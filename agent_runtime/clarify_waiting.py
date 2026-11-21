"""Whether a chat's open question still waits for the operator (MC-A-QUESTION-THE-CHAT-MOVED-PAST-STILL-WAITS-FOR-YOUR-ANSWER).

A clarify ticket is settled by the next turn that lands in its own chat
(``hermes_cli/harness_parts/persona/chat_request.py::_settle_mission_chat_clarify_binding``),
so an open ticket is always its chat's newest turn. It was never settled when the operator moved
on in ANOTHER chat with the same agent: seen 2026-11-20, a lead's question asked at 13:14 in one
chat kept Home's "Waiting for your answer" (and every idle check of that chat) six hours after the
owner started a new chat with that agent at 15:30 and worked there.

The rule, read off the runtime's own records and never written: a question has been moved past
when its agent's current chat (``default_chat_session_id``, repointed by every committed turn) is
another chat where a turn somebody sent started after the question was asked. A turn the runtime
delivered there on its own (a helper's answer, a background completion) is not the operator moving
on, so it does not count. The ticket stays open on disk
(answering it still binds); it stops being reported as waiting. Every reader of "is a question
waiting in this chat" asks :func:`waiting_clarify_ticket`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__layer__ = "policy"
__all__ = ["clarify_question_moved_past", "waiting_clarify_ticket"]

#: Turn ids the runtime mints for what it delivers into a chat by itself:
#: ``dispatch_delivery.vocabulary.delivery_client_message_id`` and the background-completion
#: drain (``dispatch_delivery/completions.py``).
_RUNTIME_DELIVERED = ("dispatch-delivery-", "bg-completion-")


def waiting_clarify_ticket(chat_session_id: str | None) -> dict[str, Any] | None:
    """The chat's open ticket while its question still waits, else None."""

    from .persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore

    ticket = PersonaChatClarifyTicketStore().open_ticket_for_session(chat_session_id)
    if ticket is None or clarify_question_moved_past(ticket):
        return None
    return ticket


def clarify_question_moved_past(ticket: dict[str, Any]) -> bool:
    """True when the ticket's agent has since run a turn in another, now current, chat. Fail-safe:
    a record that cannot be read leaves the question waiting."""

    try:
        asked = float(ticket.get("created_at") or 0.0)
        instance_id = str(ticket.get("persona_instance_id") or "")
        if not asked or not instance_id:
            return False
        from .mission_chat_turns.reads import mission_chat_turn_records
        from .persona_assignments import PersonaInstanceStore

        current = str(PersonaInstanceStore().get(instance_id).default_chat_session_id or "")
        if not current or current == str(ticket.get("chat_session_id") or ""):
            return False
        # The journal's own order key: a turn's start, else its settle time (``mission_chat_turn_records``).
        return any(_stamp_seconds(turn.get("started_at") or turn.get("updated_at")) > asked
                   and not str(turn.get("client_message_id") or "").startswith(_RUNTIME_DELIVERED)
                   for turn in mission_chat_turn_records(session_id=current))
    except Exception:
        return False


def _stamp_seconds(stamp: Any) -> float:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
