"""The operator-authorized native conversation directory."""
from agent_runtime.call_authorization import TIER_CONSOLE, authorize_call
from agent_runtime.conversation_owner import ConversationOwnerError
from agent_runtime.instance_history import (
    CONVERSATION_LIST_METHOD, InstanceHistoryRefused, list_instance_conversations,
)
from .protocol import RpcContext, defer_read, err, ok
from .registry import method, method_tier

__layer__ = "lanes"

#: The read a listed row opens through. Whether THIS caller may make it is the front-door gate's
#: own answer for that verb (one owner), never a second rule here.
_ROW_READ_METHOD = "runtime.persona.chat.history"


# The agent's existing chats (RT-FU-A-LOOK-COMPUTER-LISTS-THE-PHONES-EXISTING-CHATS, owner "rest as
# reccomended" 2026-11-22).
@method(CONVERSATION_LIST_METHOD, tier=TIER_CONSOLE)
def list_conversations(rid, params: dict, context: RpcContext | None = None):
    caller = context.caller if context is not None else None
    return defer_read(rid, CONVERSATION_LIST_METHOD, context, lambda: _list_reply(rid, params, caller))


def _list_reply(rid, params, caller=None):
    try:
        return ok(rid, _for_caller(list_instance_conversations(params), caller))
    except (InstanceHistoryRefused, ConversationOwnerError) as exc:
        return err(rid, 4090, "Conversations could not be loaded.", {"reason": str(exc)})


def _for_caller(page: dict, caller) -> dict:
    """The page as *caller* may see it: ``readable`` says whether this caller may read a row's transcript
    (``openable`` says whether it may OPEN it, as its owner)."""

    readable = row_readable_by(caller)
    for row in page.get("conversations", ()):
        row["readable"] = readable
    return page


def row_readable_by(caller) -> bool:
    """Whether *caller* may read a listed chat's history: the gate's answer, asked of the gate."""

    # MUTATION: answer True here and test_readable_is_the_gates_answer_for_the_history_read reddens.
    return authorize_call(method_tier(_ROW_READ_METHOD), caller, method=_ROW_READ_METHOD).ok
