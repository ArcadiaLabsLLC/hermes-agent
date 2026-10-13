"""Admission fence for a recoverable history operation, not its outcome store."""
from __future__ import annotations
import hashlib
import json
from . import paths
from utils import atomic_json_write

__layer__ = "stores"


def _path(session: str):
    return paths.store_root() / "history_recovery" / (hashlib.sha256(session.encode()).hexdigest() + ".json")


def pending_history_operation(session: str) -> str | None:
    record = pending_history_record(session)
    return record["operation_id"] if record else None


def pending_history_record(session: str) -> dict | None:
    path = _path(session)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def fence_history_operation(session: str, operation: str, *, action: str, workspace: str | None = None) -> None:
    existing = pending_history_operation(session)
    if existing is not None and existing != operation:
        raise ValueError("history recovery already pending")
    atomic_json_write(_path(session), {"operation_id": operation, "action": action, "workspace_path": workspace})


def clear_history_operation(session: str, operation: str) -> None:
    if pending_history_operation(session) == operation:
        _path(session).unlink()
