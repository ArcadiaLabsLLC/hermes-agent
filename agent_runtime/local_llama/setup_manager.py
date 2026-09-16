"""Root-bound installation inventory and durable, cancellable setup operations.

The existing LocalLlamaManager owns the lock, reservation and all inference.
This component never adopts or starts upstream's independent runtime supervisor.
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
import threading
import time
import uuid

from agent_runtime.store_file_io import read_json_object, iso_stamp
from utils import atomic_json_write
from .config import LocalLlamaError, identifier
from .setup_io import host_path, digest, probe, official_get, extract_zip, MAX_EXPANDED, fail
from .setup_releases import ReleaseCatalog

SCHEMA = "hermes.local_llama.setup/v1"
ACTIVE = ("queued", "running", "cancelling")


class SetupManager:
    def __init__(self, manager):
        self.manager = manager
        self.directory = manager.directory / "setup"
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / "state.json"
        self.data = read_json_object(self.path) or {"inventory": [], "receipts": {}, "inventory_revision": 0}
        self.data.setdefault("cancellations", {})
        self.catalog = ReleaseCatalog()
        self.plans = {}
        self.validations = {}
        self.cancel_event = threading.Event()
        self.worker = None
        self.active = None
        for receipt in self.data["receipts"].values():
            op = receipt["operation"]
            if op["state"] in ACTIVE:
                # Published installs are recovered only from our persisted manifest identity.
                publication = receipt.get("publication")
                if publication and Path(publication["directory"]).is_dir():
                    self._recover_publication(publication)
                op.update(state="interrupted", phase="finished", can_cancel=False,
                          finished_at=iso_stamp(None), error={"reason": "interrupted", "message": "Hermes restarted; review the recorded installation before retrying."})
                op["result"] = {"cleanup": "pending" if receipt.get("staging") else "not_needed",
                                "retained_paths": [receipt["staging"]] if receipt.get("staging") else []}
        self._persist()

    def envelope(self, **fields):
        return {"schema": SCHEMA, "install_id": self.manager.install_id,
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

    def capabilities(self):
        automatic = platform.system() == "Windows" and platform.machine().lower() in ("amd64", "x86_64")
        return self.envelope(features={"detect": True, "path_validate": True, "hardware": True,
            "releases": automatic, "install": automatic, "cancel": automatic, "activate": True,
            "offline_import": False, "host_browser": False}, automatic_platforms=["win-x64"],
            unsupported_reason=None if automatic else "Automatic installation supports Windows x64; use an existing executable.")

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
            path = self.manager.config.get("executable_path")
            selected = next((r["installation_id"] for r in self.data["inventory"] if r["executable_path"] == path), None)
            return self.envelope(inventory=[{k: v for k, v in r.items() if k != "files"} for r in self.data["inventory"]], inventory_revision=self.data["inventory_revision"],
                active_installation_id=selected, active_operation=self.active,
                requested_operation=requested, lookup_state=("found" if requested else "not_found") if request_id or operation_id else "not_requested")

    def detect(self):
        with self.manager.lock:
            candidates = [r["executable_path"] for r in self.data["inventory"]]
            configured = self.manager.config.get("executable_path")
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
        from hermes_cli.local_runtime.hardware import _ram_bytes
        total, available = _ram_bytes()
        return self.envelope(os=platform.system(), architecture=platform.machine(),
                             ram_bytes=total or None, available_ram_bytes=available or None,
                             gpu_compatibility="unknown", recommended_backend="cpu",
                             recommendation="CPU needs no GPU driver. Choose CUDA only with a compatible NVIDIA driver.")

    def paths(self, path, purpose):
        if purpose not in ("installation_parent", "model_root"):
            fail("invalid_parameter", "Unsupported path purpose")
        target = host_path(path, directory=True)
        return self.envelope(normalized_path=str(target), exists=True,
                             writable=os.access(target, os.W_OK), free_bytes=shutil.disk_usage(target).free)

    def releases(self):
        rows = deepcopy(self.catalog.list())
        for row in rows:
            for variant in row["variants"]:
                for artifact in variant["artifacts"]:
                    artifact.pop("url", None)
        return self.envelope(releases=rows)

    def plan(self, params):
        if not self.capabilities()["features"]["install"]:
            fail("unsupported_platform", "Use an existing executable on this host")
        parent = host_path(params.get("destination_parent"), directory=True)
        tag, release_id, variant_id = (params.get(k) for k in ("tag", "release_id", "variant_id"))
        variant = self.catalog.pinned(tag, release_id, variant_id)
        if variant is None:
            fail("release_unavailable", "This release has no verified asset bundle for that variant")
        required = variant["download_bytes"] + MAX_EXPANDED + 512 * 1024**2
        free = shutil.disk_usage(parent).free
        if free < required:
            fail("disk_full", "Choose a folder with enough space for download and safe extraction")
        with self.manager.lock:
            self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.time()}
            if len(self.plans) >= 100:
                fail("operation_busy", "Too many pending installation plans")
            plan_id = str(uuid.uuid4())
            plan = {"plan_id": plan_id, "plan_revision": 1, "expires": time.time() + 900,
                    "release_id": release_id, "tag": tag, "variant_id": variant_id,
                    "destination_parent": str(parent), "parent_identity": [parent.stat().st_dev, parent.stat().st_ino],
                    "directory": str(parent / ("llama-" + tag + "-" + variant["backend"] + "-" + plan_id[:8])),
                    "variant": variant, "required_free_bytes": required, "free_bytes": free,
                    "config_revision": self.manager.config_revision,
                    "inventory_revision": self.data["inventory_revision"],
                    "warning_ids": ["cuda_driver"] if variant["backend"] == "cuda" else []}
            self.plans[plan_id] = plan
        public = deepcopy(plan)
        for artifact in public["variant"]["artifacts"]:
            artifact.pop("url", None)
        return self.envelope(plan=public)

    def submit(self, kind, params):
        m = self.manager
        request_id = identifier(params.get("request_id"), "request_id")
        fingerprint = hashlib.sha256(json.dumps({"kind": kind, "params": params}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with m.lock:
            previous = self.data["receipts"].get(request_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    fail("idempotency_conflict", "Request ID belongs to a different operation")
                return self.envelope(operation=previous["operation"])
            if m.closed:
                fail("manager_unavailable", "Hermes is stopping")
            if m.setup_busy() or (m.operation and m.operation["state"] in ("queued", "running")):
                fail("operation_busy", "Another local llama operation is active")
            if m.leases:
                fail("active_turns", "Wait for the active local model response")
            if m.server != "off":
                fail("server_must_be_off", "Turn off llama before installing or changing its version")
            for key, expected in (("expect_epoch", m.epoch), ("expect_revision", m.revision), ("expect_config_revision", m.config_revision)):
                if params.get(key) != expected or isinstance(params.get(key), bool):
                    fail("stale_revision", "Refresh local llama state before continuing")
            if kind == "install":
                plan = self.plans.get(params.get("plan_id"))
                if plan is None or plan["expires"] <= time.time():
                    fail("plan_expired", "Review the installation again")
                if type(params.get("plan_revision")) is not int or params.get("plan_revision") != 1 or plan["config_revision"] != m.config_revision or plan["inventory_revision"] != self.data["inventory_revision"]:
                    fail("plan_changed", "Installation facts changed; review again")
                warnings = params.get("acknowledged_warning_ids")
                if not isinstance(warnings, list) or len(warnings) > 16 or not all(isinstance(w, str) for w in warnings):
                    fail("invalid_parameter", "Warning acknowledgements must be a list")
                if set(params.get("acknowledged_warning_ids", [])) != set(plan["warning_ids"]):
                    fail("approval_required", "Review the selected GPU runtime dependency")
                payload = deepcopy(plan)
            elif kind == "activate":
                token, installation_id = params.get("validation_token"), params.get("installation_id")
                if bool(token) == bool(installation_id):
                    fail("invalid_parameter", "Choose one validated installation")
                if params.get("expect_inventory_revision") != self.data["inventory_revision"]:
                    fail("stale_revision", "Installation inventory changed")
                payload = deepcopy(self.validations.get(token) if token else next((r for r in self.data["inventory"] if r["installation_id"] == installation_id), None))
                if payload is None or payload.get("expires", float("inf")) < time.time():
                    fail("plan_expired", "Validate this installation again")
            else:
                fail("invalid_parameter", "Unsupported setup operation")
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
            op.update(phase=phase, bytes_done=done, bytes_total=total, sequence=op["sequence"] + 1)
            self.manager.revision += 1

    def _recover_publication(self, row):
        path = host_path(row["directory"], directory=True)
        manifest = read_json_object(path / ".hermes-installation.json")
        if manifest != row or any(digest(host_path(str(path / relative))) != checksum for relative, checksum in row["files"].items()):
            fail("recovery_required", "Published installation changed; preserve it for inspection")
        if not any(r["installation_id"] == row["installation_id"] for r in self.data["inventory"]):
            self.data["inventory"].append(row)
            self.data["inventory_revision"] += 1

    def _execute(self, op, payload):
        stage = None
        published = False
        receipt = self.data["receipts"][op["request_id"]]
        stage_identity = None
        completion = None
        try:
            with self.manager.lock:
                op["state"] = "running"
            if op["kind"] == "install":
                parent = host_path(payload["destination_parent"], directory=True)
                if [parent.stat().st_dev, parent.stat().st_ino] != payload["parent_identity"] or shutil.disk_usage(parent).free < payload["required_free_bytes"]:
                    fail("plan_changed", "Installation location or free space changed")
                current = self.catalog.pinned(payload["tag"], payload["release_id"], payload["variant_id"])
                if current != payload["variant"]:
                    fail("plan_changed", "The official release asset changed")
                stage = parent / (".hermes-llama-" + op["operation_id"])
                stage.mkdir()
                stage_identity = (stage.stat().st_dev, stage.stat().st_ino)
                atomic_json_write(stage / ".owner.json", {"operation_id": op["operation_id"]})
                with self.manager.lock:
                    receipt["staging"] = str(stage)
                    self._persist()
                binaries = stage / "runtime"
                binaries.mkdir()
                remaining = MAX_EXPANDED
                for asset in current["artifacts"]:
                    archive = stage / (asset["asset_id"] + ".zip")
                    official_get(asset["url"], destination=archive, max_bytes=asset["size_bytes"], expected_size=asset["size_bytes"],
                                 tick=lambda d, t: self._tick(op, "downloading", d, t), cancelled=self.cancel_event.is_set)
                    self._tick(op, "verifying")
                    if digest(archive) != asset["sha256"]:
                        fail("digest_mismatch", "Downloaded release failed official SHA-256 verification")
                    remaining -= extract_zip(archive, binaries, remaining=remaining,
                                              tick=lambda d, t: self._tick(op, "extracting", d, t), cancelled=self.cancel_event.is_set)
                self._tick(op, "validating")
                from hermes_cli.local_runtime.binaries import server_binary
                executable = server_binary(binaries)
                validation = probe(executable)
                if not re.search(r"\b" + re.escape(payload["tag"][1:]) + r"\b", validation["version"]):
                    fail("unsupported_binary", "Installed binary version does not match the approved release")
                final = Path(payload["directory"])
                files = {str(p.relative_to(binaries)): digest(p) for p in binaries.rglob("*") if p.is_file()}
                row = {**validation, "installation_id": str(uuid.uuid4()), "tag": payload["tag"],
                       "variant_id": payload["variant_id"], "directory": str(final), "files": files,
                       "executable_path": str(final / executable.relative_to(binaries))}
                atomic_json_write(binaries / ".hermes-installation.json", row)
                with self.manager.lock:
                    self._tick(op, "publishing")
                    op["can_cancel"] = False
                    receipt["publication"] = row
                    self._persist()
                    host_path(str(parent), directory=True)
                    if final.exists():
                        fail("path_conflict", "The destination already exists; choose another location")
                    binaries.rename(final)
                    published = True
                    self._recover_publication(row)
                    self._persist()
                result = {"installation_id": row["installation_id"], "activated": False}
            else:
                self._tick(op, "validating")
                if "files" in payload:
                    self._recover_publication(payload)
                fresh = probe(payload["executable_path"])
                if fresh["sha256"] != payload["sha256"]:
                    fail("plan_changed", "The validated executable changed")
                with self.manager.lock:
                    self._tick(op, "activating")
                    config = deepcopy(self.manager.config)
                    config["executable_path"] = fresh["executable_path"]
                    self.manager._save(config)
                result = {"installation_id": payload.get("installation_id"), "activated": True}
            completion = ("succeeded", result, None)
        except Exception as exc:
            error = exc if isinstance(exc, LocalLlamaError) else LocalLlamaError("installation_failed", "Installation failed; check permissions, disk space and runtime dependencies")
            terminal = "interrupted" if self.manager.closed else "cancelled" if error.reason == "cancelled" else "failed"
            completion = (terminal, {"published": published}, {"reason": error.reason, "message": str(error)})
        finally:
            cleanup = "not_needed"
            if stage is not None:
                try:
                    checked = host_path(str(stage), directory=True)
                    if (checked.stat().st_dev, checked.stat().st_ino) != stage_identity or read_json_object(checked / ".owner.json") != {"operation_id": op["operation_id"]}:
                        fail("ownership_unverified", "Staging ownership changed")
                    shutil.rmtree(checked)
                    cleanup = "complete"
                except (OSError, LocalLlamaError):
                    cleanup = "pending"
            if completion is not None:
                terminal, result, error = completion
                result.update(cleanup=cleanup, retained_paths=[str(stage)] if cleanup == "pending" else [])
                try:
                    self._finish(op, terminal, result=result, error=error)
                finally:
                    if self.manager.closed:
                        self.manager.release_ownership()

    def _finish(self, op, state, *, result=None, error=None):
        with self.manager.lock:
            op.update(state=state, phase="finished", can_cancel=False, finished_at=iso_stamp(None), result=result or {}, error=error)
            self._persist()
            self.active = None
            self.manager.revision += 1
            self.manager._log("setup " + op["kind"] + ": " + state + (" (" + error["reason"] + ")" if error else ""))

    def close(self):
        self.cancel_event.set()
        if self.worker:
            self.worker.join(timeout=40)
        return self.worker is None or not self.worker.is_alive()
