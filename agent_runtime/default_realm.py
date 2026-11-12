"""The account's default realm: where a workspace created with no realm lands (RT-ACCOUNT-DEFAULT-REALM).

One pointer file beside the active one (``paths.default_realm_path``), written only by
:func:`set_default_realm` — the one implementation behind ``harness realm default <id>`` and
``runtime.realm.set_default``. :func:`default_realm_id` is the ONE answer every reader takes: the
snapshot's top-level ``default_realm_id`` and ``workspace create`` with no realm. It is the stored
pointer while that names a live (present, unarchived) realm; else the reserved ``realm_default``; else
the active realm; else ``None`` (a store with no live realm). A client never re-derives it.

Pinned by ``tests/agent_runtime/test_default_realm.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from .default_scope import DEFAULT_REALM_ID
from .errors import NotFound
from .models import Realm
from .store import RealmStore

__layer__ = "lanes"
__all__ = ["DefaultRealmReason", "DefaultRealmRefused", "default_realm_id", "default_realm_row", "set_default_realm"]


class DefaultRealmReason(StrEnum):
    INVALID = "invalid_request"
    NOT_FOUND = "realm_not_found"
    ARCHIVED = "realm_archived"


class DefaultRealmRefused(ValueError):
    def __init__(self, reason: DefaultRealmReason):
        self.reason = reason
        super().__init__(reason.value)


def default_realm_id(realms: Iterable[Realm] | None = None) -> str | None:
    """The account's default realm id. ``realms`` is a caller's already-read list (the snapshot's,
    archived included) so the answer costs it no second directory read."""
    store = RealmStore()
    listed = store.list_all(include_archived=True) if realms is None else realms
    live = {item.id for item in listed if not item.archived}
    for candidate in (store.default_pointer_id(), DEFAULT_REALM_ID, store.active_id()):
        if candidate and candidate in live:
            return candidate
    return None


def set_default_realm(realm_id: Any) -> tuple[Realm, bool]:
    """Make ``realm_id`` the account's default. Returns ``(realm, changed)``; ``changed`` is False when
    the pointer already named it. An unknown realm and an archived one are refused, nothing written."""
    if not isinstance(realm_id, str) or not realm_id.strip() or len(realm_id) > 256 or any(ord(c) < 32 for c in realm_id):
        raise DefaultRealmRefused(DefaultRealmReason.INVALID)
    store = RealmStore()
    try:
        realm = store.get(realm_id.strip())
    except NotFound:
        raise DefaultRealmRefused(DefaultRealmReason.NOT_FOUND) from None
    if realm.archived:
        raise DefaultRealmRefused(DefaultRealmReason.ARCHIVED)
    return realm, store.set_default_pointer(realm.id)


def default_realm_row(realm_id: Any) -> dict:
    """The row both doors answer: :func:`set_default_realm`, then the realm row (``realm_row``) plus
    ``default_realm_id`` (re-read after the write) and ``changed``."""
    from .scope_activation import realm_row

    realm, changed = set_default_realm(realm_id)
    row = realm_row(realm)
    row["default_realm_id"] = default_realm_id()
    row["changed"] = changed
    return row
