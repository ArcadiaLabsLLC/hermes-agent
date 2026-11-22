"""The operator-authorized native conversation directory."""
from agent_runtime.call_authorization import (
    COMPUTER_REACH_LOOK, TIER_CONSOLE, authorize_call, is_computer_below_account,
)
from agent_runtime.conversation_owner import ConversationOwnerError, request_client_scope
from agent_runtime.instance_history import (
    CONVERSATION_LIST_METHOD, InstanceHistoryRefused, list_instance_conversations,
)
from .protocol import RpcContext, defer_or_inline, err, ok
from .registry import method, method_computer_reach, method_tier

__layer__ = "lanes"

#: The read a listed row opens through. Whether THIS caller may make it is the front-door gate's
#: own answer for that verb (one owner: a computer's grant allowlist), never a second rule here.
_ROW_READ_METHOD = "runtime.persona.chat.history"


# The phone agent's existing chats, listed so a computer opens them read-only
# (RT-FU-A-LOOK-COMPUTER-LISTS-THE-PHONES-EXISTING-CHATS, owner "rest as reccomended" 2026-11-22).
@method(CONVERSATION_LIST_METHOD, tier=TIER_CONSOLE, computer=COMPUTER_REACH_LOOK)
def list_conversations(rid, params: dict, context: RpcContext | None = None):
    caller = context.caller if context is not None else None
    return defer_or_inline(rid, CONVERSATION_LIST_METHOD, context, lambda: _list_reply(rid, params, caller))


def _list_reply(rid, params, caller=None):
    try:
        named = request_client_scope(params)
        own = _computer_scope(caller)
        # A computer below the account grant lists as the scope its chats are stamped with at dispatch
        # (RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE), whatever scope its request names:
        # its own page is the chats it started, and only those say ``openable``.
        page = list_instance_conversations(params if own is None else {**params, "client_scope": own})
        return ok(rid, _for_caller(page, named, own, caller))
    except (InstanceHistoryRefused, ConversationOwnerError) as exc:
        return err(rid, 4090, "Conversations could not be loaded.", {"reason": str(exc)})


def _computer_scope(caller) -> str | None:
    if not is_computer_below_account(caller):
        return None
    from agent_runtime.reverse_lane.grants import computer_client_scope

    return computer_client_scope(caller.computer_id)


def _for_caller(page: dict, named, own, caller) -> dict:
    """The page as *caller* may see it (review w1122d.1 of RT-FU-A-LOOK-COMPUTER-LISTS-THE-PHONES-EXISTING-CHATS).

    ``readable``: may this caller read the row's transcript (``openable`` says whether it may OPEN it,
    as its owner); a Look computer reads every phone chat, read-only, and opens none it did not start.
    A computer below the account grant (*own* is its grant's scope) is never handed the owning
    ``client_scope`` of a row it does not own; a row it does own answers with the scope its request
    named (*named*, Eternia's account key), so Eternia's own-page check and its Open keep working,
    and the dispatcher stamps the grant's scope back over it on the open.
    """

    readable = row_readable_by(caller)
    for row in page.get("conversations", ()):
        row["readable"] = readable
        if own is None:
            continue
        # MUTATION: drop this pop and test_a_look_computer_lists_every_phone_chat_read_only reddens.
        if row.get("client_scope") != own:
            row.pop("client_scope", None)
        elif named is not None:
            row["client_scope"] = named
    return page


def row_readable_by(caller) -> bool:
    """Whether *caller* may read a listed chat's history: the gate's answer, asked of the gate."""

    # MUTATION: answer True here and test_readable_is_the_gates_answer_for_the_history_read reddens.
    return authorize_call(method_tier(_ROW_READ_METHOD), caller, method=_ROW_READ_METHOD,
                          computer_reach=method_computer_reach(_ROW_READ_METHOD)).ok
