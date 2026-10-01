"""The operator-authorized native conversation directory."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.conversation_owner import ConversationOwnerError
from agent_runtime.instance_history import InstanceHistoryRefused, list_instance_conversations
from .protocol import DEFERRED, RpcContext, deferred_reply, err, ok
from .registry import method

__layer__ = "lanes"


@method("runtime.operator.conversation.list", tier=TIER_CONSOLE)
def list_conversations(rid, params: dict, context: RpcContext | None = None):
    build = deferred_reply(rid, "runtime.operator.conversation.list", lambda: _list_reply(rid, params))
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


def _list_reply(rid, params):
    try:
        return ok(rid, list_instance_conversations(params))
    except (InstanceHistoryRefused, ConversationOwnerError) as exc:
        return err(rid, 4090, "Conversations could not be loaded.", {"reason": str(exc)})
