"""The operator-authorized native conversation directory."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.conversation_owner import ConversationOwnerError
from agent_runtime.instance_history import InstanceHistoryRefused, list_instance_conversations
from .protocol import RpcContext, defer_or_inline, err, ok
from .registry import method

__layer__ = "lanes"


@method("runtime.operator.conversation.list", tier=TIER_CONSOLE)
def list_conversations(rid, params: dict, context: RpcContext | None = None):
    return defer_or_inline(rid, "runtime.operator.conversation.list", context, lambda: _list_reply(rid, params))


def _list_reply(rid, params):
    try:
        return ok(rid, list_instance_conversations(params))
    except (InstanceHistoryRefused, ConversationOwnerError) as exc:
        return err(rid, 4090, "Conversations could not be loaded.", {"reason": str(exc)})
