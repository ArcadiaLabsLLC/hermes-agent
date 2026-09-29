"""Observation and continuation of an existing operator conversation."""
from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn
from agent_runtime.operator_conversation import (
    OperatorConversationRefused, read_operator_conversation,
)
from .protocol import DEFERRED, RpcContext, deferred_reply, err, ok
from .registry import method

__layer__ = "lanes"


@method("runtime.operator.conversation.read", tier=TIER_READ)
def read(rid, params: dict, context: RpcContext | None = None) -> dict:
    build = deferred_reply(rid, "runtime.operator.conversation.read", lambda: _read(rid, params))
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


def _read(rid, params: dict) -> dict:
    try:
        return ok(rid, read_operator_conversation(params))
    except OperatorConversationRefused as exc:
        return err(rid, 4090, "This conversation could not be attached.", {"reason": exc.reason})


@method("runtime.operator.conversation.message", tier=TIER_CONSOLE)
def message(rid, params: dict, context: RpcContext | None = None) -> dict:
    try:
        read_operator_conversation(params)
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
