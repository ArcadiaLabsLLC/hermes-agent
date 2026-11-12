"""Putting a realm away and bringing it back — ONE implementation per verb, two doors each
(RT-REALM-ARCHIVE-RESTORE).

``harness realm archive`` / ``runtime.realm.archive`` call :func:`archive_realm`; ``harness realm
unarchive`` / ``runtime.realm.unarchive`` call :func:`unarchive_realm`. Each decides, writes through
``RealmStore`` and RAISES :class:`RealmManageRefused` with a typed reason for its door to render; a
client draws the refusal, it never pre-judges one.

The rules are the owner's (2026-11-12): "realm must be empty", "same with the server realms", and of a
server realm "you need to remove yourself from the server to get rid of it". ``archived`` is this
machine's flag only: realm sync neither publishes it nor adopts it (``realm_sync/artifacts.py``
``_workspace_realm_artifacts``, ``realm_sync/pull.py`` ``_pulled_artifact_bytes``).

Pinned by ``tests/agent_runtime/test_realm_manage.py``.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from .default_realm import default_realm_id
from .errors import NotFound
from .locks import workspace_realm_assign_lock
from .models import Realm
from .scope_activation import realm_row
from .store import RealmStore, WorkspaceStore

__layer__ = "lanes"
__all__ = ["RealmManageReason", "RealmManageRefused", "archive_realm", "unarchive_realm"]


class RealmManageReason(StrEnum):
    INVALID = "invalid_request"
    REALM_NOT_FOUND = "realm_not_found"
    #: The realm comes from a server: it is every member's, and the way to be rid of it is to leave
    #: the server. Carries ``server_id``.
    SERVER_BOUND = "realm_server_bound"
    #: The account's default realm (``default_realm.default_realm_id``): choose another default first.
    IS_DEFAULT = "realm_is_default"
    #: The active realm: switch to another realm first. Checked before the default, because with no
    #: default chosen the active realm is also the resolved default and "switch away" is the next step.
    IS_ACTIVE = "realm_is_active"
    #: It still holds a workspace that is not archived. Carries ``workspace_ids`` (the live ones).
    NOT_EMPTY = "realm_not_empty"


class RealmManageRefused(ValueError):
    def __init__(self, reason: RealmManageReason, **details: Any):
        self.reason = reason
        self.details = details
        super().__init__(reason.value)


def _managed_realm(realms: RealmStore, realm_id: Any) -> Realm:
    if not isinstance(realm_id, str) or not realm_id.strip() or len(realm_id) > 256 or any(ord(c) < 32 for c in realm_id):
        raise RealmManageRefused(RealmManageReason.INVALID)
    try:
        return realms.get(realm_id.strip())
    except NotFound:
        raise RealmManageRefused(RealmManageReason.REALM_NOT_FOUND) from None


def _live_workspace_ids(realm: Realm) -> list[str]:
    """The workspaces that keep ``realm`` from being empty: not archived, and either homed in it
    (``realm_id``) or realm-less and listed on its ``workspace_ids``. An archived workspace does not
    count — it is already out of every selector and comes back only after its realm does."""
    listed = set(realm.workspace_ids or [])
    return sorted(
        item.id for item in WorkspaceStore().list_all()
        if item.realm_id == realm.id or (item.realm_id is None and item.id in listed)
    )


def archive_realm(realm_id: Any) -> tuple[dict, bool]:
    """Put a realm away. Returns ``(realm_row(full), changed)``; ``changed`` is False when it was
    already archived (nothing checked, nothing written).

    Refused, in this order, nothing written: ``realm_server_bound`` (+ ``server_id``),
    ``realm_is_active``, ``realm_is_default``, ``realm_not_empty`` (+ ``workspace_ids``). Held under
    the workspace/realm assign lock, so a move or an assign cannot land a workspace in the realm
    between the emptiness read and the write. It moves no pointer and touches no workspace.
    """
    realms = RealmStore()
    with workspace_realm_assign_lock():
        realm = _managed_realm(realms, realm_id)
        if realm.archived:
            return realm_row(realm, full=True), False
        if realm.server_id:
            raise RealmManageRefused(RealmManageReason.SERVER_BOUND, server_id=realm.server_id)
        if realm.id == realms.active_id():
            raise RealmManageRefused(RealmManageReason.IS_ACTIVE)
        if realm.id == default_realm_id():
            raise RealmManageRefused(RealmManageReason.IS_DEFAULT)
        live = _live_workspace_ids(realm)
        if live:
            raise RealmManageRefused(RealmManageReason.NOT_EMPTY, workspace_ids=live)
        realm = realms.archive(realm.id)
    return realm_row(realm, full=True), True


def unarchive_realm(realm_id: Any) -> tuple[dict, bool]:
    """Bring an archived realm back (archive's reverse). Returns ``(realm_row(full), changed)``;
    ``changed`` is False when it was not archived (nothing written). Its archived workspaces stay
    archived — each is restored by ``runtime.workspace.unarchive``, which the realm's return unblocks."""
    realms = RealmStore()
    with workspace_realm_assign_lock():
        realm = _managed_realm(realms, realm_id)
        changed = bool(realm.archived)
        if changed:
            realm = realms.unarchive(realm.id)
    return realm_row(realm, full=True), changed
