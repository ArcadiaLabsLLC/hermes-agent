"""Native session capabilities; no session activation or execution."""
import json

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_session_inspection import inspect_operator_settings, inspect_operator_skills
from agent_runtime.operator_session_models import operator_model_facts, operator_selected_model_facts, select_operator_model
from agent_runtime.operator_session_controls import (
    operator_control_facts, operator_approval_facts, set_operator_control, respond_operator_approval,
)
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


@method("runtime.operator.conversation.models", tier=TIER_CONSOLE)
def models(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.models",
                               operator_model_facts)


@method("runtime.operator.conversation.model.facts", tier=TIER_CONSOLE)
def model_facts(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.model.facts",
                               operator_selected_model_facts)


@method("runtime.operator.conversation.model.select", tier=TIER_CONSOLE)
def select_model(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.model.select",
                               select_operator_model)


@method("runtime.operator.conversation.controls", tier=TIER_CONSOLE)
def controls(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.controls", operator_control_facts)


@method("runtime.operator.conversation.control.set", tier=TIER_CONSOLE)
def set_control(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.control.set", set_operator_control)


@method("runtime.operator.conversation.approvals", tier=TIER_CONSOLE)
def approvals(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.approvals", operator_approval_facts)


@method("runtime.operator.conversation.approval.respond", tier=TIER_CONSOLE)
def respond_approval(rid, params: dict, context: RpcContext | None = None):
    return _inspect_off_reader(rid, params, context, "runtime.operator.conversation.approval.respond", respond_operator_approval)
