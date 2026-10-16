"""Reviewed restore over the native checkpoint store (fork-owned).

Moved out of ``tools/checkpoint_manager.py`` (footprint lane C, plan
``docs/agent-runtime-harness/planned/footprint-audit-2026-10-15.md`` section 2):
strict operator preview, reviewed apply with durable receipts, resumable
recovery, retention pins, and the observer reads (tree, proven file diff,
metadata namespace). ``CheckpointManager`` inherits ``ReviewedRestoreMixin``;
the native store, lock and writer stay upstream.

Upstream module-private names are read through ``_cm`` at CALL time, so a
patch of ``tools.checkpoint_manager.<name>`` reaches these bodies exactly as
it reached them in place. Each is a named exception in
``tests/fixtures/import_layers_grandfathered.json`` (ledger: "Stock files a
fork module reads by private name").
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

__layer__ = "stores"


def _history_safe_path(workdir, rel):
    path = Path(workdir) / rel
    return not _cm._validate_file_path(rel, workdir) and not any(
        item.is_symlink() or getattr(item, "is_junction", lambda: False)()
        for item in (path, *path.parents) if item != Path(workdir))


def _history_current_blob(workdir, rel):
    if not (Path(workdir) / rel).exists():
        return None
    ok, blob, _ = _cm._run_git(["hash-object", "--", rel], _cm._store_path(), workdir)
    return blob.strip() if ok else "unreadable"


def _agent_write_evidence(previous: dict, *, sha256: str | None, deleted: bool) -> dict:
    """Keep prior authorship when a successful write removes a file."""
    return {"sha256": previous.get("sha256") if deleted else sha256,
            "deleted": deleted, "ts": time.time()}


def restore_revision(result: dict) -> str:
    # Transport-only replay flags do not change the durable recovery decision.
    evidence = {key: value for key, value in result.items()
                if key not in {"replayed", "recovery_revision"}}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def pin_restore_checkpoints(workdir: str, operation_id: str, target: str, backup: str) -> bool:
    # Called inside the native store lock, before the command's first file write.
    for name, commit in (("target", target), ("backup", backup)):
        ok, _, _ = _cm._run_git(["update-ref", f"refs/operator-restore/{operation_id}/{name}", commit], _cm._store_path(), workdir)
        if not ok:
            _release_restore_checkpoints_locked(operation_id)
            return False
    return True


def release_restore_checkpoints(operation_id: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", operation_id or "") is None:
        raise ValueError("invalid restore operation")
    from tools.checkpoint_pruning import store_lock
    with store_lock(_cm._resolve_checkpoint_base()):
        _release_restore_checkpoints_locked(operation_id)


def _release_restore_checkpoints_locked(operation_id: str, base: Path | None = None) -> None:
    base = base or _cm._resolve_checkpoint_base()
    if not _cm._store_path(base).exists():
        return
    for name in ("target", "backup"):
        ok, _, _ = _cm._run_git(["update-ref", "-d", f"refs/operator-restore/{operation_id}/{name}"],
                           _cm._store_path(base), str(base))
        if not ok:
            raise OSError("checkpoint recovery reference could not be released")


def checkpoint_metadata_directory(namespace: str) -> Path:
    """Namespaced observer metadata beside the native snapshot store."""
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", namespace) is None:
        raise ValueError("invalid checkpoint metadata namespace")
    return _cm._resolve_checkpoint_base() / namespace


def release_expired_restore_checkpoints(base: Path) -> None:
    """Expire completed restore leases under the caller's native store lock.

    Unfinished recoveries have no expiry. Receipts remain as replay evidence.
    """
    for path in (base / "restore_receipts").glob("*.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            expires = (receipt.get("request") or {}).get("retain_until")
            if type(expires) in (int, float) and math.isfinite(expires) and expires <= time.time():
                _release_restore_checkpoints_locked(path.stem, base)
        except (OSError, ValueError, AttributeError, TypeError):
            _cm.logger.warning("Checkpoint retention receipt unreadable: %s", path.name)


class ReviewedRestoreMixin:
    """Reviewed-restore methods for ``tools.checkpoint_manager.CheckpointManager``."""

    def checkpoint_tree(self, working_dir: str, commit: str) -> Optional[str]:
        """Stable tree identity for an already admitted checkpoint observer."""
        ok, tree, _ = _cm._run_git(["rev-parse", f"{commit}^{{tree}}"], _cm._store_path(), working_dir)
        return tree.strip() if ok else None

    def recorded_file_diff(self, working_dir: str, before_tree: str, path: Path, evidence: dict) -> Optional[str]:
        """Diff one proven write without changing the snapshot owner's index.

        Called by the observer inside the native store lock. None means unsafe
        or unreadable; an empty diff means the file returned to its baseline.
        """
        if not path.is_relative_to(Path(working_dir)):
            return None
        rel = path.relative_to(working_dir).as_posix()
        if not _history_safe_path(working_dir, rel) or self._exceeds_size_cap(path):
            return None
        if _cm._hash_file(path) != evidence.get("sha256") or path.exists() == bool(evidence.get("deleted")):
            return None
        with tempfile.TemporaryDirectory(prefix="observed-diff-", dir=_cm._resolve_checkpoint_base()) as temporary:
            index = Path(temporary) / "index"
            for args in (["read-tree", before_tree], ["--literal-pathspecs", "add", "-A", "--", rel]):
                ok, _, _ = _cm._run_git(args, _cm._store_path(), working_dir, index_file=index)
                if not ok:
                    return None
            ok, diff, _ = _cm._run_git(["--literal-pathspecs", "diff", "--cached", "--no-ext-diff", "--no-textconv",
                                   "--no-renames", before_tree, "--", rel], _cm._store_path(), working_dir, index_file=index)
            if not ok or _cm._hash_file(path) != evidence.get("sha256"):
                return None
        return diff

    def preview_restore(self, working_dir: str, commit_hash: str) -> dict:
        """Strict operator preview: project membership, content pins and conflicts.

        Unlike the legacy safe flag, absent write evidence never permits a
        restore. This preview describes the workspace, not a particular chat.
        """
        from tools.checkpoint_pruning import store_lock
        with store_lock(_cm._resolve_checkpoint_base()):
            return self._restore_preview_locked(str(_cm._normalize_path(working_dir)), commit_hash)

    def _restore_preview_locked(self, working_dir: str, commit_hash: str, *, recovery_operation_id=None) -> dict:
        if not isinstance(commit_hash, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_hash):
            return {"success": False, "reason": "invalid_checkpoint"}
        reversal = None
        if recovery_operation_id is not None:
            reversal = self._restore_reversal_source(working_dir, recovery_operation_id)
            if not reversal or reversal["result"]["recovery_checkpoint"] != commit_hash:
                return {"success": False, "reason": "redo_unavailable"}
        if reversal is None and not any(row["hash"] == commit_hash for row in self.list_checkpoints(working_dir)):
            return {"success": False, "reason": "checkpoint_unavailable"}
        if _cm._dir_file_count(working_dir) > _cm._MAX_FILES:
            return {"success": False, "reason": "workspace_too_large"}
        store = _cm._store_path()
        index = _cm._index_path(store, _cm._project_hash(working_dir))
        try:
            ok, _, _ = _cm._run_git(["add", "-A"], store, working_dir, index_file=index)
            if not ok:
                return {"success": False, "reason": "checkpoint_read_failed"}
            ok, names, _ = _cm._run_git(["diff", "--name-only", "--no-renames", "-z", commit_hash, "--cached"],
                                    store, working_dir, index_file=index)
            if not ok:
                return {"success": False, "reason": "checkpoint_read_failed"}
            ledger = _cm._load_ledger(store, self._ledger_key(working_dir))
            files = [self._restore_file_preview(working_dir, commit_hash, rel, ledger)
                     for rel in filter(None, names.split("\x00"))]
            if reversal is not None:
                selected = reversal["request"]["plan"]
                files = [row for row in files if row["path"] in selected]
                # Even another agent's authored edit is not the state reversed
                # by this request. Check the exact previous restore targets.
                for rel, original in selected.items():
                    if _history_current_blob(working_dir, rel) != original["target_blob"]:
                        return {"success": False, "reason": "workspace_changed"}
            ok, diff, _ = _cm._run_git(["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames",
                                    "-R", commit_hash], store, working_dir, index_file=index)
            if not ok:
                return {"success": False, "reason": "checkpoint_read_failed"}
            fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            return {"success": True, "checkpoint": commit_hash, "revision": fingerprint,
                    "files": files, "diff": diff[:180000], "diff_truncated": len(diff) > 180000,
                    "scope": "workspace", "max_file_size_mb": self.max_file_size_mb,
                    "ignored_files_included": False}
        finally:
            _cm._run_git(["read-tree", _cm._ref_name(_cm._project_hash(working_dir))], store, working_dir, index_file=index)

    def _restore_file_preview(self, working_dir: str, commit_hash: str, rel: str, ledger: dict) -> dict:
        path = Path(working_dir) / rel
        reason = None
        if _cm._validate_file_path(rel, working_dir) or path.is_symlink() or any(
                parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
                for parent in [path, *path.parents] if parent != Path(working_dir)):
            reason = "unsafe_path"
        elif self._exceeds_size_cap(path):
            reason = "oversize"
        current = _cm._hash_file(path) if reason is None else None
        record = ledger.get(str(path))
        recorded = record.get("sha256") if isinstance(record, dict) else None
        recorded_absence = bool(recorded) and record.get("deleted") is True and not path.exists()
        if reason is None and not recorded_absence and (not recorded or current is None or current != recorded):
            reason = "no_write_evidence" if not recorded else "changed_externally"
        if reason is None and record.get("deleted") and path.exists():
            reason = "changed_externally"
        ok, tree, _ = _cm._run_git(["--literal-pathspecs", "ls-tree", "-z", commit_hash, "--", rel], _cm._store_path(), working_dir)
        if not ok:
            reason = "checkpoint_read_failed"
        # Only ordinary files are eligible. Never install a symlink or gitlink
        # from an old snapshot into a directory another tool may write through.
        target = tree.split("\t", 1)[0].split() if tree else []
        if target and (len(target) != 3 or target[0] not in ("100644", "100755")):
            reason = "unsupported_file_type"
        return {"path": rel, "current_sha256": current, "target_blob": target[2] if len(target) == 3 else None,
                "change": "modify" if target and path.exists() else "restore" if target else "delete",
                "eligible": reason is None, "reason": reason}

    def restore_preview(self, working_dir: str, commit_hash: str, *, revision: str,
                        selected_paths: list[str], operation_id: str, recovery_operation_id=None) -> dict:
        """Apply the exact reviewed subset; durable receipt prevents blind replay.

        A pending receipt means the previous process may have changed files.
        It is returned for inspection, never automatically rerun. Every file is
        pinned again just before its write; partial failures name each path.
        """
        from tools.checkpoint_pruning import store_lock
        if (not re.fullmatch(r"[0-9a-f]{64}", operation_id or "") or not selected_paths
                or len(selected_paths) != len(set(selected_paths))):
            return {"success": False, "reason": "invalid_restore_request"}
        working_dir = str(_cm._normalize_path(working_dir))
        evidence = [working_dir, commit_hash, revision, sorted(selected_paths)]
        if recovery_operation_id is not None:
            evidence.append(recovery_operation_id)
        digest = hashlib.sha256(json.dumps(evidence).encode()).hexdigest()
        with store_lock(_cm._resolve_checkpoint_base()):
            receipt_path = _cm._resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt["request_digest"] != digest:
                    return {"success": False, "reason": "operation_payload_changed"}
                return {**self._settled_restore_receipt(receipt["result"]), "replayed": True}
            plan = self._restore_preview_locked(working_dir, commit_hash, recovery_operation_id=recovery_operation_id)
            if not plan.get("success"):
                return plan
            if plan["revision"] != revision:
                return {"success": False, "reason": "workspace_changed"}
            by_path = {row["path"]: row for row in plan["files"]}
            if any(path not in by_path or not by_path[path]["eligible"] for path in selected_paths):
                return {"success": False, "reason": "restore_conflict"}
            self._take(working_dir, f"before reviewed restore {operation_id[:12]}", prune=False)
            backup = self.list_checkpoints(working_dir)
            if not backup or not self._restore_backup_matches(working_dir, backup[0]["hash"], selected_paths):
                return {"success": False, "reason": "recovery_checkpoint_failed"}
            # Independent refs keep both trees alive if normal retention rewrites
            # the workspace snapshot chain while this command needs recovery.
            if not pin_restore_checkpoints(working_dir, operation_id, commit_hash, backup[0]["hash"]):
                return {"success": False, "reason": "recovery_checkpoint_failed"}
            result = {"success": False, "reason": "restore_outcome_unknown", "restored_files": [],
                      "failed_files": [], "review_paths": selected_paths,
                      "recovery_checkpoint": backup[0]["hash"], "replayed": False}
            try:
                self._write_restore_receipt(receipt_path, digest, result, request={
                    "working_dir": working_dir, "checkpoint": commit_hash, "revision": revision,
                    "selected_paths": selected_paths, "plan": {rel: by_path[rel] for rel in selected_paths}})
            except OSError:
                _release_restore_checkpoints_locked(operation_id)
                raise
            for rel in selected_paths:
                row = by_path[rel]
                checked = self._restore_file_preview(working_dir, commit_hash, rel,
                    _cm._load_ledger(_cm._store_path(), self._ledger_key(working_dir)))
                if not checked["eligible"] or checked["current_sha256"] != row["current_sha256"]:
                    result["failed_files"].append({"path": rel, "reason": "workspace_changed"})
                    self._write_restore_receipt(receipt_path, digest, result)
                    continue
                try:
                    self._write_reviewed_restore_file(working_dir, commit_hash, rel, row["target_blob"])
                    result["restored_files"].append(rel)
                except OSError:
                    result["failed_files"].append({"path": rel, "reason": "file_write_failed"})
                self._write_restore_receipt(receipt_path, digest, result)
            result.update(success=not result["failed_files"],
                          reason="restored" if not result["failed_files"] else "restore_partial")
            self._write_restore_receipt(receipt_path, digest, result)
            return result

    def _restore_backup_matches(self, working_dir: str, commit_hash: str, selected_paths: list[str]) -> bool:
        store = _cm._store_path()
        for rel in selected_paths:
            if not (Path(working_dir) / rel).exists():
                found, _, _ = _cm._run_git(["cat-file", "-e", f"{commit_hash}:{rel}"], store, working_dir,
                                       allowed_returncodes={1, 128})
                if found:
                    return False
                continue
            ok, current, _ = _cm._run_git(["hash-object", "--", rel], store, working_dir)
            found, saved, _ = _cm._run_git(["rev-parse", f"{commit_hash}:{rel}"], store, working_dir)
            if not ok or not found or current != saved:
                return False
        return True

    @staticmethod
    def _write_restore_receipt(path: Path, digest: str, result: dict, *, request=None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if request is None and path.exists():
            request = json.loads(path.read_text(encoding="utf-8")).get("request")
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"request_digest": digest, "request": request, "result": result}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def resume_restore(self, operation_id: str, *, revision: str, rollback: bool = False) -> dict:
        from tools.checkpoint_pruning import store_lock
        if re.fullmatch(r"[0-9a-f]{64}", operation_id or "") is None:
            raise ValueError("invalid restore operation")
        with store_lock(_cm._resolve_checkpoint_base()):
            path = _cm._resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
            if not path.exists():
                return {"success": False, "reason": "restore_receipt_unavailable"}
            receipt = json.loads(path.read_text(encoding="utf-8"))
            request, result = receipt.get("request"), receipt["result"]
            if revision != restore_revision(self._settled_restore_receipt(result)):
                return {**self._settled_restore_receipt(result), "recovery_stale": True}
            if request is None:
                return {**result, "success": False, "reason": "restore_review_required"}
            if result.get("success") and (result["reason"] == "rolled_back" or not rollback):
                return result
            direction = "rollback" if rollback else "finish"
            result.update(success=False, reason="restore_outcome_unknown", recovery_direction=direction,
                          failed_files=[], restored_files=[])
            workdir = request["working_dir"]
            commit = result["recovery_checkpoint"] if rollback else request["checkpoint"]
            self._write_restore_receipt(path, receipt["request_digest"], result)
            done = []
            for rel in request["selected_paths"]:
                row = request["plan"][rel]
                file = Path(workdir) / rel
                if not _history_safe_path(workdir, rel) or self._exceeds_size_cap(file):
                    result["failed_files"].append({"path": rel, "reason": "unsafe_path"})
                    continue
                current_sha = _cm._hash_file(file)
                current_blob = _history_current_blob(workdir, rel)
                matches_before = current_sha == row["current_sha256"] and (current_sha is not None or not file.exists())
                if not matches_before and current_blob != row["target_blob"]:
                    result["failed_files"].append({"path": rel, "reason": "changed_externally"})
                    continue
                ok, tree, _ = _cm._run_git(["--literal-pathspecs", "ls-tree", "-z", commit, "--", rel], _cm._store_path(), workdir)
                entry = tree.split("\t", 1)[0].split() if tree else []
                if not ok or (entry and (len(entry) != 3 or entry[0] not in ("100644", "100755"))):
                    result["failed_files"].append({"path": rel, "reason": "checkpoint_read_failed"})
                    continue
                target_blob = entry[2] if entry else None
                try:
                    self._write_reviewed_restore_file(workdir, commit, rel, target_blob)
                    done.append(rel)
                except OSError:
                    result["failed_files"].append({"path": rel, "reason": "file_write_failed"})
                result["restored_files"] = list(done)
                self._write_restore_receipt(path, receipt["request_digest"], result)
            result.update(restored_files=done, success=not result["failed_files"],
                          reason=("rolled_back" if rollback else "restored") if not result["failed_files"] else "restore_partial")
            self._write_restore_receipt(path, receipt["request_digest"], result)
            return result

    def _write_reviewed_restore_file(self, workdir: str, commit: str, rel: str,
                                    target_blob: str | None) -> None:
        """Use the native writer, verify its result, then update authorship."""
        if _history_current_blob(workdir, rel) != target_blob:
            if target_blob is None:
                self._delete_restore_file(workdir, rel)
            else:
                ok, _, _ = self._checkout_restore_paths(workdir, commit, [rel], literal=True)
                if not ok:
                    raise OSError("checkpoint checkout failed")
        if _history_current_blob(workdir, rel) != target_blob:
            raise OSError("restored content changed")
        path = Path(workdir) / rel
        ledger_key = self._ledger_key(workdir)
        ledger = _cm._load_ledger(_cm._store_path(), ledger_key)
        ledger[str(path)] = _agent_write_evidence(ledger.get(str(path), {}),
            sha256=_cm._hash_file(path), deleted=target_blob is None)
        _cm._save_ledger(_cm._store_path(), ledger_key, ledger)

    def release_restore_checkpoints(self, operation_id: str) -> None:
        release_restore_checkpoints(operation_id)

    def retain_restore_checkpoints(self, operation_id: str, *, until: float) -> None:
        """Lease an existing successful restore's recovery refs; never recreate them."""
        from tools.checkpoint_pruning import store_lock
        if not re.fullmatch(r"[0-9a-f]{64}", operation_id or "") or not math.isfinite(until):
            raise ValueError("invalid restore retention")
        with store_lock(_cm._resolve_checkpoint_base()):
            path = _cm._resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if not receipt["result"].get("success"):
                raise ValueError("unfinished restore cannot expire")
            receipt["request"]["retain_until"] = until
            self._write_restore_receipt(path, receipt["request_digest"], receipt["result"], request=receipt["request"])

    def _restore_reversal_source(self, working_dir: str, operation_id: str):
        if not re.fullmatch(r"[0-9a-f]{64}", operation_id or ""):
            return None
        path = _cm._resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
        if not path.is_file():
            return None
        receipt = json.loads(path.read_text(encoding="utf-8"))
        request, result = receipt.get("request") or {}, receipt["result"]
        if (request.get("working_dir") != working_dir or not result.get("success")
                or result.get("reason") != "restored" or request.get("retain_until", 0) <= time.time()):
            return None
        ok, saved, _ = _cm._run_git(["rev-parse", f"refs/operator-restore/{operation_id}/backup"],
                                _cm._store_path(), working_dir, allowed_returncodes={128})
        return receipt if ok and saved.strip() == result["recovery_checkpoint"] else None

    def preview_restore_reversal(self, working_dir: str, operation_id: str) -> dict:
        """Review a completed restore's inverse through the same file plan/writer."""
        from tools.checkpoint_pruning import store_lock
        working_dir = str(_cm._normalize_path(working_dir))
        with store_lock(_cm._resolve_checkpoint_base()):
            source = self._restore_reversal_source(working_dir, operation_id)
            if source is None:
                return {"success": False, "reason": "redo_unavailable"}
            return self._restore_preview_locked(working_dir, source["result"]["recovery_checkpoint"],
                                                recovery_operation_id=operation_id)

    def restore_receipt(self, operation_id: str) -> Optional[dict]:
        """Read an immutable apply receipt; this never retries filesystem work."""
        from tools.checkpoint_pruning import store_lock
        if not re.fullmatch(r"[0-9a-f]{64}", operation_id or ""):
            raise ValueError("invalid restore operation")
        with store_lock(_cm._resolve_checkpoint_base()):
            path = _cm._resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
            if not path.exists():
                # The receipt precedes every write. A crash before it was saved
                # can leave refs, but cannot leave applied workspace changes.
                _release_restore_checkpoints_locked(operation_id)
                return None
            return self._settled_restore_receipt(json.loads(path.read_text(encoding="utf-8"))["result"])

    @staticmethod
    def _settled_restore_receipt(result: dict) -> dict:
        # Called ONLY while holding the same store lock as restore_preview:
        # an in-progress writer cannot still own a pending receipt at this point.
        # A crash left unknown individual writes; report review-required paths
        # and expose its verified backup, never retry those writes automatically.
        if result["reason"] != "restore_outcome_unknown":
            return result
        known = set(result.get("restored_files", [])) | {row["path"] for row in result.get("failed_files", [])}
        return {**result, "reason": "restore_interrupted", "failed_files": [
            *result.get("failed_files", []),
            *({"path": path, "reason": "review_required"} for path in result.get("review_paths", []) if path not in known)]}

    def _checkout_restore_paths(self, working_dir: str, commit_hash: str,
                                paths: list[str], *, literal: bool = False):
        """Checkout one validated selection while the caller holds the store lock.

        Native pathspec callers retain Git's matching rules. Literal selections
        use a NUL file to preserve filenames and keep batches off the argv limit.
        Snapshot, selection and user-edit policy stay with the restore caller.
        """
        if not paths:
            return True, "", ""
        store = _cm._store_path()
        index = _cm._index_path(store, _cm._project_hash(working_dir))
        if literal:
            with tempfile.TemporaryDirectory(prefix="restore-select-", dir=store) as scratch:
                spec_file = Path(scratch) / "pathspec"
                spec_file.write_bytes(b"".join(os.fsencode(p) + b"\0" for p in paths))
                return _cm._run_git(
                    ["checkout", commit_hash, f"--pathspec-from-file={spec_file}", "--pathspec-file-nul"],
                    store, working_dir, timeout=_cm._GIT_TIMEOUT * 2, index_file=index,
                    extra_env={"GIT_LITERAL_PATHSPECS": "1"},
                )
        return _cm._run_git(["checkout", commit_hash, "--", *paths], store, working_dir,
                        timeout=_cm._GIT_TIMEOUT * 2, index_file=index)

    @staticmethod
    def _delete_restore_file(working_dir: str, rel: str) -> None:
        """Remove a selected file; confinement/ownership were checked by caller."""
        target = Path(working_dir) / rel
        if target.is_file() or target.is_symlink():
            target.unlink()


# Bottom import: ``tools.checkpoint_manager`` imports this module for the mixin
# base, so the reverse binding is made once both names can exist.
import tools.checkpoint_manager as _cm
