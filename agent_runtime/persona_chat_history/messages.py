"""``persona_chat_session_messages``: one conversation's curated transcript, with an honest read status.

Separate because it is the transcript entry point (the harness CLI, the live
log backfill, the peer directory) — one conversation, not the roster.
"""

from __future__ import annotations

from typing import Any

from ..persona_assignments import safe_assignment_text
from .curation import (
    _decode_history_cursor,
    _encode_history_cursor,
    _history_revision,
    _safe_curated_messages,
)
from .trace_rows import _bounded_message_tail
from .vocabulary import (
    CHAT_SCOPE_MISMATCH,
    CHAT_SCOPE_UNRESOLVED,
    DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
)

__layer__ = "lanes"
__all__ = [
    "persona_chat_session_messages",
]


def persona_chat_session_messages(
    *,
    session_id: str,
    limit: int = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    before: str | None = None,
    session_db: Any | None = None,
) -> dict[str, Any]:
    """Paged on-demand read of one persona chat session's complete transcript.

    Backs ``harness persona chat history`` — the fetch that replaces the message
    tail S2 evicts from the steady-state frame. Each page is bounded, but the
    opaque ``before`` cursor can walk all curated rows across the root's native
    compression lineage. The log IS the history: no new storage, just a
    per-session read of the durable SessionDB the frame previously projected.
    """

    bounded = _bounded_message_tail(limit)
    scope = None
    db = session_db
    if db is None:
        # Self-resolved acquisition is PER-CONVERSATION: the persona instance
        # bound to this session may record where its transcript lives (the
        # INSTANCE_RECORDED rung), and the resolved scope rides every envelope
        # this function returns so an empty page always says which state.db
        # answered. A caller that passes its own ``session_db`` owns the
        # acquisition and its provenance; none of this applies to it.
        from ..chat_session_scope import (
            ChatHeadSource,
            ambient_chat_reads_allowed,
            open_chat_session_db,
            resolve_chat_session_scope,
        )

        scope = resolve_chat_session_scope(session_id=session_id)
        if scope.mismatch is not None:
            # Two AUTHORITIES disagree about where this conversation lives.
            # Serving the read from either would risk answering from the wrong
            # store — a well-formed empty page — so neither side is silently
            # preferred; the refusal names both heads.
            return {
                "ok": False,
                "error_kind": CHAT_SCOPE_MISMATCH,
                "error": (
                    "this conversation's persona instance records its transcript home at "
                    f"{scope.mismatch.recorded_head} but "
                    f"{scope.mismatch.resolved_source.value} resolves "
                    f"{scope.mismatch.resolved_head}; reading either could answer from "
                    "the wrong store, so this read refuses instead of returning a "
                    "plausible empty page. Align HERMES_HEAD_HOME with the recorded "
                    "home, or re-open the chat under the intended head."
                ),
                "session_id": session_id,
                "limit": bounded,
                "chat_scope": scope.payload(),
            }
        if scope.source is ChatHeadSource.AMBIENT_HOME and not ambient_chat_reads_allowed():
            # "I do not know where to look" must not render as "no messages".
            # Rare by construction after the machine root anchor: an anchored
            # machine resolves the shared-root pointer even ambiently, so this
            # fires only where NOTHING ever recorded the operator root.
            return {
                "ok": False,
                "error_kind": CHAT_SCOPE_UNRESOLVED,
                "error": (
                    "no authority names the operator chat database from this process; "
                    "reading the degraded ambient fallback would answer from whichever "
                    "state.db this process happens to resolve — a well-formed empty "
                    "page indistinguishable from a real one. Set HERMES_HEAD_HOME, or "
                    "start `harness serve` once so the head pointer and machine root "
                    "anchor are published, or set HERMES_ALLOW_AMBIENT_CHAT_READS=1 to "
                    "accept the guess on a deliberately single-root setup."
                ),
                "session_id": session_id,
                "limit": bounded,
                "chat_scope": scope.payload(),
            }
        if scope.source is ChatHeadSource.AMBIENT_HOME:
            import logging

            logging.getLogger(__name__).warning(
                "chat read for %s is using the degraded AMBIENT chat scope (%s) "
                "because HERMES_ALLOW_AMBIENT_CHAT_READS is set — its answer is a "
                "guess about which state.db holds this conversation",
                session_id,
                scope.db_path,
            )
        db = open_chat_session_db(scope)
    messages, status, unread = _safe_curated_messages(db, session_id=session_id)
    if unread is not None:
        # A read that did not happen is NOT an empty conversation. This used to
        # return the full success envelope — ``ok: True``, ``count: 0``,
        # ``redaction_status: "safe"`` — byte-identical to a genuinely empty
        # chat, so an operator concluded their messages were lost and an agent
        # hunting a missing turn was told authoritatively there were none.
        return _with_chat_scope(
            {
                "ok": False,
                "error_kind": unread["error_kind"],
                "error": unread["detail"],
                "session_id": session_id,
                "limit": bounded,
            },
            scope,
        )
    end = len(messages)
    if before:
        cursor = _decode_history_cursor(before)
        if cursor is None or cursor.get("session_id") != session_id:
            return _with_chat_scope(
                {
                    "ok": False,
                    "error_kind": "invalid_history_cursor",
                    "error": "history cursor is malformed or belongs to another session",
                    "session_id": session_id,
                },
                scope,
            )
        before_id = safe_assignment_text(cursor.get("before_id"), limit=160)
        match = next(
            (index for index, row in enumerate(messages) if row.get("id") == before_id),
            None,
        )
        if match is None:
            return _with_chat_scope(
                {
                    "ok": False,
                    "error_kind": "invalid_history_cursor",
                    "error": "history cursor no longer resolves in this session",
                    "session_id": session_id,
                },
                scope,
            )
        end = match
    start = max(0, end - bounded)
    page = messages[start:end]
    has_more = start > 0
    return _with_chat_scope(
        {
            "ok": True,
            "session_id": session_id,
            "limit": bounded,
            "count": len(page),
            "total_count": len(messages),
            "has_more": has_more,
            "next_before": (
                _encode_history_cursor(session_id, page[0]["id"])
                if has_more and page
                else None
            ),
            "history_revision": _history_revision(session_id, messages, session_db=db),
            "redaction_status": status,
            "messages": page,
        },
        scope,
    )


def _with_chat_scope(envelope: dict[str, Any], scope: Any) -> dict[str, Any]:
    """Stamp the ACTUAL per-conversation scope onto a self-resolved envelope.

    ``attach_root_observability`` at the CLI verb resolves the PROCESS-level
    scope and never overwrites an existing key, so stamping here is what makes
    the envelope state the conversation's true frame of reference — including
    the ``instance_recorded`` rung the process-level resolution cannot see.
    ``scope`` is ``None`` when the caller supplied its own ``session_db``; its
    provenance is unknown here, so nothing is claimed about it.
    """

    if scope is not None:
        envelope["chat_scope"] = scope.payload()
    return envelope
