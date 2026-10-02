"""Read-only native session capabilities; no session activation or execution."""
import json

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_session_inspection import inspect_operator_settings, inspect_operator_skills
from agent_runtime.skill_inspection import SkillInspectionError
from .protocol import DEFERRED, RpcContext, deferred_reply, err, ok
from .registry import method

__layer__ = "lanes"


def _inspect_reply(rid, params, inspect):
    try:
        result = inspect(params)
        if len(json.dumps(result, ensure_ascii=True)) > 900 * 1024:
            return err(rid, 4130, "This information is too large to display.",
                       {"reason": "response_too_large"})
        return ok(rid, result)
    except (OperatorConversationRefused, SkillInspectionError) as exc:
        return err(rid, 4090, "This conversation's information is unavailable.",
                   {"reason": exc.reason})
    except Exception as exc:
        return err(rid, 4090, "This conversation's information could not be read.",
                   {"reason": "inspection_failed", "error_class": type(exc).__name__})


def _inspect_off_reader(rid, params, context, operation, inspect):
    build = deferred_reply(rid, operation, lambda: _inspect_reply(rid, params, inspect))
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


@method("runtime.operator.conversation.settings", tier=TIER_CONSOLE)
def settings(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.settings",
                               inspect_operator_settings)


@method("runtime.operator.conversation.skills", tier=TIER_CONSOLE)
def skills(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.skills",
                               inspect_operator_skills)
