"""The account a monitor belongs to (row ``RT-LENS-EPISODE-CHAT-OWNED-BY-THE-MONITORS-ACCOUNT``).

An Episode's chat is minted by no client, so it borrowed the client scope of the persona's current
chat (``trigger._operator_client_scope``). A monitor sealed by an account that had no chat with
the persona yet minted its Episode chats unscoped, and that account's Lens receipt "Open chat" was
then refused as another account's. The monitor now records the scope of the account that SEALED
it (``monitors.client_scope``), and the trigger stamps that first.

The stored scope is account authority: whatever it names is the account every later Episode chat
is filed under. So only a scope the server verified for the sealing request is stored
(:func:`verified_seal_scope`): the request's own ``client_scope`` checked by
``conversation_owner.request_client_scope`` (the opaque launcher digest, never a credential), and
for a paired DEVICE caller, the scope bound at its pairing — a device that names any other scope
is refused, as is one with no bound scope that names one. A re-seal by a scoped client never moves
a monitor recorded for another account (``conversation_owner_changed``); an unscoped native
operator's re-seal keeps the recorded owner, as ``require_session_owner`` lets an unscoped caller
keep its authority without adopting anything.
"""

from __future__ import annotations

import sqlite3
from enum import Enum
from typing import Any, Mapping

from .wire_value import LensRefusal

__layer__ = "stores"

class OwnerRefusal(str, Enum):
    """Why a seal's account scope is refused: the words ``conversation_owner`` already speaks."""

    INVALID_CLIENT_SCOPE = "invalid_client_scope"
    OWNER_CHANGED = "conversation_owner_changed"


class LensOwnerError(LensRefusal):
    """The sealing request's scope refused: ``reason`` is an :class:`OwnerRefusal`."""

    reasons = OwnerRefusal
    summary = "Invalid conversation owner."


def add_owner_column(conn: sqlite3.Connection) -> None:
    """A store written before the owner gains ``monitors.client_scope``; its monitors read NULL."""

    if "client_scope" not in {row[1] for row in conn.execute("PRAGMA table_info(monitors)")}:
        conn.execute("ALTER TABLE monitors ADD COLUMN client_scope TEXT")


def verified_seal_scope(params: Mapping[str, Any], bound_scope: str | None, *, device: bool) -> str | None:
    """The scope the sealing request may record, or :class:`LensOwnerError`.

    ``device``: the caller is a paired device, held to ``bound_scope`` (its pairing's, read off the
    device store by the transport's caller, never off the request). Any other caller kind holds the
    install's own credential, so the request's checked scope is the account's namespace."""

    from ..conversation_owner import ConversationOwnerError, request_client_scope

    try:
        requested = request_client_scope(params)
    except ConversationOwnerError as exc:
        raise LensOwnerError(OwnerRefusal.INVALID_CLIENT_SCOPE) from exc
    if not device:
        return requested
    if requested is not None and requested != bound_scope:
        raise LensOwnerError(OwnerRefusal.OWNER_CHANGED)
    return bound_scope


def owner_for_seal(row: sqlite3.Row, scope: str | None) -> str | None:
    """The owner the monitor keeps after a seal by ``scope``; refuses taking another account's."""

    from .store import LensStoreError, StoreRefusal

    recorded = row["client_scope"]
    if scope is None:
        return recorded
    if recorded is not None and recorded != scope:
        raise LensStoreError(StoreRefusal.OWNER_CHANGED)
    return scope


def monitor_client_scope(monitor_id: str) -> str | None:
    """The account the monitor was sealed by, or ``None`` (never sealed by a scoped client, gone,
    or any read failure — the caller falls back to the persona's current chat)."""

    from .store import LensStore

    store = LensStore()
    if not store.exists():
        return None
    with store._db() as conn:
        row = store._row(conn, monitor_id)
    return None if row is None else row["client_scope"]
