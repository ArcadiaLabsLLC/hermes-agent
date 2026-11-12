"""Managing a workspace that already exists — ONE implementation per verb, two doors each.

``harness workspace unarchive`` / ``runtime.workspace.unarchive`` (RT-WORKSPACE-UNARCHIVE) call
:func:`unarchive_workspace`. Each function decides, writes through the stores, and RAISES
:class:`WorkspaceManageRefused` with a typed reason for its door to render; a client draws the
refusal, it never pre-judges one.

Pinned by ``tests/agent_runtime/test_workspace_manage.py``.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from .errors import NotFound
from .locks import workspace_realm_assign_lock
from .scope_activation import workspace_row
from .store import RealmStore, WorkspaceStore, lift_deleted_workspace

__layer__ = "lanes"
__all__ = ["WorkspaceManageReason", "WorkspaceManageRefused", "unarchive_workspace"]


class WorkspaceManageReason(StrEnum):
    INVALID = "invalid_request"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    REALM_ARCHIVED = "realm_archived"


class WorkspaceManageRefused(ValueError):
    def __init__(self, reason: WorkspaceManageReason, **details: str):
        self.reason = reason
        self.details = details
        super().__init__(reason.value)


def _clean_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise WorkspaceManageRefused(WorkspaceManageReason.INVALID)
    return value.strip()


def _workspace(workspaces: WorkspaceStore, workspace_id: Any):
    try:
        return workspaces.get(_clean_id(workspace_id))
    except NotFound:
        raise WorkspaceManageRefused(WorkspaceManageReason.WORKSPACE_NOT_FOUND) from None


def unarchive_workspace(workspace_id: Any) -> tuple[dict, bool]:
    """Bring an archived workspace back. Returns ``(workspace_row(full), restored)``; ``restored`` is
    False when it was not archived (nothing written).

    Refused ``realm_archived`` (with ``realm_id``) while the realm that owns it is archived: the
    workspace would come back where no selector lists it. A restore also lifts the workspace off its
    realm's delete ledger (``lift_deleted_workspace``) and heals a missing ``workspace_ids`` entry —
    a copy realm sync archived because another member deleted it (``workspace_tombstone_archived``)
    would otherwise be archived again by the next pull. It moves no active pointer.
    """
    workspaces, realms = WorkspaceStore(), RealmStore()
    with workspace_realm_assign_lock():
        workspace = _workspace(workspaces, workspace_id)
        realm = None
        if workspace.realm_id:
            try:
                realm = realms.get(workspace.realm_id)
            except NotFound:
                realm = None
        if realm is not None and realm.archived and workspace.archived:
            raise WorkspaceManageRefused(WorkspaceManageReason.REALM_ARCHIVED, realm_id=realm.id)
        restored = bool(workspace.archived)
        if restored:
            workspace = workspaces.unarchive(workspace.id)
            if realm is not None:
                realm_changed = lift_deleted_workspace(realm, workspace.id)
                if workspace.id not in realm.workspace_ids:
                    realm.workspace_ids.append(workspace.id)
                    realm_changed = True
                if realm_changed:
                    realms.save(realm)
    return workspace_row(workspace, full=True), restored
