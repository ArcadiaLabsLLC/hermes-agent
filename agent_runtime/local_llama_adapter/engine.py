"""The adapter's only door into upstream's engine: one ``LlamaServerSupervisor`` per serve.

Upstream owns the process (``supervisor``/``processes``: Windows job containment, restart with
backoff, the stable persisted API key, ``logs/llama-server.log``-style logging, the published
``server.json`` endpoint the ``llamacpp`` provider resolves) and the GGUF header reader. This
module adds two things upstream has no equivalent for:

* **GAP-PR-1 fallback** — the supervisor serves the executable the operator configured (a
  user-supplied ``llama-server`` or an upstream-installed build), not only a pinned-tag install.
  Upstream's ``ensure_local_runtime`` resolves the binary from ``installed_tags()``; the gap is
  a ``local_runtime.executable_path`` knob, held (no upstream PRs, owner 2026-09-24).
* **Row 9, owner-ruled KEEP** — the per-model load knobs, written as the router's
  ``--models-preset`` INI. RECORDED PARALLEL of upstream ``presets.generate_presets``, which
  derives the same INI keys from its context policy and exposes no per-model override
  ("constants, not knobs"). Retires only if upstream grows per-model preset overrides.

And one GAP-PR-2 fallback: ``scan``/``validate_model`` walk the operator's extra model roots
(upstream serves only ``models_dir()`` plus per-file sideload).
"""
from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time
import uuid
from urllib.parse import quote

from . import model_alias
from .config import GENERATION_DEFAULTS, LOAD_DEFAULTS, LocalLlamaError

_SHARD = re.compile(r"(.+)-(\d{5})-of-(\d{5})\.gguf", re.IGNORECASE)


def _fail(reason, message):
    return LocalLlamaError(reason, message, code=-32000)


def write_preset(path: Path, model) -> None:
    """The router preset: one section carrying the operator's knobs for the model being loaded."""
    from utils import atomic_write_text
    content = "version = 1\n"
    if model is not None:
        load = model["load"]
        content += f"[{model_alias(model['model_id'])}]\nmodel = {Path(model['gguf_path']).as_posix()}\n"
        values = {"ctx-size": load["context_size"], "n-gpu-layers": load["gpu_layers"],
                  "flash-attn": load["flash_attention"], "cache-type-k": load["cache_type_k"],
                  "cache-type-v": load["cache_type_v"], "jinja": "true", "parallel": 1,
                  "load-on-startup": "false"}
        if load["chat_template_path"]:
            values["chat-template-file"] = Path(load["chat_template_path"]).as_posix()
        content += "".join(f"{k} = {v}\n" for k, v in values.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, content)


class Engine:
    def __init__(self, directory: Path):
        self.directory = directory
        self.supervisor = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def preset_path(self) -> Path:
        return self.directory / "models.ini"

    @property
    def log_path(self) -> Path:
        return self.directory / "llama-server.log"

    def start(self, config) -> None:
        from hermes_cli.local_runtime.binaries import BinaryResolutionError, server_binary
        from hermes_cli.local_runtime.supervisor import LlamaServerSupervisor
        executable = Path(config["executable_path"])
        try:
            if server_binary(executable.parent).resolve() != executable.resolve():
                raise BinaryResolutionError(str(executable))
        except (BinaryResolutionError, OSError):
            raise _fail("unsupported_binary", "Choose a llama-server executable") from None
        with socket.socket() as check:
            try:
                check.bind(("127.0.0.1", config["port"]))
            except OSError as exc:
                raise _fail("port_in_use", "Configured llama port is already in use") from exc
        write_preset(self.preset_path, None)
        with self._lock:
            if self._closed:
                raise _fail("interrupted", "Hermes is stopping")
            supervisor = LlamaServerSupervisor(executable.parent, self.directory / "models", models_max=1,
                                               port=config["port"], log_path=self.log_path,
                                               preset_path=self.preset_path)
            self.supervisor = supervisor
        try:
            supervisor.start(timeout_s=30)
        except Exception as exc:
            with suppress(Exception):
                supervisor.stop()
            with self._lock:
                self.supervisor = None
                closed = self._closed
            if closed:
                raise _fail("interrupted", "Local llama operation was interrupted") from exc
            if isinstance(exc, TimeoutError):
                raise _fail("timeout", "Timed out waiting for llama.cpp") from exc
            raise _fail("router_failed", "The managed llama.cpp process exited") from exc

    def _running(self):
        with self._lock:
            if self._closed:
                raise _fail("interrupted", "Local llama operation was interrupted")
            supervisor = self.supervisor
        if supervisor is None or supervisor.proc is None or supervisor.proc.poll() is not None:
            raise _fail("router_failed", "The managed llama.cpp process exited")
        return supervisor

    def _get(self, supervisor, route, timeout=10):
        from hermes_cli.local_runtime.endpoint import managed_get_json
        try:
            return managed_get_json(supervisor.base_url.rsplit("/v1", 1)[0], supervisor.api_key, route, timeout)
        except Exception as exc:
            # Never include raw server output, payloads, paths or the credential.
            raise _fail("router_failed", "llama.cpp did not return a valid response") from exc

    def _status(self, supervisor, alias):
        rows = self._get(supervisor, "/models")
        rows = rows.get("data", []) if isinstance(rows, dict) else []
        return next((r.get("status", {}) for r in rows if r.get("id") == alias), {})

    def load(self, model) -> dict:
        alias = model_alias(model["model_id"])
        write_preset(self.preset_path, model)
        supervisor = self._running()
        self._get(supervisor, "/models?reload=1")
        try:
            supervisor.load_model(alias)
        except Exception as exc:
            raise _fail("model_load_failed", "llama.cpp could not load these weights/parameters") from exc
        deadline = time.monotonic() + 600
        while True:
            status = self._status(self._running(), alias)
            if status.get("failed"):
                raise _fail("model_load_failed", "llama.cpp could not load these weights/parameters")
            if status.get("value") == "loaded":
                break
            if time.monotonic() > deadline:
                raise _fail("timeout", "Timed out waiting for llama.cpp")
            time.sleep(.25)
        # Upstream's watchdog reloads the primary model after a router restart.
        supervisor.primary_model = alias
        return self._get(supervisor, "/props?model=" + quote(alias))

    def unload(self, model_id) -> None:
        supervisor = self._running()
        supervisor.primary_model = None
        try:
            supervisor.unload_model(model_alias(model_id))
        except Exception as exc:
            raise _fail("router_failed", "llama.cpp did not return a valid response") from exc

    def alive(self) -> bool:
        supervisor = self.supervisor
        return supervisor is not None and supervisor.proc is not None and supervisor.proc.poll() is None

    def endpoint(self):
        supervisor = self.supervisor
        if supervisor is None:
            raise LocalLlamaError("model_not_ready", "Turn on llama and load the selected model", code=4090)
        return supervisor.base_url, supervisor.api_key

    def secret(self):
        supervisor = self.supervisor
        return supervisor.api_key if supervisor is not None else None

    def stop(self) -> None:
        with self._lock:
            supervisor, self.supervisor = self.supervisor, None
        if supervisor is not None:
            supervisor.stop()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            supervisor = self.supervisor
        if supervisor is not None:
            # Cancels a start still waiting on /health, then reaps the tree.
            supervisor.stop()
        self.stop()


def _header(path: Path):
    from hermes_cli.local_runtime.gguf import read_gguf_header
    try:
        header = read_gguf_header(path)
    except OSError as exc:
        raise _fail("missing_file", "The saved model is missing or unreadable") from exc
    except Exception as exc:
        raise _fail("unsupported_model", "Not a supported GGUF file") from exc
    info = {k: v for k, v in header.metadata.items()
            if k in ("general.name", "general.architecture", "split.no", "split.count") or k.endswith(".context_length")}
    if not header.architecture or header.architecture in ("clip", "vision"):
        raise _fail("unsupported_model", "GGUF has no supported text architecture")
    return info


def validate_model(path: Path) -> dict:
    info = _header(path)
    count = info.get("split.count", 1)
    if count > 1:
        match = _SHARD.fullmatch(path.name)
        if not match or int(match[3]) != count or info.get("split.no") != 0 or int(match[2]) != 1:
            raise _fail("incomplete_model", "Select the first file of a complete GGUF shard set")
        for index in range(count):
            shard = path.with_name(f"{match[1]}-{index + 1:05d}-of-{count:05d}.gguf")
            try:
                part = _header(shard)
            except LocalLlamaError as exc:
                raise _fail("incomplete_model", "A GGUF shard is missing or unreadable") from exc
            if any(part.get(k) != info.get(k) for k in ("general.name", "general.architecture", "split.count")) or part.get("split.no") != index:
                raise _fail("incomplete_model", "GGUF shards do not belong to the same model")
    return info


def _walk(root, deadline, max_candidates, errors):
    candidates, truncated = [], False
    for parent, directories, files in os.walk(root, followlinks=False,
            onerror=lambda exc: errors.append({"path": exc.filename, "reason": "unreadable_directory"})):
        kept = []
        for directory in directories:
            try:
                info = Path(parent, directory).lstat()
            except OSError:
                errors.append({"path": str(Path(parent, directory)), "reason": "unreadable_directory"})
                continue
            # Reject links and Windows reparse points (junctions) without following them.
            if not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                kept.append(directory)
        directories[:] = kept
        for name in sorted(files):
            path = Path(parent, name)
            if path.suffix.lower() != ".gguf" or name.lower().startswith("mmproj") or path.is_symlink():
                continue
            if len(candidates) >= max_candidates or time.monotonic() > deadline:
                return candidates, True
            candidates.append(path.resolve())
        if time.monotonic() > deadline:
            return candidates, True
    return candidates, truncated


def scan(config: dict, *, max_candidates=10000, timeout=60):
    """GAP-PR-2 fallback: new presets for every complete GGUF under the extra model roots."""
    result = deepcopy(config)
    existing = {os.path.normcase(str(Path(p["gguf_path"]).resolve())) for p in result["presets"]}
    errors, candidates, truncated = [], [], False
    deadline = time.monotonic() + timeout
    for root in config["model_roots"]:
        found, cut = _walk(root, deadline, max_candidates - len(candidates), errors)
        candidates += found
        if cut:
            truncated = True
            break
    groups, singles = {}, []
    for path in candidates:
        try:
            info = _header(path)
        except LocalLlamaError as exc:
            errors.append({"path": str(path), "reason": exc.reason})
            continue
        count = info.get("split.count", 1)
        match = _SHARD.fullmatch(path.name)
        if count > 1 and match:
            groups.setdefault((str(path.parent), match[1], info.get("general.name"), count), []).append((path, info))
        elif count > 1:
            errors.append({"path": str(path), "reason": "incomplete_model"})
        else:
            singles.append((path, info))
    for key, group in groups.items():
        if {info.get("split.no") for _, info in group} != set(range(key[-1])):
            errors.append({"path": key[0], "reason": "incomplete_model"})
        else:
            singles.append(next(row for row in group if row[1].get("split.no") == 0))
    for path, info in singles:
        if os.path.normcase(str(path)) in existing:
            continue
        preset = {"model_id": str(uuid.uuid4()), "display_name": (info.get("general.name") or path.parent.name)[:120],
                  "gguf_path": str(path), "revision": 0, "load": deepcopy(LOAD_DEFAULTS),
                  "generation": deepcopy(GENERATION_DEFAULTS)}
        contexts = [v for k, v in info.items() if k.endswith(".context_length") and type(v) is int]
        if contexts:
            preset["load"]["context_size"] = min(32768, min(contexts)) // 256 * 256
            preset["generation"]["max_output_tokens"] = min(4096, preset["load"]["context_size"] // 2)
        result["presets"].append(preset)
        existing.add(os.path.normcase(str(path)))
    return result, {"candidates": len(candidates), "errors": errors, "truncated": truncated}
