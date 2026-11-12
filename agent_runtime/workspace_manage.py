"""Managing a workspace that already exists — ONE implementation per verb, two doors each.

``harness workspace unarchive`` / ``runtime.workspace.unarchive`` (RT-WORKSPACE-UNARCHIVE) call
:func:`unarchive_workspace`; ``harness workspace move-realm`` / ``runtime.workspace.move_realm``
(RT-WORKSPACE-MOVE-REALM) call :func:`move_workspace_realm`. Each function decides, writes through the stores, and RAISES
:class:`WorkspaceManageRefused` with a typed reason for its door to render; a client draws the
refusal, it never pre-judges one.

Pinned by ``tests/agent_runtime/test_workspace_manage.py``.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from .default_scope import DEFAULT_REALM_ID, DEFAULT_WORKSPACE_ID
from .errors import NotFound
from .locks import workspace_realm_assign_lock
from .scope_activation import reconcile_active_workspace_to_realm, workspace_row
from .store import RealmStore, WorkspaceStore, lift_deleted_workspace

__layer__ = "lanes"
__all__ = ["WorkspaceManageReason", "WorkspaceManageRefused", "move_workspace_realm", "unarchive_workspace"]


class WorkspaceManageReason(StrEnum):
    INVALID = "invalid_request"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    REALM_ARCHIVED = "realm_archived"
    REALM_NOT_FOUND = "realm_not_found"
    WORKSPACE_ARCHIVED = "workspace_archived"
    #: The workspace is its realm's default (or the reserved ``ws_default``): it stays — the word
    #: ``WorkspaceStore.delete`` refuses with.
    REALM_DEFAULT = "realm_default_workspace"
    #: The realm that owns it is server-bound: its workspaces are shared through realm sync, and a
    #: move out is a delete every member must receive (RT-WORKSPACE-MOVE-OUT-OF-SERVER-REALM).
    SERVER_BOUND = "workspace_realm_server_bound"


class WorkspaceManageRefused(ValueError):
    def __init__(self, reason: WorkspaceManageReason, **details: str):
        self.reason = reason
        self.details = details
        super().__init__(reason.value)


def _clean_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise WorkspaceManageRefused(WorkspaceManageReason.INVALID)
    return value.strip()


def _managed_workspace(workspaces: WorkspaceStore, workspace_id: Any):
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
        workspace = _managed_workspace(workspaces, workspace_id)
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


def move_workspace_realm(workspace_id: Any, realm_id: Any) -> tuple[dict, dict]:
    """Move a workspace into ``realm_id``. Returns ``(workspace_row, flags)`` with ``flags`` =
    ``{moved, from_realm_id, active_workspace_id}``: ``moved`` is False when that realm already owned
    it whole (nothing written); ``from_realm_id`` is the realm it left (None for a realm-less one);
    ``active_workspace_id`` is the active pointer after the reconcile.

    The rules, all decided here:

    * the target must exist and be live (``realm_not_found`` / ``realm_archived``); an archived
      workspace is restored first (``workspace_archived``);
    * a realm's default workspace — and the reserved ``ws_default`` — never leaves its realm
      (``realm_default_workspace``, with ``realm_id``);
    * a workspace owned by a SERVER-BOUND realm is not moved out (``workspace_realm_server_bound``,
      with ``owner_realm_id``): realm sync would put the other members' copy back, or delete this
      one on the next pull. Moving INTO a server-bound realm is allowed — it is how a local
      workspace gets shared — and lifts the target's delete ledger for the id.

    Writes, under the assign lock: the workspace's ``realm_id`` back-reference first, then every
    source realm's ``workspace_ids`` entry out, then the target's in — so a crash in between leaves
    a state a replay of the same move heals. Last, the active-workspace reconcile: when the moved
    workspace is the ACTIVE one and the active realm is not the target, the active realm keeps the
    operator and the workspace pointer falls to that realm's next workspace
    (``reconcile_active_workspace_to_realm``) — the two pointers never straddle realms.
    """
    target_id = _clean_id(realm_id)
    workspaces, realms = WorkspaceStore(), RealmStore()
    with workspace_realm_assign_lock():
        workspace = _managed_workspace(workspaces, workspace_id)
        try:
            target = realms.get(target_id)
        except NotFound:
            raise WorkspaceManageRefused(WorkspaceManageReason.REALM_NOT_FOUND) from None
        if target.archived:
            raise WorkspaceManageRefused(WorkspaceManageReason.REALM_ARCHIVED, realm_id=target.id)
        if workspace.archived:
            raise WorkspaceManageRefused(WorkspaceManageReason.WORKSPACE_ARCHIVED)
        every = realms.list_all(include_archived=True)
        sources = [item for item in every if item.id != target.id
                   and (item.id == workspace.realm_id or workspace.id in (item.workspace_ids or []))]
        from_realm_id = (workspace.realm_id if workspace.realm_id and workspace.realm_id != target.id
                         else sources[0].id if sources else None)
        if workspace.id == DEFAULT_WORKSPACE_ID and workspace.realm_id != target.id:
            raise WorkspaceManageRefused(WorkspaceManageReason.REALM_DEFAULT, realm_id=workspace.realm_id or DEFAULT_REALM_ID)
        for source in sources:
            if source.default_workspace_id == workspace.id:
                raise WorkspaceManageRefused(WorkspaceManageReason.REALM_DEFAULT, realm_id=source.id)
            if source.server_id:
                raise WorkspaceManageRefused(WorkspaceManageReason.SERVER_BOUND, owner_realm_id=source.id)
        moved = workspace.realm_id != target.id
        if moved:
            workspace.realm_id = target.id
            workspace = workspaces.save(workspace)
        for source in sources:
            source.workspace_ids = [wid for wid in (source.workspace_ids or []) if wid != workspace.id]
            realms.save(source)
            moved = True
        target_changed = lift_deleted_workspace(target, workspace.id)
        if workspace.id not in target.workspace_ids:
            target.workspace_ids.append(workspace.id)
            target_changed = True
        if target_changed:
            realms.save(target)
            moved = True
        active_realm_id = realms.active_id()
        if workspaces.active_id() == workspace.id and active_realm_id and active_realm_id != target.id:
            try:
                reconcile_active_workspace_to_realm(realms.get(active_realm_id))
            except NotFound:  # a dangling realm pointer has no realm to reconcile to
                pass
    flags = {"moved": moved, "from_realm_id": from_realm_id, "active_workspace_id": workspaces.active_id()}
    return workspace_row(workspace), flags
