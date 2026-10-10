"""Resume the native reviewed restore using its original per-file evidence."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import re
import time

from tools.checkpoint_manager import (
    _resolve_checkpoint_base, _store_path, _run_git, _index_path, _project_hash,
    _hash_file, _load_ledger, _save_ledger, _validate_file_path,
)
from tools.checkpoint_pruning import store_lock


def _safe_path(workdir, rel):
    path = Path(workdir) / rel
    return not _validate_file_path(rel, workdir) and not any(
        item.is_symlink() or getattr(item, "is_junction", lambda: False)()
        for item in (path, *path.parents) if item != Path(workdir))


def _current_blob(workdir, rel):
    if not (Path(workdir) / rel).exists():
        return None
    ok, blob, _ = _run_git(["hash-object", "--", rel], _store_path(), workdir)
    return blob.strip() if ok else "unreadable"


def restore_revision(result: dict) -> str:
    # Transport-only replay flags do not change the durable recovery decision.
    evidence = {key: value for key, value in result.items()
                if key not in {"replayed", "recovery_revision"}}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def resume_restore(manager, operation_id: str, *, revision: str, rollback: bool = False) -> dict:
    if re.fullmatch(r"[0-9a-f]{64}", operation_id or "") is None:
        raise ValueError("invalid restore operation")
    with store_lock(_resolve_checkpoint_base()):
        path = _resolve_checkpoint_base() / "restore_receipts" / f"{operation_id}.json"
        if not path.exists():
            return {"success": False, "reason": "restore_receipt_unavailable"}
        receipt = json.loads(path.read_text(encoding="utf-8"))
        request, result = receipt.get("request"), receipt["result"]
        if revision != restore_revision(manager._settled_restore_receipt(result)):
            return {**manager._settled_restore_receipt(result), "recovery_stale": True}
        if request is None:
            return {**result, "success": False, "reason": "restore_review_required"}
        if result.get("success") and (result["reason"] == "rolled_back" or not rollback):
            return result
        direction = "rollback" if rollback else "finish"
        result.update(success=False, reason="restore_outcome_unknown", recovery_direction=direction,
                      failed_files=[], restored_files=[])
        workdir = request["working_dir"]
        commit = result["recovery_checkpoint"] if rollback else request["checkpoint"]
        manager._write_restore_receipt(path, receipt["request_digest"], result)
        done = []
        for rel in request["selected_paths"]:
            row = request["plan"][rel]
            file = Path(workdir) / rel
            if not _safe_path(workdir, rel) or manager._exceeds_size_cap(file):
                result["failed_files"].append({"path": rel, "reason": "unsafe_path"})
                continue
            current_sha = _hash_file(file)
            current_blob = _current_blob(workdir, rel)
            matches_before = current_sha == row["current_sha256"] and (current_sha is not None or not file.exists())
            if not matches_before and current_blob != row["target_blob"]:
                result["failed_files"].append({"path": rel, "reason": "changed_externally"})
                continue
            ok, tree, _ = _run_git(["--literal-pathspecs", "ls-tree", "-z", commit, "--", rel], _store_path(), workdir)
            entry = tree.split("\t", 1)[0].split() if tree else []
            if not ok or (entry and (len(entry) != 3 or entry[0] not in ("100644", "100755"))):
                result["failed_files"].append({"path": rel, "reason": "checkpoint_read_failed"})
                continue
            target_blob = entry[2] if entry else None
            try:
                if current_blob != target_blob:
                    if target_blob is None:
                        file.unlink(missing_ok=True)
                    else:
                        file.parent.mkdir(parents=True, exist_ok=True)
                        ok, _, _ = _run_git(["--literal-pathspecs", "checkout", commit, "--", rel],
                            _store_path(), workdir, index_file=_index_path(_store_path(), _project_hash(workdir)))
                        if not ok:
                            raise OSError("restore failed")
                if _current_blob(workdir, rel) != target_blob:
                    raise OSError("restored content changed")
                ledger_key = manager._ledger_key(workdir)
                ledger = _load_ledger(_store_path(), ledger_key)
                ledger[str(file)] = {"sha256": _hash_file(file), "deleted": target_blob is None, "ts": time.time()}
                _save_ledger(_store_path(), ledger_key, ledger)
                done.append(rel)
            except OSError:
                result["failed_files"].append({"path": rel, "reason": "file_write_failed"})
            result["restored_files"] = list(done)
            manager._write_restore_receipt(path, receipt["request_digest"], result)
        result.update(restored_files=done, success=not result["failed_files"],
                      reason=("rolled_back" if rollback else "restored") if not result["failed_files"] else "restore_partial")
        manager._write_restore_receipt(path, receipt["request_digest"], result)
        return result
