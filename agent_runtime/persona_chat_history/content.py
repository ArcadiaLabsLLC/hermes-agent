"""Windowed reads of displayed messages and native tool records; no second store."""
from __future__ import annotations

import json
import logging
from typing import Any

from ..persona_chat_continuity.bounds import _redacted
from .messages import ChatSessionReadRefused, existing_chat_session
from .text import text_revision

__layer__ = "lanes"
CONTENT_WINDOW_CHARS = 16_000


class ContentReadRefused(ValueError):
    pass


def _message_text(db, session_id: str, content_id: str) -> str:
    from .curation import _safe_curated_messages

    rows, _, unread = _safe_curated_messages(db, session_id=session_id, preview=False)
    if unread is not None:
        raise ContentReadRefused("content_unavailable")
    matches = [row["text"] for row in rows if row.get("id") == content_id]
    if len(matches) != 1:
        raise ContentReadRefused("content_unavailable")
    return matches[0]


def _tool_text(db, session_id: str, content_id: str, *, field: str) -> str:
    from .curation import _read_raw_messages

    matches = []
    for row in _read_raw_messages(db, session_id):
        if row.get("display_kind") == "hidden":
            continue
        if field == "tool_result" and row.get("role") == "tool" and row.get("tool_call_id") == content_id:
            matches.append(row.get("content"))
        if field == "tool_input" and row.get("role") == "assistant":
            for call in row.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id") == content_id:
                    matches.append((call.get("function") or {}).get("arguments"))
    if len(matches) != 1:
        raise ContentReadRefused("content_unavailable")
    value = matches[0]
    return _redacted(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))


def _tool_input(db, session_id, content_id):
    return _tool_text(db, session_id, content_id, field="tool_input")


def _tool_result(db, session_id, content_id):
    return _tool_text(db, session_id, content_id, field="tool_result")


_READERS = {"message": _message_text, "tool_input": _tool_input, "tool_result": _tool_result}


def read_chat_content(params: dict[str, Any]) -> dict[str, Any]:
    """Require the existing session/account scope and pin every continuation to its text."""
    session_id, reference = params.get("session_id"), params.get("content_ref")
    offset = params.get("offset", 0)
    if (not isinstance(session_id, str) or not session_id.strip()
            or not isinstance(reference, dict) or not isinstance(reference.get("kind"), str)
            or reference["kind"] not in _READERS
            or not isinstance(reference.get("id"), str) or not reference["id"]
            or type(offset) is not int or offset < 0):
        return {"ok": False, "error_kind": "invalid_content_request"}
    try:
        with existing_chat_session(session_id=session_id, client_scope=params.get("client_scope")) as session:
            text = _READERS[reference["kind"]](session.db, session_id, reference["id"])
        revision = text_revision(text)
        requested_revision = reference.get("revision")
        if (requested_revision is not None and requested_revision != revision) or (offset and not requested_revision):
            raise ContentReadRefused("content_changed")
        if offset > len(text):
            raise ContentReadRefused("invalid_content_offset")
        end = min(len(text), offset + CONTENT_WINDOW_CHARS)
        return {"ok": True, "session_id": session_id, "content_ref": {
                    "kind": reference["kind"], "id": reference["id"], "revision": revision},
                "text": text[offset:end], "offset": offset, "total_chars": len(text),
                "next_offset": end if end < len(text) else None}
    except ChatSessionReadRefused as exc:
        return exc.envelope
    except ContentReadRefused as exc:
        return {"ok": False, "error_kind": str(exc)}
    except Exception as exc:
        # A storage failure is unavailable, never an empty or complete read.
        logging.getLogger(__name__).warning("chat_content_read_failed type=%s", type(exc).__name__)
        return {"ok": False, "error_kind": "content_unavailable"}
