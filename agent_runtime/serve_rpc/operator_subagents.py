"""Console-private owned child inspection and commands on the existing lane."""
from functools import partial

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.subagents.model import OPERATIONS, MUTATIONS, Refusal, SubagentError
from agent_runtime.subagents.operator import inspect_operator
from .protocol import DEFERRED, deferred_reply, err, ok
from .registry import method

__layer__ = "lanes"


def _subagent_reply(operation, rid, params):
    try:
        return ok(rid, inspect_operator(operation, params))
    except (OperatorConversationRefused, SubagentError) as exc:
        return err(rid, 4090, "This conversation's subagents are unavailable.", {"reason": exc.reason})
    except Exception:
        reason = Refusal.UNKNOWN if operation in MUTATIONS else Refusal.UNAVAILABLE
        return err(rid, 4090, "Subagent outcome could not be verified.", {"reason": reason})


def _dispatch(operation, rid, params, context=None):
    name = "runtime.operator.conversation.subagents." + operation
    build = deferred_reply(rid, name, lambda: _subagent_reply(operation, rid, params))
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


for _operation in OPERATIONS:
    method("runtime.operator.conversation.subagents." + _operation, tier=TIER_CONSOLE)(
        partial(_dispatch, _operation))
