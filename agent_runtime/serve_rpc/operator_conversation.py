"""Observation and continuation of an existing operator conversation."""
from agent_runtime.call_authorization import (
    CALLER_COMPUTER,
    COMPUTER_GRANT_ACCOUNT,
    COMPUTER_REACH_CHAT,
    TIER_CONSOLE,
)
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn
from agent_runtime.operator_conversation import (
    OperatorConversationRefused, read_operator_conversation,
    validate_operator_conversation,
)
from agent_runtime.operator_execution import execution_status, stop_operator_execution
from agent_runtime.chat_turn_reservations import ChatTurnReservationError
from .protocol import RpcContext, defer_or_inline, err, ok
from .registry import method

__layer__ = "lanes"


# The Agent Console's attach read of the chat this computer started, at Run chats, never Look: it answers
# a turn's clarify token and execution ids, which only a chat verb can use, and it REQUIRES the
# computer's own client_scope (below), so it opens only chats that scope owns
# (RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT, review w1122b.5).
@method("runtime.operator.conversation.read", tier=TIER_CONSOLE, computer=COMPUTER_REACH_CHAT)
def read(rid, params: dict, context: RpcContext | None = None) -> dict:
    if _computer_without_its_scope(params, context):
        return err(rid, 4090, "This conversation could not be attached.", {"reason": "client_scope_required"})
    return defer_or_inline(rid, "runtime.operator.conversation.read", context, lambda: _read_operator_reply(rid, params, context))


def _computer_without_its_scope(params: dict, context: RpcContext | None) -> bool:
    """A computer driving this phone below the account grant names its own ``client_scope``.

    An absent ``client_scope`` is the unscoped operator path, which reads every chat on the
    phone (``conversation_owner.require_session_owner``); the desktop operator keeps it, a
    computer at Run chats never takes it. With its scope it opens only the chats it started,
    and the phone owner's answer ``conversation_owner_changed`` (review w1122b.5,
    RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT). The
    account grant is answered as a paired console device, so it is not asked.
    """

    caller = context.caller if context is not None else None
    if caller is None or caller.kind != CALLER_COMPUTER or caller.computer_grant == COMPUTER_GRANT_ACCOUNT:
        return False
    # MUTATION: return False here and test_operator_conversation_attachment's computer test reads
    # the phone owner's unscoped chat with no client_scope.
    return params.get("client_scope") is None


def _read_operator_reply(rid, params: dict, context: RpcContext | None) -> dict:
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
        return ok(rid, stop_operator_execution(params["session_id"], params.get("turn_request_id")))
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
