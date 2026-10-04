"""``mission-chat turn-resolve`` / ``runtime.chat.turn.resolve`` — settle one ``outcome_unknown`` turn.

The only resolution is ``abandon``: the operator confirms the ambiguous turn is
dead so the next send can carry a new ``client_message_id``. The caller must
name the instance that OWNS the chat root, the turn must be in an
operator-resolvable state with the exact ``turn_id``, and the write runs under
the root's lease — a live turn on the same root refuses ``chat_busy`` rather
than racing it.
"""

from __future__ import annotations

from typing import Any

from ..persona_chat_durability import default_persona_session_db as _default_persona_session_db
from ..persona_chat_session import _persona_chat_session_owner

__layer__ = "lanes"
__all__ = ["TURN_RESOLVE_CAPABILITY", "resolve_chat_turn"]

TURN_RESOLVE_CAPABILITY = "mission.chat.turn.resolve"
_DEFAULT_REASON = "operator requested abandon and resend"


def _refusal(error_kind: str, error: str, **fields: Any) -> dict:
    return {"ok": False, "capability_id": TURN_RESOLVE_CAPABILITY, "error_kind": error_kind, "error": error, **fields}


def _owner_instance_id(session_id: str) -> str | None:
    from ..persona_assignments import PersonaInstanceStore

    try:
        owner_id = _persona_chat_session_owner(_default_persona_session_db(), session_id)
        return PersonaInstanceStore().get(owner_id).id if owner_id else None
    except Exception:
        return None


def _abandon(session_id: str, client_message_id: str, turn_id: str, actor: str, reason: str) -> dict:
    from ..mission_chat_outcome import ChatErrorKind
    from ..mission_chat_turns.journal import abandon_mission_chat_turn
    from ..mission_chat_turns.reads import mission_chat_turn_record
    from ..mission_chat_turns.states import (
        OPERATOR_RESOLVABLE_TURN_STATES, TURN_STATE_ABANDONED, MissionChatTurnPersistOutcome)
    from ..persona_assignments import safe_assignment_token

    record = mission_chat_turn_record(session_id=session_id, client_message_id=client_message_id)
    # The resolvable set is the turn store's own table, never a literal here.
    if (not record or record.get("state") not in OPERATOR_RESOLVABLE_TURN_STATES
            or safe_assignment_token(record.get("turn_id")) != turn_id):
        return _refusal(ChatErrorKind.CHAT_TURN_RESOLUTION_MISMATCH,
                        "resolution requires the exact matching outcome_unknown root/client/turn",
                        session_id=session_id, client_message_id=client_message_id, turn_id=turn_id)
    outcome = abandon_mission_chat_turn(session_id=session_id, client_message_id=client_message_id,
                                        turn_id=turn_id, resolution_actor=actor, resolution_reason=reason)
    return {
        "ok": outcome is MissionChatTurnPersistOutcome.PERSISTED,
        "capability_id": TURN_RESOLVE_CAPABILITY,
        "resolution": "abandon",
        "journal_state": TURN_STATE_ABANDONED,
        "root_chat_session_id": session_id,
        "session_id": session_id,
        "client_message_id": client_message_id,
        "turn_id": turn_id,
        "next_expected": "send again with a new client_message_id",
    }


def resolve_chat_turn(
    *, session_id: Any, client_message_id: Any, turn_id: Any, action: Any,
    persona_instance_id: Any, reason: Any = None,
) -> dict:
    """The verb's row. Refusals (``error_kind``): ``invalid_request``,
    ``foreign_chat_session``, ``chat_busy`` (with ``lease_owner``),
    ``chat_turn_resolution_mismatch``. A journal write that did not persist is
    ``ok: false`` on the success row's shape, as the argv verb has always said."""
    from ..mission_chat_outcome import ChatErrorKind
    from ..persona_assignments import safe_assignment_text, safe_assignment_token
    from ..persona_chat_continuity import PersonaChatBusyError, persona_chat_root_lease

    session = safe_assignment_text(session_id, limit=240)
    client_id = safe_assignment_text(client_message_id, limit=240)
    turn = safe_assignment_token(turn_id)
    instance = safe_assignment_token(persona_instance_id)
    if safe_assignment_token(action) != "abandon" or not instance:
        return _refusal(ChatErrorKind.INVALID_REQUEST, "action=abandon and persona_instance_id are required")
    if _owner_instance_id(session) != instance:
        return _refusal(ChatErrorKind.FOREIGN_CHAT_SESSION, "chat root is not owned by the requested persona instance",
                        session_id=session, persona_instance_id=instance)
    try:
        with persona_chat_root_lease(session, owner_id=instance, observer_kind="turn_resolve"):
            # Asked again under the lease: ownership may have moved while the
            # lease was being taken, and the write must answer to the holder.
            if _owner_instance_id(session) != instance:
                return _refusal(ChatErrorKind.FOREIGN_CHAT_SESSION,
                                "chat root is not owned by the requested persona instance",
                                session_id=session, persona_instance_id=instance)
            return _abandon(session, client_id, turn, instance,
                            safe_assignment_text(reason, limit=320) or _DEFAULT_REASON)
    except PersonaChatBusyError as exc:
        return _refusal(ChatErrorKind.CHAT_BUSY, str(exc), session_id=session, lease_owner=exc.owner)
