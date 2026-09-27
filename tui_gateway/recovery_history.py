"""Bounded delivery of the native display projection, without a second history store."""
from __future__ import annotations

import json

_CHUNK_CHARS = 16384
_PAGE_BYTES = 256 * 1024


def _matches(session, position):
    return (position["session_key"] == session.get("session_key")
            and position["version"] == int(session.get("history_version", 0)))


def history_page(server, session, params):
    position = params["position"]
    index, offset = params.get("message_index", 0), params.get("offset", 0)
    reset = {"chunks": [], "message_index": index, "offset": offset, "more": False, "reset": True}
    with session["history_lock"]:
        if not _matches(session, position):
            return reset
    with server._session_db(session) as db:
        if db is None:
            raise RuntimeError("History is unavailable")
        history = db.get_messages_as_conversation(position["session_key"], include_ancestors=True,
            include_compacted=True, include_row_ids=True, through_row_id=position["through_row"])
    messages = server._history_to_messages(history, profile_home=session.get("profile_home"))
    with session["history_lock"]:
        if not _matches(session, position):
            return reset
    return _history_chunks(messages, index, offset)


def _history_chunks(messages, index, offset):
    chunks, size = [], 0
    if index > len(messages) or (index == len(messages) and offset):
        raise ValueError("Invalid history position")
    while index < len(messages) and size < _PAGE_BYTES:
        encoded = json.dumps(messages[index], ensure_ascii=False, separators=(",", ":"))
        if offset >= len(encoded):
            raise ValueError("Invalid history offset")
        while offset < len(encoded) and size < _PAGE_BYTES:
            text = encoded[offset:offset + _CHUNK_CHARS]
            chunk = {"index": index, "offset": offset, "data": text,
                     "complete": offset + len(text) == len(encoded)}
            chunks.append(chunk)
            size += len(json.dumps(chunk, ensure_ascii=True))
            offset += len(text)
        if offset == len(encoded):
            index, offset = index + 1, 0
    return {"chunks": chunks, "message_index": index, "offset": offset, "more": index < len(messages)}
