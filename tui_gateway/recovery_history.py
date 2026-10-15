"""Bounded delivery of the native display projection, without a second history store."""
from __future__ import annotations

import json

from tui_gateway.recovery_history_delivery import HistoryDeliveries

_CHUNK_CHARS = 16384
_PAGE_BYTES = 256 * 1024
_deliveries = HistoryDeliveries()


def _matches(session, position):
    return (not session.get("_closing") and position["session_key"] == session.get("session_key")
            and position["version"] == int(session.get("history_version", 0)))


def history_page(server, session, params):
    position = params["position"]
    index, offset = params.get("message_index", 0), params.get("offset", 0)
    reset = {"chunks": [], "message_index": index, "offset": offset, "more": False, "reset": True}
    with session["history_lock"]:
        if not _matches(session, position):
            discard_history(session)
            return reset
        owner = session.setdefault("_history_delivery_owner", object())
    key = (owner, position["session_key"], position["version"], position["through_row"])
    try:
        result = _deliveries.read(key, lambda: _project_history(server, session, position),
            lambda delivery: _history_chunks(delivery, index, offset))
    except OSError:
        raise RuntimeError("History is unavailable") from None
    with session["history_lock"]:
        if not _matches(session, position):
            discard_history(session)
            return reset
    return result


def discard_history(session):
    _deliveries.discard(session.get("_history_delivery_owner"))


def prune_history():
    _deliveries.prune()


def _project_history(server, session, position):
    with server._session_db(session) as db:
        if db is None:
            raise RuntimeError("History is unavailable")
        history = db.get_messages_as_conversation(position["session_key"], include_ancestors=True,
            include_compacted=True, include_row_ids=True, through_row_id=position["through_row"])
    return server._history_to_messages(history, profile_home=session.get("profile_home"))


def _history_chunks(messages, index, offset):
    chunks, size = [], 0
    if index < 0 or offset < 0 or index > messages.count or (index == messages.count and offset):
        raise ValueError("Invalid history position")
    while index < messages.count and size < _PAGE_BYTES:
        text, complete = messages.chunk(index, offset, _CHUNK_CHARS)
        chunk = {"index": index, "offset": offset, "data": text, "complete": complete}
        chunks.append(chunk)
        size += len(json.dumps(chunk, ensure_ascii=True))
        offset += len(text)
        if complete:
            index, offset = index + 1, 0
    return {"chunks": chunks, "message_index": index, "offset": offset, "more": index < messages.count}
