"""Exact operator-chat attachment; existing stores remain authoritative."""
from __future__ import annotations

from typing import Any

from agent_runtime import paths
from agent_runtime.gateway_identity import read_install_identity
from agent_runtime.persona_assignments import (
    PersonaInstanceStore, resolve_default_chat_session_id_for_instance,
)
from agent_runtime.persona_chat_history.messages import existing_persona_chat_messages
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_records
from agent_runtime.mission_chat_turns.states import (
    INFLIGHT_TURN_STATES, SETTLING_TURN_STATES,
)
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.workspace_scope import effective_workspace_id
from agent_runtime.chat_turn_reservations import reserve_chat_turn, unsettled_chat_receipts
from agent_runtime.operator_execution import execution_status
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
from tools.agent_chat.lane import session_belongs_to_chat_lane
from agent_runtime.serde import safe_assignment_token
from agent_runtime.conversation_owner import ConversationOwnerError, request_client_scope

__layer__ = "lanes"


class OperatorConversationRefused(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def exact_operator_target(params: dict[str, Any]):
    """Resolve an explicit reference without selecting, minting or rebinding."""
    try:
        request_client_scope(params)
    except ConversationOwnerError as exc:
        raise OperatorConversationRefused(exc.reason) from exc
    keys = ("install_id", "persona_id", "persona_instance_id", "session_id")
    if any(not isinstance(params.get(key), str) or not params[key].strip() for key in keys):
        raise OperatorConversationRefused("conversation_identity_required")
    for key in ("workspace_id", "persona_instance_id"):
        if key == "workspace_id" and params.get(key) is None:
            continue
        if safe_assignment_token(params[key]) != params[key]:
            raise OperatorConversationRefused("conversation_identity_invalid")
    if read_install_identity(paths.store_root()).install_id != params["install_id"]:
        raise OperatorConversationRefused("installation_changed")
    store = PersonaInstanceStore()
    instance = store.get(params["persona_instance_id"])
    if instance.id != params["persona_instance_id"] or instance.persona_id != params["persona_id"]:
        raise OperatorConversationRefused("agent_changed")
    if effective_workspace_id(instance, active_workspace_id=None) != params.get("workspace_id"):
        raise OperatorConversationRefused("workspace_changed")
    if store.retired_instance_archive_path(instance.id, persona_id=instance.persona_id) is not None:
        raise OperatorConversationRefused("agent_retired")
    default = resolve_default_chat_session_id_for_instance(
        store, persona_id=instance.persona_id, persona_instance_id=instance.id)
    if not session_belongs_to_chat_lane(params["session_id"], handle=instance.id, default_session=default):
        raise OperatorConversationRefused("foreign_session")
    return instance


def read_operator_conversation(params: dict[str, Any], *, can_interrupt: bool = False) -> dict[str, Any]:
    instance = exact_operator_target(params)
    session = params["session_id"]
    history = existing_persona_chat_messages(session_id=session, before=params.get("before"),
                                             client_scope=params.get("client_scope"))
    if not history.get("ok"):
        raise OperatorConversationRefused(str(history.get("error_kind") or "history_unavailable"))
    turns = mission_chat_turn_records(session_id=session)
    active = [turn for turn in turns if turn["state"] in INFLIGHT_TURN_STATES | SETTLING_TURN_STATES]
    ticket = PersonaChatClarifyTicketStore().open_ticket_for_session(session)
    requested = params.get("turn_request_id")
    receipt = None
    if requested is not None:
        with reserve_chat_turn(turn_request_id=requested, verb=CHAT_MESSAGE_METHOD,
                               session_scope=session) as reservation:
            receipt = reservation.record.state
    recorded = any(turn["client_message_id"] == requested for turn in turns)
    journal_ids = {turn["client_message_id"] for turn in turns}
    queued = [record.ack["turn_request_id"] for record in unsettled_chat_receipts(session)
              if record.verb == CHAT_MESSAGE_METHOD and record.ack["turn_request_id"] not in journal_ids]
    execution_ids = list(dict.fromkeys([turn["client_message_id"] for turn in active] + queued))
    return {
        **history,
        "install_id": params["install_id"],
        "workspace_id": params.get("workspace_id"),
        "persona_id": instance.persona_id,
        "persona_instance_id": instance.id,
        "display_name": instance.display_name,
        "active_turns": active,
        "clarify_token": ticket.get("clarify_token") if ticket else None,
        "delivery_observed": recorded or receipt == "settled",
        "delivery_pending": receipt == "accepted" and not recorded,
        "executions": [execution_status(session, key) for key in execution_ids],
        "requested_execution": execution_status(session, requested) if requested else None,
        "can_interrupt": can_interrupt,
        "capabilities": {"skills": True, "settings": True},
    }


def validate_operator_conversation(params: dict[str, Any]) -> None:
    """Control-path validation must not scan transcript or admission history."""
    exact_operator_target(params)
    history = existing_persona_chat_messages(session_id=params["session_id"], check_only=True,
                                             client_scope=params.get("client_scope"))
    if not history.get("ok"):
        raise OperatorConversationRefused(str(history.get("error_kind") or "history_unavailable"))
