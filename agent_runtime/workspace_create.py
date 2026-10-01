"""Create through WorkspaceStore without changing the operator's selection."""
from __future__ import annotations

import hashlib
from enum import StrEnum

from . import paths
from .errors import NotFound
from .locks import workspace_create_lock
from .office_store import OfficeStore
from .serde import read_json, write_json_atomic
from .store import WorkspaceStore

__layer__ = "stores"


class WorkspaceCreationReason(StrEnum):
    INVALID = "invalid_workspace_creation"
    CONFLICT = "idempotency_conflict"
    UNRESOLVED = "workspace_creation_unresolved"
    ARCHIVED = "workspace_archived"


class WorkspaceCreationRefused(ValueError):
    def __init__(self, reason: WorkspaceCreationReason):
        self.reason = reason
        super().__init__(reason.value)


def conversations_workspace():
    """One native home for non-spatial conversations; never moves an agent."""
    return create_workspace("Conversations", "harness:conversations-workspace:v1")


def create_workspace(name: str, key: str):
    """A receipt fences replay; the workspace record remains the sole authority."""
    if (not isinstance(name, str) or not name.strip() or len(name) > 120 or
            any(ord(c) < 32 for c in name) or not isinstance(key, str) or not 1 <= len(key) <= 128):
        raise WorkspaceCreationRefused(WorkspaceCreationReason.INVALID)
    name = name.strip()
    digest = hashlib.sha256(key.encode()).hexdigest()
    fingerprint = hashlib.sha256(name.encode()).hexdigest()
    identity = "ws_" + digest[:32]
    receipt_path = paths.store_root() / "workspace_creates" / f"{digest}.json"
    store = WorkspaceStore()
    with workspace_create_lock(digest):
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if receipt != {"workspace_id": identity, "fingerprint": fingerprint}:
                raise WorkspaceCreationRefused(WorkspaceCreationReason.CONFLICT)
            try:
                existing = store.get(identity)
            except NotFound:
                # A crash before create or a later deletion is not permission to recreate.
                raise WorkspaceCreationRefused(WorkspaceCreationReason.UNRESOLVED) from None
            if existing.archived:
                raise WorkspaceCreationRefused(WorkspaceCreationReason.ARCHIVED)
            OfficeStore().ensure_surface(identity)
            return existing
        write_json_atomic(receipt_path, {"workspace_id": identity, "fingerprint": fingerprint})
        created = store.create(name=name, workspace_id=identity)
        OfficeStore().ensure_surface(identity)
        return created
