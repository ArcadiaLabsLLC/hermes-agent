"""The setup verbs (``hermes.local_llama.setup/v1``) over upstream's installer.

Row 3 ADOPT: an install is upstream ``binaries.ensure_engine(backend)`` — PM installs the
backend's pinned ``llamacpp-*`` package into its store, verifies every archive and hands back the
exact binary (re-seated at the 2026-09-25 merge from the retired ``ensure_runtime_installed`` /
``default_tag`` / ``resolve_assets`` / ``installed_tags`` / ``manifest_verified`` /
``server_binary``). ``releases.list`` offers one release per PM pin (``pinned_tag``) with one
variant per backend ``unavailable_reason`` clears for this host; inventory is
``installed_engine`` per backend; ``installation.plan``'s ``directory`` is PM's store root. Row 5 ADOPT: ``hardware.get`` reads
``probe_budget``. GAP-PR-1 fallback: ``installations.detect/validate/activate`` still accept a
user-supplied ``llama-server``; activation of either kind writes ``executable_path``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid

from agent_runtime.store_file_io import iso_stamp, read_json_object
from utils import atomic_json_write

from . import SETUP_SCHEMA
from .config import LocalLlamaError, identifier

ACTIVE = ("queued", "running", "cancelling")
_ROUTER_FLAGS = ("--models-dir", "--models-preset", "--models-max", "--models-autoload")
_INSTALL_HEADROOM_BYTES = 3 * 1024**3
_BACKENDS = ("cpu", "cuda", "vulkan", "hip")
_PHASES = {"download": "downloading", "extract": "extracting", "verify": "verifying"}


def fail(reason, message):
    raise LocalLlamaError(reason, message, code=-32000)


def host_path(value, *, directory=False):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        fail("invalid_path", "Enter an absolute path on the Hermes host")
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")):
        fail("invalid_path", "Use an absolute local host path; network paths are not supported")
    for part in path.parts[1:]:
        if part in (".", "..") or ":" in part or part.endswith((".", " ")):
            fail("invalid_path", "The path contains an unsafe component")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            fail("invalid_path", "The path contains a reserved filename")
    for parent in [path, *path.parents]:
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            fail("unsafe_path", "Links and junctions cannot be used for managed installation")
    if not path.exists() or (directory and not path.is_dir()):
        fail("missing_file", "This location does not exist on the Hermes host")
    return path.resolve()


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(executable):
    """Validate a llama-server the supervisor can drive: router flags present, it runs."""
    from hermes_cli.local_runtime.processes import server_child_env
    executable = host_path(str(executable))
    # Upstream hands the supervisor the exact binary and never scans a directory for one, so
    # the check is the file itself plus the router-flag probe below.
    if not executable.is_file():
        fail("unsupported_binary", "Choose a llama-server executable")
    outputs = []
    for flag in ("--version", "--help"):
        try:
            result = subprocess.run([str(executable), flag], capture_output=True, timeout=10, cwd=str(executable.parent),
                                    env=server_child_env(os.environ), text=True, encoding="utf-8", errors="replace",
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            fail("probe_timeout", "Binary validation exceeded its time limit")
        except OSError:
            fail("unsupported_binary", "llama-server could not start; check its runtime dependencies")
        if result.returncode:
            fail("unsupported_binary", "llama-server could not start; check its runtime dependencies")
        outputs.append((result.stdout + result.stderr)[:256 * 1024])
    if not all(flag in outputs[1] for flag in _ROUTER_FLAGS):
        fail("unsupported_binary", "This llama.cpp build lacks managed router support")
    return {"executable_path": str(executable), "version": outputs[0].strip()[:512],
            "sha256": _digest(executable), "compatibility": "compatible", "capabilities": list(_ROUTER_FLAGS)}


def _host_label():
    return f"{platform.system().lower()}-{platform.machine().lower()}"


_PM_READ_ERRORS = (RuntimeError, KeyError, OSError, ValueError)


def _pinned_backends():
    """``{backend: pinned tag}`` for every backend PM can install on this host."""
    from hermes_cli.local_runtime.binaries import BACKEND_PACKAGES, pinned_tag, unavailable_reason
    backends = ("metal",) if platform.system() == "Darwin" else _BACKENDS
    pinned = {}
    for backend in backends:
        if backend not in BACKEND_PACKAGES:
            continue
        try:
            if unavailable_reason(backend) is None:
                pinned[backend] = pinned_tag(backend)
        except _PM_READ_ERRORS:
            continue
    return pinned


def _variants(tag):
    from hermes_cli.local_runtime.binaries import BACKEND_PACKAGES
    return [{"variant_id": _host_label() + "-" + backend, "backend": backend, "download_bytes": 0,
             "artifacts": [{"asset_id": BACKEND_PACKAGES[backend], "name": BACKEND_PACKAGES[backend],
                            "size_bytes": 0, "sha256": ""}]}
            for backend, pinned in _pinned_backends().items() if pinned == tag]


def installed_runtimes():
    """PM's installed engines, as inventory rows (derived live, never stored)."""
    from hermes_cli.local_runtime.binaries import BACKEND_PACKAGES, installed_engine
    rows, seen = [], set()
    for backend in BACKEND_PACKAGES:
        try:
            engine = installed_engine(backend)
        except _PM_READ_ERRORS:
            continue
        if engine is None or engine.binary in seen:
            continue
        seen.add(engine.binary)
        directory = engine.binary.parent
        rows.append({"installation_id": str(uuid.uuid5(uuid.NAMESPACE_URL, directory.resolve().as_uri())),
                     "executable_path": str(engine.binary.resolve()), "version": engine.tag,
                     "compatibility": "compatible", "tag": engine.tag, "variant_id": _host_label() + "-" + engine.backend,
                     "directory": str(directory)})
    return rows


class SetupManager:
    def __init__(self, manager):
        self.manager = manager
        self.directory = manager.directory / "setup"
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / "state.json"
        self.data = read_json_object(self.path) or {"inventory": [], "receipts": {}, "inventory_revision": 0}
        self.data.setdefault("cancellations", {})
        self.plans, self.validations = {}, {}
        self.cancel_event = threading.Event()
        self.worker, self.active = None, None
        for receipt in self.data["receipts"].values():
            op = receipt["operation"]
            if op["state"] in ACTIVE:
                # An upstream install publishes atomically through its verified manifest; a crash
                # mid-install leaves nothing an inventory row points at.
                op.update(state="interrupted", phase="finished", can_cancel=False, finished_at=iso_stamp(None),
                          error={"reason": "interrupted", "message": "Hermes restarted; review the installation before retrying."},
                          result={"cleanup": "not_needed", "retained_paths": []})
        self._persist()

    def envelope(self, **fields):
        return {"schema": SETUP_SCHEMA, "install_id": self.manager.install_id,
                "epoch": self.manager.epoch, **deepcopy(fields)}

    def _persist(self):
        receipts = self.data["receipts"]
        terminal = sorted((k for k, v in receipts.items() if v["operation"]["state"] not in ACTIVE),
                          key=lambda k: receipts[k]["accepted_time"])
        for key in terminal:
            if len(receipts) <= 1000 and time.time() - receipts[key]["accepted_time"] < 7 * 86400:
                break
            del receipts[key]
        atomic_json_write(self.path, self.data)

    def inventory(self):
        rows = [dict(r) for r in self.data["inventory"]]
        known = {r["executable_path"] for r in rows}
        return rows + [r for r in installed_runtimes() if r["executable_path"] not in known]

    def capabilities(self):
        automatic = bool(_pinned_backends())
        return self.envelope(features={"detect": True, "path_validate": True, "hardware": True,
            "releases": automatic, "install": automatic, "cancel": automatic, "activate": True,
            "offline_import": False, "host_browser": False}, automatic_platforms=[_host_label()] if automatic else [],
            unsupported_reason=None if automatic else "No prebuilt llama.cpp runtime exists for this host; use an existing executable.")

    def status(self, request_id=None, operation_id=None):
        with self.manager.lock:
            if request_id and operation_id:
                fail("invalid_parameter", "Choose one receipt lookup")
            requested = None
            if request_id:
                requested = self.data["receipts"].get(identifier(request_id), {}).get("operation")
            elif operation_id:
                identifier(operation_id)
                requested = next((r["operation"] for r in self.data["receipts"].values()
                                  if r["operation"]["operation_id"] == operation_id), None)
            inventory = self.inventory()
            path = self.manager.config.get("executable_path")
            selected = next((r["installation_id"] for r in inventory if r["executable_path"] == path), None)
            return self.envelope(inventory=inventory, inventory_revision=self.data["inventory_revision"],
                active_installation_id=selected, active_operation=self.active, requested_operation=requested,
                lookup_state=("found" if requested else "not_found") if request_id or operation_id else "not_requested")

    def detect(self):
        with self.manager.lock:
            configured = self.manager.config.get("executable_path")
            candidates = [r["executable_path"] for r in self.inventory()]
        if configured:
            candidates.insert(0, configured)
        found = shutil.which("llama-server")
        if found:
            candidates.append(found)
        rows, issues = [], []
        for path in dict.fromkeys(candidates[:100]):
            try:
                checked = host_path(path)
                rows.append({"executable_path": str(checked), "state": "candidate", "version": None,
                             "compatibility": "unknown", "configured": path == configured})
                if path == configured:
                    rows[-1].update(probe(checked), state="validated")
            except LocalLlamaError as exc:
                issues.append({"reason": exc.reason, "message": str(exc)})
        return self.envelope(installations=rows, complete=not issues, issues=issues,
                             checked_scopes=["configured executable", "managed inventory", "PATH"], observed_at=iso_stamp(None))

    def validate(self, path):
        result = probe(path)
        token = str(uuid.uuid4())
        with self.manager.lock:
            self.validations = {k: v for k, v in self.validations.items() if v["expires"] > time.time()}
            if len(self.validations) >= 100:
                fail("operation_busy", "Too many pending validations; wait before trying again")
            self.validations[token] = {**result, "expires": time.time() + 900}
        return self.envelope(installation=result, validation_token=token, expires_in_seconds=900)

    def hardware(self):
        import psutil
        from hermes_cli.local_runtime.binaries import select_backend
        from hermes_cli.local_runtime.hardware import probe_budget
        budget = probe_budget(planning=True)
        memory = psutil.virtual_memory()
        # probe_budget answers a discrete (non-UMA) budget only when nvidia-smi saw a device.
        discrete = not budget.uma and budget.total_device_bytes > 0
        backend = select_backend("nvidia" if discrete else None)
        return self.envelope(os=platform.system(), architecture=platform.machine(),
                             ram_bytes=memory.total or None, available_ram_bytes=memory.available or None,
                             gpu_compatibility="compatible" if discrete else "unknown", recommended_backend=backend,
                             recommendation="CUDA uses the detected NVIDIA device." if backend == "cuda"
                             else "CPU needs no GPU driver. Choose CUDA only with a compatible NVIDIA driver.")

    def paths(self, path, purpose):
        if purpose not in ("installation_parent", "model_root"):
            fail("invalid_parameter", "Unsupported path purpose")
        target = host_path(path, directory=True)
        return self.envelope(normalized_path=str(target), exists=True,
                             writable=os.access(target, os.W_OK), free_bytes=shutil.disk_usage(target).free)

    def releases(self):
        tags = sorted(set(_pinned_backends().values()))
        return self.envelope(releases=[{"release_id": tag, "tag": tag, "stable_alias": None,
                                        "prerelease": False, "variants": _variants(tag)} for tag in tags])

    def plan(self, params):
        from pm.paths import store_root
        if not self.capabilities()["features"]["install"]:
            fail("unsupported_platform", "Use an existing executable on this host")
        tag, release_id, variant_id = (params.get(k) for k in ("tag", "release_id", "variant_id"))
        # The destination is validated for the operator's benefit; PM installs into its own store.
        parent = host_path(params.get("destination_parent"), directory=True)
        variant = next((v for v in _variants(tag) if v["variant_id"] == variant_id), None) if release_id == tag else None
        if variant is None:
            fail("release_unavailable", "This release has no asset bundle for that variant")
        target = store_root()
        existing = target
        while not existing.exists():
            existing = existing.parent
        free = shutil.disk_usage(existing).free
        if free < _INSTALL_HEADROOM_BYTES:
            fail("disk_full", "Free space on the Hermes drive for the download and its extraction")
        with self.manager.lock:
            self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.time()}
            if len(self.plans) >= 100:
                fail("operation_busy", "Too many pending installation plans")
            plan = {"plan_id": str(uuid.uuid4()), "plan_revision": 1, "expires": time.time() + 900,
                    "release_id": release_id, "tag": tag, "variant_id": variant_id,
                    "destination_parent": str(parent), "directory": str(target), "variant": variant,
                    "required_free_bytes": _INSTALL_HEADROOM_BYTES, "free_bytes": free,
                    "config_revision": self.manager.config_revision,
                    "inventory_revision": self.data["inventory_revision"],
                    "warning_ids": ["cuda_driver"] if variant["backend"] == "cuda" else []}
            self.plans[plan["plan_id"]] = plan
        return self.envelope(plan=deepcopy(plan))

    def submit(self, kind, params):
        m = self.manager
        request_id = identifier(params.get("request_id"), "request_id")
        fingerprint = hashlib.sha256(json.dumps({"kind": kind, "params": params}, sort_keys=True,
                                                allow_nan=False).encode()).hexdigest()
        with m.lock:
            previous = self.data["receipts"].get(request_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    fail("idempotency_conflict", "Request ID belongs to a different operation")
                return self.envelope(operation=previous["operation"])
            if m.closed:
                fail("manager_unavailable", "Hermes is stopping")
            if m.busy():
                fail("operation_busy", "Another local llama operation is active")
            if m.leases:
                fail("active_turns", "Wait for the active local model response")
            if m.server != "off":
                fail("server_must_be_off", "Turn off llama before installing or changing its version")
            m.guard({key: params.get(key) for key in ("expect_epoch", "expect_revision", "expect_config_revision")})
            payload = self._payload(kind, params)
            operation = {"operation_id": str(uuid.uuid4()), "request_id": request_id, "kind": kind,
                         "state": "queued", "phase": "queued", "sequence": 0,
                         "bytes_done": None, "bytes_total": None, "can_cancel": kind == "install",
                         "accepted_at": iso_stamp(None), "finished_at": None, "error": None, "result": None}
            self.data["receipts"][request_id] = {"fingerprint": fingerprint, "operation": operation, "accepted_time": time.time()}
            try:
                self._persist()
            except OSError:
                del self.data["receipts"][request_id]
                fail("storage_unavailable", "Cannot save installation receipt; nothing was started")
            self.active = operation
            self.cancel_event.clear()
            m.revision += 1
            self.worker = threading.Thread(target=self._execute, args=(operation, payload), daemon=True, name="local-llama-setup")
            self.worker.start()
            return self.envelope(operation=operation)

    def _payload(self, kind, params):
        if kind == "install":
            plan = self.plans.get(params.get("plan_id"))
            if plan is None or plan["expires"] <= time.time():
                fail("plan_expired", "Review the installation again")
            if (type(params.get("plan_revision")) is not int or params.get("plan_revision") != 1
                    or plan["config_revision"] != self.manager.config_revision
                    or plan["inventory_revision"] != self.data["inventory_revision"]):
                fail("plan_changed", "Installation facts changed; review again")
            warnings = params.get("acknowledged_warning_ids")
            if not isinstance(warnings, list) or len(warnings) > 16 or not all(isinstance(w, str) for w in warnings):
                fail("invalid_parameter", "Warning acknowledgements must be a list")
            if set(warnings) != set(plan["warning_ids"]):
                fail("approval_required", "Review the selected GPU runtime dependency")
            return deepcopy(plan)
        if kind == "activate":
            token, installation_id = params.get("validation_token"), params.get("installation_id")
            if bool(token) == bool(installation_id):
                fail("invalid_parameter", "Choose one validated installation")
            if params.get("expect_inventory_revision") != self.data["inventory_revision"]:
                fail("stale_revision", "Installation inventory changed")
            payload = deepcopy(self.validations.get(token) if token else
                               next((r for r in self.inventory() if r["installation_id"] == installation_id), None))
            if payload is None or payload.get("expires", float("inf")) < time.time():
                fail("plan_expired", "Validate this installation again")
            return payload
        fail("invalid_parameter", "Unsupported setup operation")

    def cancel(self, operation_id, request_id):
        identifier(operation_id)
        identifier(request_id)
        with self.manager.lock:
            previous = self.data["cancellations"].get(request_id)
            if previous is not None and previous != operation_id:
                fail("idempotency_conflict", "Cancellation request belongs to a different operation")
            row = next((r["operation"] for r in self.data["receipts"].values() if r["operation"]["operation_id"] == operation_id), None)
            if row is None:
                fail("operation_not_found", "Installation receipt was not found")
            self.data["cancellations"][request_id] = operation_id
            if len(self.data["cancellations"]) > 1000:
                del self.data["cancellations"][next(iter(self.data["cancellations"]))]
            self._persist()
            if row["state"] not in ACTIVE:
                return self.envelope(operation=row)
            if not row["can_cancel"]:
                fail("cancel_not_available", "Installation is publishing; wait for the result")
            row["state"] = "cancelling"
            self._persist()
            self.cancel_event.set()
            return self.envelope(operation=row)

    def _tick(self, op, phase, done=None, total=None):
        with self.manager.lock:
            if self.manager.closed or self.cancel_event.is_set():
                fail("cancelled", "Installation cancelled")
            if phase != op["phase"]:
                self.manager._log("setup " + op["kind"] + ": " + phase)
            op.update(phase=phase, bytes_done=done, bytes_total=total or None, sequence=op["sequence"] + 1)
            self.manager.revision += 1

    def _install(self, op, payload):
        from hermes_cli.local_runtime.binaries import ensure_engine
        if _pinned_backends().get(payload["variant"]["backend"]) != payload["tag"]:
            fail("plan_changed", "The pinned llama.cpp release changed; review the installation again")
        engine = ensure_engine(
            payload["variant"]["backend"],
            progress=lambda stage, done, total, _label: self._tick(op, _PHASES.get(stage, stage), done, total))
        install_dir = engine.binary.parent
        self._tick(op, "publishing")
        with self.manager.lock:
            op["can_cancel"] = False
            self.data["inventory_revision"] += 1
            self._persist()
        row = next((r for r in installed_runtimes() if Path(r["directory"]) == install_dir), None)
        return {"installation_id": row["installation_id"] if row else None, "activated": False}

    def _activate(self, op, payload):
        self._tick(op, "validating")
        fresh = probe(payload["executable_path"])
        if payload.get("sha256") and fresh["sha256"] != payload["sha256"]:
            fail("plan_changed", "The validated executable changed")
        with self.manager.lock:
            self._tick(op, "activating")
            config = deepcopy(self.manager.config)
            config["executable_path"] = fresh["executable_path"]
            self.manager.save(config)
            installation_id = payload.get("installation_id")
            if installation_id is None:
                installation_id = str(uuid.uuid4())
                self.data["inventory"].append({k: v for k, v in fresh.items() if k != "capabilities"}
                                              | {"installation_id": installation_id, "tag": None, "variant_id": None})
                self.data["inventory_revision"] += 1
        return {"installation_id": installation_id, "activated": True}

    def _execute(self, op, payload):
        try:
            with self.manager.lock:
                op["state"] = "running"
            result = self._install(op, payload) if op["kind"] == "install" else self._activate(op, payload)
            completion = ("succeeded", result, None)
        except Exception as exc:
            error = exc if isinstance(exc, LocalLlamaError) else LocalLlamaError(
                "installation_failed", "Installation failed; check permissions, disk space and runtime dependencies")
            terminal = "interrupted" if self.manager.closed else "cancelled" if error.reason == "cancelled" else "failed"
            completion = (terminal, {}, {"reason": error.reason, "message": str(error)})
        state, result, error = completion
        result.update(cleanup="not_needed", retained_paths=[])
        with self.manager.lock:
            op.update(state=state, phase="finished", can_cancel=False, finished_at=iso_stamp(None), result=result, error=error)
            self._persist()
            self.active = None
            self.manager.revision += 1
            self.manager._log("setup " + op["kind"] + ": " + state + (" (" + error["reason"] + ")" if error else ""))

    def close(self):
        self.cancel_event.set()
        if self.worker:
            self.worker.join(timeout=40)
