"""The guarded half of the contract: receipts, epoch/revision guards, the turn lease, the log cursor.

Rows 12, 13 and 17 of the 2026-09-24 feature diff, owner-ruled KEEP: upstream's local runtime
has no idempotent mutation receipts, no restart epoch, no whole-turn lease and only a log FILE.
Everything that touches a process goes through :class:`engine.Engine` (upstream's supervisor).
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from agent_runtime.clock import iso_stamp
from agent_runtime.store_file_io import read_json_object
from utils import atomic_json_write

from . import SCHEMA, model_alias
from .config import (ConfigStore, LocalLlamaError, identifier, integer, publish_journal,
                     recover_journal, validate_config, validate_parameters)
from .engine import Engine, scan, validate_model

__layer__ = "stores"

_LOG_TAIL_BYTES = 256 * 1024
_ACTIVE = ("queued", "running")


class LocalLlamaManager:
    def __init__(self, root: Path, config_path: Path, install_id: str, *, engine_factory=Engine):
        self.directory = root / "local_llama"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.config_store = ConfigStore(config_path)
        recover_journal(self.directory, self.config_store)
        self.config = self.config_store.read()
        self.install_id = install_id
        self.epoch = str(uuid.uuid4())
        self.revision = 0
        self.config_revision = read_json_object(self.directory / "state.json").get("config_revision", 0)
        self.engine = engine_factory(self.directory)
        self.server, self.server_error = "off", None
        self.loaded = None
        self.model_states, self.leases = {}, {}
        self.operation, self._worker = None, None
        self.logs = deque(maxlen=2000)
        self._log_sequence = 0
        self._log_offset = None
        self.closed = False
        self._refresh_unavailable()
        self.receipts = read_json_object(self.directory / "operations.json")
        for row in self.receipts.values():
            if row["operation"]["state"] in _ACTIVE:
                row["operation"].update(state="interrupted", finished_at=iso_stamp(None),
                                        error=LocalLlamaError("interrupted", "Hermes restarted during this operation").as_error())
        self._persist()
        from .setup import SetupManager
        self.setup = SetupManager(self)

    def _refresh_unavailable(self):
        self.unavailable = {p["model_id"]: "missing_file" for p in self.config["presets"]
                            if not Path(p["gguf_path"]).is_file()}

    def _persist(self):
        terminal = sorted((k for k, v in self.receipts.items() if v["operation"]["state"] not in _ACTIVE),
                          key=lambda k: self.receipts[k]["accepted_at"])
        for key in terminal:
            if len(self.receipts) <= 1000 and time.time() - self.receipts[key]["accepted_at"] < 7 * 86400:
                break
            del self.receipts[key]
        atomic_json_write(self.directory / "operations.json", self.receipts)
        atomic_json_write(self.directory / "state.json", {"config_revision": self.config_revision})

    def _log(self, message, level="info"):
        self._log_sequence += 1
        self.logs.append({"sequence": self._log_sequence, "time": iso_stamp(None), "level": level, "message": message})

    def _tail_engine_log(self):
        """Row 17: fold new lines of upstream's server log into the cursor ring, credential redacted."""
        path = self.engine.log_path
        try:
            size = path.stat().st_size
        except OSError:
            return
        if self._log_offset is None or size < self._log_offset:
            self._log_offset = max(0, size - _LOG_TAIL_BYTES) if self._log_offset is None else 0
        if size == self._log_offset:
            return
        with path.open("rb") as stream:
            stream.seek(self._log_offset)
            chunk = stream.read(_LOG_TAIL_BYTES)
        complete = chunk.rfind(b"\n") + 1
        if not complete:
            return
        self._log_offset += complete
        secret = self.engine.secret()
        for line in chunk[:complete].decode("utf-8", errors="replace").splitlines():
            if secret:
                line = line.replace(secret, "[redacted]")
            if line.strip():
                self._log(line[:2000], level="server")

    def _model(self, model_id):
        row = next((p for p in self.config["presets"] if p["model_id"] == model_id), None)
        if row is None:
            raise LocalLlamaError("model_not_found", "Saved model does not exist", code=4001)
        return row

    def capabilities(self):
        return {"supported": True, "reason": None, "router_load_unload": True,
                "parameter_schema_version": 1,
                "supported_values": {"thinking": ["auto"], "flash_attention": ["auto", "on", "off"],
                                     "cache_type_k": ["f16", "q8_0", "q4_0"], "cache_type_v": ["f16", "q8_0", "q4_0"]}}

    def busy(self):
        return self.setup.active is not None or (self.operation is not None and self.operation["state"] in _ACTIVE)

    def active_operation(self):
        if self.setup.active is not None:
            op = self.setup.active
            return {"operation_id": op["operation_id"], "request_id": op["request_id"],
                    "kind": "setup." + op["kind"], "state": "running", "progress": None,
                    "error": None, "accepted_at": op["accepted_at"]}
        return self.operation if self.operation and self.operation["state"] in _ACTIVE else None

    def _server_view(self):
        # Upstream's supervisor restarts a crashed router on its own; between the crash and the
        # restart the server is coming back, not off.
        state = self.server
        if state == "running" and not self.engine.alive():
            state = "starting"
        return {"state": state, "error": self.server_error}

    def status(self, *, operation_id=None, request_id=None):
        with self.lock:
            if operation_id and request_id:
                raise LocalLlamaError("invalid_parameter", "Choose one operation lookup")
            operation = self.active_operation() or self.operation
            if request_id:
                operation = self.receipts.get(identifier(request_id, "request_id"), {}).get("operation")
            if operation_id:
                identifier(operation_id, "operation_id")
                operation = next((r["operation"] for r in self.receipts.values()
                                  if r["operation"]["operation_id"] == operation_id), None)
            if (operation_id or request_id) and operation is None:
                raise LocalLlamaError("operation_not_found", "Operation receipt is no longer available", code=4001)
            rows = []
            for preset in self.config["presets"]:
                state = self.model_states.get(preset["model_id"], {})
                rows.append({"model_id": preset["model_id"], "display_name": preset["display_name"],
                             "context_length": preset["load"]["context_size"],
                             "preset_revision": preset["revision"], "state": state.get("state", "unloaded"),
                             "selectable": preset["model_id"] not in self.unavailable,
                             "unavailable_reason": self.unavailable.get(preset["model_id"]),
                             "active_parameters": state.get("active_parameters"), "error": state.get("error")})
            return deepcopy({"schema": SCHEMA, "install_id": self.install_id, "epoch": self.epoch,
                             "revision": self.revision, "config_revision": self.config_revision,
                             "configured": bool(self.config.get("executable_path")),
                             "capabilities": self.capabilities(), "server": self._server_view(),
                             "models": rows, "active_turns": list(self.leases.values()), "operation": operation,
                             "active_operation": self.active_operation()})

    def config_get(self):
        with self.lock:
            return {"schema": SCHEMA, "install_id": self.install_id, "config_revision": self.config_revision,
                    "config": deepcopy(self.config), "capabilities": self.capabilities()}

    def logs_get(self, cursor=None, limit=100):
        integer(limit, "limit", 1, 200)
        try:
            after = int(cursor) if cursor is not None else None
        except (ValueError, TypeError):
            raise LocalLlamaError("invalid_parameter", "Invalid log cursor") from None
        with self.lock:
            self._tail_engine_log()
            candidates = [r for r in self.logs if after is None or r["sequence"] > after]
            rows = candidates[-limit:] if after is None else candidates[:limit]
            return {"schema": SCHEMA, "install_id": self.install_id,
                    "lines": [{k: v for k, v in row.items() if k != "sequence"} for row in rows],
                    "next_cursor": str(rows[-1]["sequence"]) if rows else cursor,
                    "truncated": len(candidates) > len(rows)}

    def guard(self, normalized):
        """The epoch/revision guard every mutation (and every setup mutation) passes."""
        if normalized.get("expect_epoch") != self.epoch:
            raise LocalLlamaError("stale_epoch", "Hermes restarted; refresh local llama state", code=4090)
        for name, actual in (("expect_revision", self.revision), ("expect_config_revision", self.config_revision)):
            integer(normalized.get(name), name)
            if normalized[name] != actual:
                raise LocalLlamaError("stale_revision", "Local llama state changed; refresh and retry", code=4090)

    def submit(self, kind, params):
        allowed = {"config.set": ("config",), "catalog.scan": (), "start": (), "stop": (),
                   "load": ("model_id", "preset_revision", "load", "generation", "replace_model_id"),
                   "unload": ("model_id",)}
        if kind not in allowed:
            raise LocalLlamaError("unknown_operation", "Unknown local llama operation")
        request_id = identifier(params.get("request_id"), "request_id")
        keys = ("request_id", "expect_epoch", "expect_revision", "expect_config_revision") + allowed[kind]
        if set(params) - set(keys):
            raise LocalLlamaError("invalid_parameter", "Unknown local llama operation parameter")
        params = dict(params)
        for key in ("model_id", "replace_model_id"):
            if params.get(key) is not None:
                params[key] = identifier(params[key], key)
        normalized = {k: params.get(k) for k in keys}
        try:
            canonical = json.dumps({"kind": kind, "params": normalized}, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise LocalLlamaError("invalid_parameter", "Parameters must contain finite JSON values") from None
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.lock:
            if self.closed:
                raise LocalLlamaError("manager_unavailable", "Local llama manager is stopping", code=-32000)
            if request_id in self.receipts:
                receipt = self.receipts[request_id]
                if receipt["fingerprint"] != fingerprint:
                    raise LocalLlamaError("idempotency_conflict", "Request ID was already used for a different operation", code=4090)
                return self._reply(receipt["operation"])
            self.guard(normalized)
            if self.busy():
                raise LocalLlamaError("operation_busy", "A local llama operation is already running", code=4090)
            if self.leases and kind in ("start", "stop", "load", "unload"):
                raise LocalLlamaError("active_turns", "A local model turn is active", code=4090,
                                      active_turns=deepcopy(list(self.leases.values())))
            self._precheck(kind, params)
            op = {"operation_id": str(uuid.uuid4()), "request_id": request_id, "kind": kind, "state": "queued",
                  "model_id": normalized.get("model_id"), "progress": None, "error": None,
                  "started_at": None, "finished_at": None}
            previous_operation, previous_revision = self.operation, self.revision
            self.receipts[request_id] = {"fingerprint": fingerprint, "accepted_at": time.time(), "operation": op}
            self.operation = op
            self.revision += 1
            try:
                self._persist()
            except OSError as exc:
                self.receipts.pop(request_id, None)
                self.operation, self.revision = previous_operation, previous_revision
                raise LocalLlamaError("storage_unavailable", "Cannot save the local llama operation receipt", code=-32000) from exc
            self._worker = threading.Thread(target=self._execute, args=(kind, deepcopy(normalized), op), daemon=True,
                                            name="local-llama-operation")
            self._worker.start()
            return self._reply(op)

    def _precheck(self, kind, params):
        if kind == "load":
            model = self._model(identifier(params.get("model_id")))
            integer(params.get("preset_revision"), "preset_revision")
            if params.get("preset_revision") != model["revision"]:
                raise LocalLlamaError("stale_revision", "Model preset changed", code=4090)
            validate_parameters(params.get("load"), params.get("generation"))
            if params["generation"]["thinking"] != "auto":
                raise LocalLlamaError("unsupported_parameter", "This preset has no verified thinking override")
            if self.server != "running":
                raise LocalLlamaError("model_not_ready", "Turn on llama first", code=4090)
            if self.loaded and params.get("replace_model_id") != self.loaded:
                active = self.model_states[self.loaded]["active_parameters"]
                if self.loaded != model["model_id"] or active["load"] != params["load"] or active["generation"] != params["generation"]:
                    raise LocalLlamaError("replacement_required", "Explicitly name the loaded model to replace", code=4090)
        elif kind == "unload":
            self._model(identifier(params.get("model_id")))
        elif kind == "start" and not self.config.get("executable_path"):
            raise LocalLlamaError("unconfigured", "Configure the llama.cpp executable first", code=-32000)

    def _reply(self, operation):
        return {"schema": SCHEMA, "install_id": self.install_id,
                "operation": deepcopy(operation), "state": self.status()}

    def _transition(self, server=None, model=None, state=None, parameters=None):
        with self.lock:
            if self.closed:
                raise LocalLlamaError("interrupted", "Hermes is stopping", code=-32000)
            if server is not None:
                self.server, self.server_error = server, None
            if model is not None:
                self.model_states[model] = {"state": state, "active_parameters": parameters, "error": None}
            self.revision += 1

    def save(self, config):
        with self.lock:
            if self.closed:
                raise LocalLlamaError("interrupted", "Hermes is stopping", code=-32000)
            publish_journal(self.directory, self.config_store, self.config, config, self.config_revision + 1)
            self.config = config
            self._refresh_unavailable()
            self.config_revision += 1
            self.revision += 1

    def _set_config(self, config):
        config = validate_config(config)
        with self.lock:
            if self.server != "off" and any(config[k] != self.config[k] for k in ("executable_path", "port", "model_roots")):
                raise LocalLlamaError("restart_required", "Turn off llama before changing server settings", code=4090)
            if self.loaded and not any(p["model_id"] == self.loaded for p in config["presets"]):
                raise LocalLlamaError("restart_required", "Unload a model before removing its preset", code=4090)
            old = {p["model_id"]: p for p in self.config["presets"]}
            for preset in config["presets"]:
                previous = old.get(preset["model_id"])
                if previous and preset["revision"] != previous["revision"]:
                    raise LocalLlamaError("stale_revision", "Model preset changed", code=4090)
                preset["revision"] = previous["revision"] + (preset != previous) if previous else 0
        self.save(config)

    def _load(self, params):
        model = deepcopy(self._model(params["model_id"]))
        model.update(load=params["load"], generation=params["generation"])
        wanted = {"load": model["load"], "generation": model["generation"],
                  "effective_context_size": model["load"]["context_size"]}
        if self.loaded == model["model_id"] and self.model_states[self.loaded]["active_parameters"] == wanted:
            return False
        info = validate_model(Path(model["gguf_path"]))
        contexts = [v for k, v in info.items() if k.endswith(".context_length") and type(v) is int]
        if contexts and model["load"]["context_size"] > min(contexts):
            raise LocalLlamaError("invalid_parameter", "Context exceeds the model metadata maximum")
        if self.loaded:
            self._unload(self.loaded)
        self._transition(model=model["model_id"], state="loading")
        props = self.engine.load(model)
        caps = props.get("chat_template_caps", {})
        if not caps.get("supports_tools") or not caps.get("supports_tool_calls"):
            raise LocalLlamaError("unsupported_model", "This model template does not support agent tool calls", code=-32000)
        context = props.get("default_generation_settings", {}).get("n_ctx")
        if type(context) is not int or context != model["load"]["context_size"]:
            raise LocalLlamaError("context_mismatch", "Loaded context does not match the requested context", code=-32000)
        with self.lock:
            self.loaded = model["model_id"]
        self._transition(model=self.loaded, state="ready", parameters={**wanted, "effective_context_size": context})
        return True

    def _execute(self, kind, params, op):
        with self.lock:
            op.update(state="running", started_at=iso_stamp(None))
        try:
            if kind == "config.set":
                self._set_config(params["config"])
            elif kind == "catalog.scan":
                config, report = scan(self.config)
                self.save(config)
                op["scan"] = report
            elif kind == "start" and self.server != "running":
                if self.server != "off":
                    raise LocalLlamaError("restart_required", "Turn off llama to clear the previous failure", code=4090)
                self._transition(server="starting")
                self.engine.start(self.config)
                self._transition(server="running")
            elif kind == "stop":
                self._transition(server="stopping")
                try:
                    if self.loaded:
                        self.engine.unload(self.loaded)
                finally:
                    self.engine.stop()
                with self.lock:
                    self.loaded = None
                    self.model_states.clear()
                self._transition(server="off")
            elif kind == "load":
                self._load(params)
            elif kind == "unload" and self.loaded == params["model_id"]:
                self._unload(self.loaded)
            with self.lock:
                if self.closed:
                    raise LocalLlamaError("interrupted", "Hermes stopped", code=-32000)
                op.update(state="succeeded", finished_at=iso_stamp(None))
                self._log(kind + " succeeded")
        except Exception as exc:
            self._fail(kind, params, op, exc)
        finally:
            with self.lock:
                self.revision += 1
                if not self.closed:
                    self._persist()

    def _fail(self, kind, params, op, exc):
        error = exc if isinstance(exc, LocalLlamaError) else LocalLlamaError(
            "operation_failed", "Local llama operation failed; verify configuration and available memory", code=-32000)
        router_failed = kind in ("start", "stop", "unload")
        loading = kind == "load" and self.model_states.get(params["model_id"], {}).get("state") == "loading"
        if loading:
            try:
                self.engine.unload(params["model_id"])
            except Exception:
                router_failed = True
        if router_failed:
            self.engine.stop()
        with self.lock:
            if router_failed:
                self.server, self.server_error = "failed", error.as_error()
                self.loaded = None
                self.model_states.clear()
            elif loading:
                self.loaded = None
                self.model_states[params["model_id"]] = {"state": "failed", "active_parameters": None,
                                                        "error": error.as_error()}
            op.update(state="interrupted" if self.closed else "failed", error=error.as_error(), finished_at=iso_stamp(None))
            self._log(kind + " failed: " + error.reason)

    def _unload(self, model_id):
        self._transition(model=model_id, state="unloading")
        self.engine.unload(model_id)
        with self.lock:
            self.loaded = None
        self._transition(model=model_id, state="unloaded")

    @contextmanager
    def lease(self, model_id, turn_id, persona_instance_id):
        """Row 12: a whole turn holds the model; start/stop/load/unload refuse while it is held."""
        key = str(uuid.uuid4())
        with self.lock:
            if self.busy():
                raise LocalLlamaError("operation_busy", "Local llama is changing state", code=4090)
            self._ready(model_id)
            self.leases[key] = {"turn_id": turn_id, "persona_instance_id": persona_instance_id, "model_id": model_id}
            self.revision += 1
        try:
            yield self.runtime(model_id)
        finally:
            with self.lock:
                self.leases.pop(key, None)
                self.revision += 1

    def _ready(self, model_id):
        if self.closed or self.server != "running" or self.loaded != model_id:
            raise LocalLlamaError("model_not_ready", "Load the selected local model before sending a message", code=4090)

    def runtime(self, model_id):
        """The turn's route: upstream's ``llamacpp`` provider, pinned to THIS supervisor's endpoint."""
        with self.lock:
            self._ready(model_id)
            parameters = deepcopy(self.model_states[model_id]["active_parameters"])
            base_url, _ = self.engine.endpoint()
        from hermes_cli.runtime_provider import resolve_runtime_provider
        try:
            resolved = resolve_runtime_provider(requested="llamacpp")
        except Exception as exc:
            raise LocalLlamaError("model_not_ready", "Turn on llama and load the selected model", code=4090) from exc
        if resolved.get("base_url") != base_url:
            # Another llama.cpp server holds the machine's managed endpoint; never route a turn to it.
            raise LocalLlamaError("model_not_ready", "Another llama.cpp server holds the managed endpoint", code=4090)
        return {"provider": resolved["provider"], "model": model_alias(model_id),
                "api_mode": resolved.get("api_mode") or "chat_completions", "base_url": resolved["base_url"],
                "api_key": resolved["api_key"], "local_parameters": parameters}

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.operation and self.operation["state"] in _ACTIVE:
                self.operation.update(state="interrupted", finished_at=iso_stamp(None),
                                      error=LocalLlamaError("interrupted", "Hermes service stopped").as_error())
            self._persist()
        self.engine.close()
        self.setup.close()
        if self._worker is not None:
            self._worker.join(timeout=5)
