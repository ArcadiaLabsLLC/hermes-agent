"""Durable operator-turn provenance for native workspace checkpoints.

The native manager invokes the recorder while holding its store lock. This
index owns attribution only: snapshots, write safety and restoration remain
in CheckpointManager. Tree identities survive native retention's commit rewrite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import atomic_json_write
from tools.checkpoint_manager import _resolve_checkpoint_base, _run_git, _store_path, _hash_file

__layer__ = "stores"


def _record_path(session_id: str, turn_id: str) -> Path:
    key = hashlib.sha256(json.dumps([session_id, turn_id]).encode()).hexdigest()
    return _resolve_checkpoint_base() / "operator_turns" / f"{key}.json"


def read_turn_checkpoint(session_id: str, turn_id: str) -> dict | None:
    path = _record_path(session_id, turn_id)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("session_id") != session_id or record.get("turn_id") != turn_id:
        raise ValueError("checkpoint attribution mismatch")
    return record


class TurnCheckpointRecorder:
    def __init__(self, session_id: str, turn_id: str, *, max_file_size_mb: int = 10):
        self.session_id, self.turn_id = session_id, turn_id
        self.max_file_size_mb = max_file_size_mb

    def _save(self, record: dict) -> None:
        atomic_json_write(_record_path(self.session_id, self.turn_id), record)

    def checkpoint(self, workdir: str, commit: str) -> None:
        ok, tree, _ = _run_git(["rev-parse", f"{commit}^{{tree}}"], _store_path(), workdir)
        if not ok:
            return
        record = read_turn_checkpoint(self.session_id, self.turn_id) or {
            "session_id": self.session_id, "turn_id": self.turn_id, "workspaces": {}}
        # An agent iteration is not an operator turn. Keep the FIRST baseline
        # across every tool/iteration/reused resident agent of this exact turn.
        record["workspaces"].setdefault(workdir, {"before_tree": tree.strip(), "files": {}})
        self._save(record)

    def write(self, workdir: str, path: Path, evidence: dict) -> None:
        record = read_turn_checkpoint(self.session_id, self.turn_id)
        workspace = (record or {}).get("workspaces", {}).get(workdir)
        if workspace is None or not path.is_relative_to(Path(workdir)):
            return
        rel = path.relative_to(workdir).as_posix()
        if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)()
               for item in (path, *path.parents) if item != Path(workdir)) or (path.exists() and self.max_file_size_mb > 0
                                and path.stat().st_size > self.max_file_size_mb * 1024 * 1024):
            return
        if _hash_file(path) != evidence.get("sha256") or path.exists() == bool(evidence.get("deleted")):
            return
        # A private index includes new/deleted paths without changing the native
        # manager's next snapshot. Only the path whose write was observed enters.
        with TemporaryDirectory(prefix="turn-diff-", dir=_resolve_checkpoint_base()) as temporary:
            index = Path(temporary) / "index"
            for args in (["read-tree", workspace["before_tree"]], ["--literal-pathspecs", "add", "-A", "--", rel]):
                ok, _, _ = _run_git(args, _store_path(), workdir, index_file=index)
                if not ok:
                    return
            ok, diff, _ = _run_git(["--literal-pathspecs", "diff", "--cached", "--no-ext-diff", "--no-textconv",
                                   "--no-renames", workspace["before_tree"], "--", rel], _store_path(), workdir,
                                   index_file=index)
            if not ok or _hash_file(path) != evidence.get("sha256"):
                return
        if not diff.strip():
            workspace["files"].pop(rel, None)
            self._save(record)
            return
        plus = sum(line.startswith("+") and not line.startswith("+++") for line in diff.splitlines())
        minus = sum(line.startswith("-") and not line.startswith("---") for line in diff.splitlines())
        remaining = max(0, 500000 - sum(len(row["diff"]) for name, row in workspace["files"].items() if name != rel))
        limit = min(180000, remaining)
        workspace["files"][rel] = {
            "path": rel, "sha256": evidence.get("sha256"), "deleted": evidence.get("deleted", False),
            "diff": diff[:limit], "diff_truncated": len(diff) > limit,
            "insertions": plus, "deletions": minus,
        }
        self._save(record)


def checkpoint_for_tree(manager, workdir: str, tree: str) -> str | None:
    for checkpoint in manager.list_checkpoints(workdir):
        ok, candidate, _ = _run_git(["rev-parse", f"{checkpoint['hash']}^{{tree}}"], _store_path(), workdir)
        if ok and candidate.strip() == tree:
            return checkpoint["hash"]
    return None
