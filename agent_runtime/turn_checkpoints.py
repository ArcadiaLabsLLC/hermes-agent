"""Durable operator-turn provenance for native workspace checkpoints.

The native manager invokes the recorder while holding its store lock. This
index owns attribution only: snapshots, write safety and restoration remain
in CheckpointManager. Tree identities survive native retention's commit rewrite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from utils import atomic_json_write
from tools.checkpoint_manager import CheckpointManager, checkpoint_metadata_directory

__layer__ = "stores"


def _record_path(session_id: str, turn_id: str) -> Path:
    key = hashlib.sha256(json.dumps([session_id, turn_id]).encode()).hexdigest()
    return checkpoint_metadata_directory("operator_turns") / f"{key}.json"


def read_turn_checkpoint(session_id: str, turn_id: str) -> dict | None:
    path = _record_path(session_id, turn_id)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("session_id") != session_id or record.get("turn_id") != turn_id:
        raise ValueError("checkpoint attribution mismatch")
    return record


class TurnCheckpointRecorder:
    def __init__(self, session_id: str, turn_id: str, checkpoints: CheckpointManager):
        self.session_id, self.turn_id = session_id, turn_id
        self.checkpoints = checkpoints

    def _save(self, record: dict) -> None:
        atomic_json_write(_record_path(self.session_id, self.turn_id), record)

    def checkpoint(self, workdir: str, commit: str) -> None:
        tree = self.checkpoints.checkpoint_tree(workdir, commit)
        if tree is None:
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
        diff = self.checkpoints.recorded_file_diff(workdir, workspace["before_tree"], path, evidence)
        if diff is None:
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
        candidate = manager.checkpoint_tree(workdir, checkpoint["hash"])
        if candidate == tree:
            return checkpoint["hash"]
    return None
