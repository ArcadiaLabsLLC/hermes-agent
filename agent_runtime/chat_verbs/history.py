"""``persona chat history`` / ``runtime.persona.chat.history`` — one transcript page.

The fetch that replaces the message tail S2 evicts from the frame: the frame
carries the recency pointer, this returns the messages. ``chat_scope`` rides
every envelope so a ``count: 0`` says WHICH state.db answered (the 2026-08-12
ambient chat-history incident).
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["HISTORY_PAGE_MAX", "clamp_history_limit", "persona_chat_history_page", "persona_chat_history_search"]

#: The page ceiling both doors clamp to (the argv verb's ``--limit`` help).
HISTORY_PAGE_MAX = 40


def clamp_history_limit(limit: Any) -> int:
    """``1..40``; absent, zero or unparseable reads as a full page."""
    try:
        value = int(limit or HISTORY_PAGE_MAX)
    except (TypeError, ValueError):
        value = HISTORY_PAGE_MAX
    return max(1, min(HISTORY_PAGE_MAX, value))


def persona_chat_history_page(session_id: str, *, limit: Any = HISTORY_PAGE_MAX, before: str | None = None) -> dict:
    """The page row: ``ok``, ``messages``, ``count``, the ``before`` cursor,
    ``resolution`` and ``chat_scope``; ``ok: false`` with ``error_kind`` when
    the read did not happen (never rendered as an empty conversation)."""
    from ..persona_chat_history import persona_chat_session_messages
    from ..root_observability import attach_root_observability

    return attach_root_observability(
        persona_chat_session_messages(session_id=session_id, limit=clamp_history_limit(limit), before=before),
        chat_scope=True,
    )


def persona_chat_history_search(session_id: str, query: str, *, limit: Any = None, before: str | None = None) -> dict:
    """One page of hits in this conversation's history, each openable by the page read above
    (:mod:`agent_runtime.persona_chat_history.search`); the same ``chat_scope`` stamp."""
    from ..persona_chat_history.search import persona_chat_session_search
    from ..root_observability import attach_root_observability

    return attach_root_observability(
        persona_chat_session_search(session_id=session_id, query=query, limit=limit, before=before),
        chat_scope=True,
    )
