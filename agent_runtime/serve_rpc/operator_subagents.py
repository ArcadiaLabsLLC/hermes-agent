"""Console-private owned child inspection and commands on the existing lane."""
import logging
from functools import partial

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.subagents.model import OPERATIONS, WRITES, Refusal, SubagentError
from agent_runtime.subagents.operator import inspect_operator
from .protocol import defer_or_inline, err, ok
from .registry import method

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def _subagent_reply(operation, rid, params):
    try:
        return ok(rid, inspect_operator(operation, params))
    except (OperatorConversationRefused, SubagentError) as exc:
        logger.info("subagents.%s refused reason=%s", operation, exc.reason)
        return err(rid, 4090, "This conversation's subagents are unavailable.", {"reason": exc.reason})
    except Exception:
        reason = Refusal.UNKNOWN if operation in WRITES else Refusal.UNAVAILABLE
        # The wire reply is a fixed refusal, so this line is the only trace of what actually failed.
        logger.exception("subagents.%s failed unclassified; replying reason=%s", operation, reason)
        return err(rid, 4090, "Subagent outcome could not be verified.", {"reason": reason})


def _dispatch(operation, rid, params, context=None):
    name = "runtime.operator.conversation.subagents." + operation
    return defer_or_inline(rid, name, context, lambda: _subagent_reply(operation, rid, params))


for _operation in OPERATIONS:
    method("runtime.operator.conversation.subagents." + _operation, tier=TIER_CONSOLE)(
        partial(_dispatch, _operation))
