"""``runtime.chat.clarify.dismiss`` — the operator closes an agent's question without answering it.

An agent-chat ``clarify`` ends its turn and leaves an open ticket; until this verb only the next
operator turn in that chat settled it, so a question the operator did not want to answer kept its
chat "waiting for your answer". Dismissing settles the ticket ``dismissed`` through the ticket
store (the one writer of ticket state), so every reader of "is a question waiting"
(:mod:`agent_runtime.clarify_waiting`) stops naming it, and the agent's next turn in that chat reads
one line saying so (the store's dismissal note, on the turn's volatile tail).

Idempotent: a ticket already dismissed, already answered or unknown answers ``ok`` with its
``outcome`` and changes nothing. A ticket asked in another chat is refused
``foreign_chat_session``, and a scoped caller dismisses only in a chat its scope owns.
"""

from __future__ import annotations

import logging
from typing import Any

__layer__ = "lanes"
__all__ = ["CLARIFY_DISMISS_CAPABILITY", "dismiss_clarify_question"]

logger = logging.getLogger(__name__)

CLARIFY_DISMISS_CAPABILITY = "mission.chat.clarify.dismiss"

#: What each idempotent outcome tells the caller, beside the outcomes so a new one ships with one.
_NEXT_EXPECTED = {
    "dismissed": "the chat no longer waits for an answer; the agent's next turn here is told",
    "already_dismissed": "nothing to do; the question was already dismissed",
    "already_answered": "nothing to do; a turn in this chat already answered the question",
    "unknown_ticket": "nothing to do; no question with this token is waiting (it may have been swept)",
}


def _refusal(error_kind: str, error: str, **fields: Any) -> dict:
    return {"ok": False, "capability_id": CLARIFY_DISMISS_CAPABILITY, "error_kind": error_kind,
            "error": error, **fields}


def dismiss_clarify_question(*, session_id: Any, clarify_token: Any, client_scope: Any = None) -> dict:
    """The verb's row. Refusals (``error_kind``): ``invalid_request``, ``foreign_chat_session``
    (the ticket belongs to another chat, or the chat to another ``client_scope``),
    ``clarify_store_unavailable``. Success carries ``outcome``: ``dismissed``,
    ``already_dismissed``, ``already_answered`` or ``unknown_ticket``."""
    from ..conversation_access import validate_conversation_access
    from ..conversation_owner import ConversationOwnerError
    from ..mission_chat_outcome import ChatErrorKind
    from ..persona_assignments import safe_assignment_text
    from ..persona_chat_continuity.clarify_tickets import DISMISS_FOREIGN_CHAT, PersonaChatClarifyTicketStore

    session = safe_assignment_text(session_id, limit=240)
    token = safe_assignment_text(clarify_token, limit=240)
    if not session or not token:
        return _refusal(ChatErrorKind.INVALID_REQUEST, "session_id and clarify_token are required")
    if client_scope is not None:
        try:
            # MUTATION: skip this check and test_a_scoped_caller_cannot_dismiss_in_another_scopes_chat reddens.
            validate_conversation_access({"session_id": session, "client_scope": client_scope})
        except ConversationOwnerError as exc:
            return _refusal(ChatErrorKind.FOREIGN_CHAT_SESSION, "chat root is not owned by this client scope",
                            session_id=session, reason=exc.reason)
    try:
        outcome, record = PersonaChatClarifyTicketStore().dismiss(token, chat_session_id=session)
    except OSError as exc:
        return _refusal("clarify_store_unavailable", safe_assignment_text(str(exc), limit=320) or "write failed",
                        session_id=session, clarify_token=token)
    if outcome == DISMISS_FOREIGN_CHAT:
        return _refusal(ChatErrorKind.FOREIGN_CHAT_SESSION, "this question was asked in another chat",
                        session_id=session, clarify_token=token)
    logger.info("clarify_dismiss session=%s token=%s outcome=%s", session, token, outcome)
    return {
        "ok": True,
        "capability_id": CLARIFY_DISMISS_CAPABILITY,
        "outcome": outcome,
        "dismissed": outcome == "dismissed",
        "session_id": session,
        "clarify_token": token,
        "state": (record or {}).get("state"),
        "dismissed_at": (record or {}).get("dismissed_at"),
        "next_expected": _NEXT_EXPECTED[outcome],
    }
