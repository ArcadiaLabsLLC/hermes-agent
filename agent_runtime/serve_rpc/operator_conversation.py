"""Observation and continuation of an existing operator conversation."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn
from agent_runtime.operator_conversation import (
    OperatorConversationRefused, read_operator_conversation,
    validate_operator_conversation,
)
from agent_runtime.operator_execution import execution_status, stop_operator_execution
from agent_runtime.chat_turn_reservations import ChatTurnReservationError
from .protocol import DEFERRED, RpcContext, deferred_reply, err, ok
from .registry import method

__layer__ = "lanes"


@method("runtime.operator.conversation.read", tier=TIER_CONSOLE)
def read(rid, params: dict, context: RpcContext | None = None) -> dict:
    build = deferred_reply(rid, "runtime.operator.conversation.read", lambda: _read_reply(rid, params, context))
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


def _read_reply(rid, params: dict, context: RpcContext | None) -> dict:
    try:
        return ok(rid, read_operator_conversation(params,
                  can_interrupt=context is not None and context.interrupt_operator is not None))
    except (OperatorConversationRefused, ChatTurnReservationError) as exc:
        reason = exc.reason if isinstance(exc, OperatorConversationRefused) else exc.code
        return err(rid, 4090, "This conversation could not be attached.", {"reason": reason})


@method("runtime.operator.conversation.message", tier=TIER_CONSOLE)
def message(rid, params: dict, context: RpcContext | None = None) -> dict:
    try:
        validate_operator_conversation(params)
    except OperatorConversationRefused as exc:
        return err(rid, 4090, "The conversation changed. Nothing was sent.", {"reason": exc.reason})
    # Never accept a request to replace the conversation behind the attachment.
    if params.get("new_session") or params.get("kill_active"):
        return err(rid, -32602, "An attachment cannot replace its conversation.", {"reason": "replace_not_allowed"})
    outcome = perform_chat_turn(params, verb=CHAT_MESSAGE_METHOD,
                                spawn=None if context is None else context.spawn_chat_turn)
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)


@method("runtime.operator.conversation.stop", tier=TIER_CONSOLE)
def stop(rid, params: dict, context: RpcContext | None = None) -> dict:
    if context is None or context.interrupt_operator is None:
        return err(rid, 4090, "Stop is unavailable on this connection.", {"reason": "control_unavailable"})
    try:
        validate_operator_conversation(params)
        return ok(rid, stop_operator_execution(params["session_id"], params.get("turn_request_id"),
                                               context.interrupt_operator))
    except (OperatorConversationRefused, ChatTurnReservationError) as exc:
        reason = exc.reason if isinstance(exc, OperatorConversationRefused) else exc.code
        return err(rid, 4090, "This turn could not be stopped.", {"reason": reason})


@method("runtime.operator.conversation.status", tier=TIER_CONSOLE)
def status(rid, params: dict, context: RpcContext | None = None) -> dict:
    """Read the named execution receipt without loading its transcript or stopping it."""
    try:
        validate_operator_conversation(params)
        return ok(rid, execution_status(params["session_id"], params.get("turn_request_id")))
    except (OperatorConversationRefused, ChatTurnReservationError) as exc:
        reason = exc.reason if isinstance(exc, OperatorConversationRefused) else exc.code
        return err(rid, 4090, "This turn's status could not be read.", {"reason": reason})
