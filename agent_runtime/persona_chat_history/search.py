"""``runtime.persona.chat.history.search``: find a conversation's messages without loading its history.

The serve's only transcript search was the agent's ``session_search`` tool
(``hermes_state_search.py::search_messages``), which spans every session and has
no session-id filter; post-filtering its FTS pages breaks paging, and a fork-side
FTS query would duplicate its CJK/trigram routing. More to the point, both read
RAW rows: tool and system scaffolding, envelopes, and text the transcript
redactor hides. This search reads exactly what the history page read shows —
:func:`curation._safe_curated_messages` over the conversation's whole
compression lineage, un-truncated (``preview=False``) — so a hit can never
surface text the history would not, and every hit opens in that read.

Matching: the query's whitespace-separated terms, case-folded, must all occur
in one message's text (substring, so CJK needs no tokenizer). Hits come
newest-first, at most :data:`SEARCH_PAGE_MAX` per page; ``next_before`` (the
history cursor shape, naming the oldest hit returned) continues to older hits.
Each hit's ``open_before`` is the history ``before`` cursor whose page ENDS at
that hit (``None``: the hit is in the newest page).
"""

from __future__ import annotations

from typing import Any

from .. import chat_session_scope
from ..persona_assignments import safe_assignment_text
from .curation import _decode_history_cursor, _encode_history_cursor, _history_revision, _safe_curated_messages
from .messages import _cursor_refusal, _resolve_scope, _with_chat_scope
from .trace_rows import _bounded_message_tail

__layer__ = "lanes"
__all__ = ["SEARCH_PAGE_MAX", "SEARCH_QUERY_MAX_CHARS", "persona_chat_session_search"]

#: Hits per page ceiling (and the default).
SEARCH_PAGE_MAX = 20
#: A query past this is refused rather than scanned.
SEARCH_QUERY_MAX_CHARS = 200
#: Characters of context either side of the first matched term.
_SNIPPET_CONTEXT = 80


def _clamp_limit(limit: Any) -> int:
    try:
        value = int(limit or SEARCH_PAGE_MAX)
    except (TypeError, ValueError):
        value = SEARCH_PAGE_MAX
    return max(1, min(SEARCH_PAGE_MAX, value))


def _snippet(text: str, folded: str, terms: list[str]) -> str:
    at = min(folded.find(term) for term in terms)
    start, end = max(0, at - _SNIPPET_CONTEXT), min(len(text), at + _SNIPPET_CONTEXT)
    body = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def _invalid_search(session_id: str, error: str) -> dict[str, Any]:
    return {"ok": False, "error_kind": "invalid_request", "error": error, "session_id": session_id}


def persona_chat_session_search(
    *, session_id: str, query: str, limit: Any = None, before: str | None = None, session_db: Any | None = None,
) -> dict[str, Any]:
    """One page of hits: ``ok``, ``hits``, ``count``, ``has_more``, ``next_before``,
    ``history_revision``, ``redaction_status``, ``chat_scope``; the history read's typed
    refusals when the transcript could not be read (never an empty result)."""
    if len(query) > SEARCH_QUERY_MAX_CHARS:
        return _invalid_search(session_id, f"query is longer than {SEARCH_QUERY_MAX_CHARS} characters")
    terms = sorted({term.casefold() for term in query.split()})
    if not terms:
        return _invalid_search(session_id, "query has no search terms")
    bounded = _clamp_limit(limit)
    scope, db = None, session_db
    if db is None:
        scope, refusal = _resolve_scope(session_id, _bounded_message_tail(bounded))
        if refusal is not None:
            return refusal
        db = chat_session_scope.open_chat_session_db(scope, access=chat_session_scope.SessionDbAccess.READ)
    messages, status, unread = _safe_curated_messages(db, session_id=session_id, preview=False)
    if unread is not None:
        return _with_chat_scope({"ok": False, "error_kind": unread["error_kind"], "error": unread["detail"],
                                 "session_id": session_id, "limit": bounded}, scope)
    end = len(messages)
    if before:
        cursor = _decode_history_cursor(before)
        if cursor is None or cursor.get("session_id") != session_id:
            return _cursor_refusal("search cursor is malformed or belongs to another session", session_id)
        before_id = safe_assignment_text(cursor.get("before_id"), limit=160)
        end = next((index for index, row in enumerate(messages) if row.get("id") == before_id), None)
        if end is None:
            return _cursor_refusal("search cursor no longer resolves in this session", session_id)
    hits: list[dict[str, Any]] = []
    has_more = False
    for index in range(end - 1, -1, -1):
        row = messages[index]
        text = str(row.get("text") or "")
        folded = text.casefold()
        if not all(term in folded for term in terms):
            continue
        if len(hits) == bounded:
            has_more = True
            break
        following = messages[index + 1]["id"] if index + 1 < len(messages) else None
        hits.append({
            "id": row["id"], "role": row.get("role"), "timestamp": row.get("timestamp"),
            "snippet": _snippet(text, folded, terms),
            "open_before": _encode_history_cursor(session_id, following) if following else None,
        })
    return _with_chat_scope({
        "ok": True, "session_id": session_id, "query": query, "limit": bounded, "count": len(hits),
        "has_more": has_more,
        "next_before": _encode_history_cursor(session_id, hits[-1]["id"]) if has_more else None,
        "history_revision": _history_revision(session_id, messages, session_db=db),
        "redaction_status": status, "hits": hits,
    }, scope)
