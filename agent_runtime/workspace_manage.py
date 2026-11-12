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
from .store import RealmStore, WorkspaceStore, lift_deleted_workspace, record_deleted_workspace

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
    #: move out removes the workspace for every member of that realm who is not in the target. The
    #: caller must say so by naming that realm (``confirm_leave_realm`` = its id or its name); the
    #: refusal carries ``owner_realm_id`` and ``owner_realm_name`` for the client's confirm dialog
    #: (RT-WORKSPACE-MOVE-OUT-OF-SERVER-REALM).
    CONFIRM_LEAVE = "workspace_move_confirm_required"


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


def _names_realm(confirm: Any, realm) -> bool:
    """Whether ``confirm`` is the realm's id, or its name (case and outer spaces aside)."""
    if not isinstance(confirm, str) or not confirm.strip():
        return False
    said = confirm.strip()
    return said == realm.id or said.casefold() == str(realm.name or "").strip().casefold()


def move_workspace_realm(workspace_id: Any, realm_id: Any, *, confirm_leave_realm: Any = None,
                         credential: Any = None, membership: Any = None) -> tuple[dict, dict]:
    """Move a workspace into ``realm_id``. Returns ``(workspace_row, flags)`` with ``flags`` =
    ``{moved, from_realm_id, active_workspace_id, publish_owed}``: ``moved`` is False when that realm
    already owned it whole (nothing written); ``from_realm_id`` is the realm it left (None for a
    realm-less one); ``active_workspace_id`` is the active pointer after the reconcile;
    ``publish_owed`` is the server-bound realms this move changed, in the order to publish them.

    The rules, all decided here:

    * the target must exist and be live (``realm_not_found`` / ``realm_archived``); an archived
      workspace is restored first (``workspace_archived``);
    * a realm's default workspace — and the reserved ``ws_default`` — never leaves its realm
      (``realm_default_workspace``, with ``realm_id``);
    * moving INTO a server-bound realm is how a local workspace gets shared; it lifts the target's
      delete ledger for the id;
    * moving OUT of a SERVER-BOUND realm removes the workspace for the team — every member of that
      realm who is not also a member of the target loses it at their next pull (their copy is
      deleted, or kept archived when it owns local goals). So it is a write to the shared realm,
      and it is refused unless both hold, with nothing written:

      - **the caller may publish to the source realm.** ``realm_sync``'s own publish gate runs
        (``_authorize(source, "publish", …)`` with the launcher-brokered ``credential``) and its
        ``RealmSyncError`` propagates: ``sync_auth_failed`` (no credential, or one for another
        realm), ``role_insufficient`` / ``membership_denied``, ``realm_revoked``. Asked FIRST when
        a credential is given, so a member who may not publish is told so before being asked to
        confirm; a call with no credential is asked to confirm first.
      - **the caller named the realm it leaves.** ``confirm_leave_realm`` must be the source
        realm's id or name; absent or naming anything else is ``workspace_move_confirm_required``
        with ``owner_realm_id`` and ``owner_realm_name``.

    * EVERY move out writes the LEAVE into the realm it left (``record_deleted_workspace`` — what
      ``WorkspaceStore.delete`` writes: off ``workspace_ids``, onto ``deleted_workspace_ids``, a
      live lift superseded), server-bound or not, so realm sync carries it whenever that realm
      syncs — now or later. A local realm reaches other machines too: through the player's
      personal repo (``sync_manifest_ref`` is set by its first sync, so "does it sync" cannot be
      asked at move time — RT-WORKSPACE-MOVE-OUT-OF-PERSONAL-REPO-REALM), and a realm that turned
      local when the member left its server is bound again by a re-join
      (RT-REJOIN-KEEPS-WORKSPACES-MOVED-WHILE-LOCAL). Without the leave the other machine's copy
      is republished into the source, or the team's copy is written back over the moved one. Only
      the confirm and the publish gate above are a server-bound source's: a local realm is the
      player's own. The pull keeps the moved workspace on this machine (``realm_sync.pull``: the
      tombstone applier and the overwrite loop both leave a workspace that names another realm).
      Moving it back lifts the ledger again.

    Publish order (``publish_owed``): the TARGET first when it is server-bound, then the source —
    so the workspace is never absent from both remotes.

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
        shared = [source for source in sources if source.server_id]
        if shared:
            _admit_leaving_shared_realms(shared, from_realm_id, confirm_leave_realm, credential, membership)
        moved = workspace.realm_id != target.id
        if moved:
            workspace.realm_id = target.id
            workspace = workspaces.save(workspace)
        for source in sources:
            record_deleted_workspace(source, workspace.id)
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
    publish_owed = [realm.id for realm in ([target] if target.server_id else []) + shared] if moved else []
    flags = {"moved": moved, "from_realm_id": from_realm_id, "active_workspace_id": workspaces.active_id(),
             "publish_owed": publish_owed}
    return workspace_row(workspace), flags


def _admit_leaving_shared_realms(shared: list, from_realm_id: str | None, confirm: Any, credential: Any,
                                 membership: Any) -> None:
    """The two gates of a move out of server-bound realm(s) — see :func:`move_workspace_realm`."""
    from .realm_sync.git import _authorize

    def authorize() -> None:
        for source in shared:
            _authorize(source, "publish", membership, credential)

    if credential is not None:
        authorize()
    owner = next((source for source in shared if source.id == from_realm_id), shared[0])
    if not _names_realm(confirm, owner):
        raise WorkspaceManageRefused(WorkspaceManageReason.CONFIRM_LEAVE, owner_realm_id=owner.id,
                                     owner_realm_name=str(owner.name or ""))
    if credential is None:
        authorize()
