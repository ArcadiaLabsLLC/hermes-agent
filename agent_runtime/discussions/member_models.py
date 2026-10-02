"""Group model controls delegate to the exact native conversation owner."""
from __future__ import annotations

from .profile_groups import member_scope
from .run_values import DiscussionError

__layer__ = "lanes"


def open_member(conversations, run, member):
    scope = member_scope(run, member)
    opened = conversations.open(scope, key=run["run_id"], cwd=run["initial"]["group"]["cwd"],
                                expected_home=member["binding"]["home"])
    if opened["session_id"] != member["session_id"]:
        raise DiscussionError("session_binding_mismatch")
    return scope, opened["facts"]


def member_models(service, params, *, select=False):
    run = service.runs.get(params["run_id"], params["workspace_id"])
    if not service.accepting or run["phase"] not in {"open", "paused"}:
        raise DiscussionError("runtime_stopping")
    member = next((m for m in service.runs.members(run["run_id"])
                   if m["member_id"] == params["member_id"] and m["status"] == "active"), None)
    if member is None:
        raise DiscussionError("member_not_found")
    if "group" not in run["initial"]:
        return _instance_models(service, run, member, params, select=select)
    conversations = service.executions.profiles.turns.conversations()
    scope, facts = open_member(conversations, run, member)
    if select:
        facts = conversations.select_model(scope, member["session_id"], params["model_id"],
                                            save_default=params.get("save_default", False))
    return {"member_id": member["member_id"], "facts": facts}


def _instance_models(service, run, member, params, *, select):
    from agent_runtime.operator_conversation import OperatorConversationRefused
    from agent_runtime.operator_session_models import operator_model_facts, select_operator_model
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.workspace_scope import effective_workspace_id

    if select and service.state.unresolved(run["run_id"], member["member_id"]):
        raise DiscussionError("conversation_busy")
    with service.context.scope():
        live = service.context.resolve_member(run, member)
        if any(live[key] != member[key] for key in ("persona_id", "profile")):
            raise DiscussionError("profile_binding_changed")
        instance = PersonaInstanceStore().get(member["instance_id"])
        identity = {
            "install_id": member["install_id"], "persona_id": member["persona_id"],
            "persona_instance_id": member["instance_id"], "session_id": member["session_id"],
            "workspace_id": effective_workspace_id(instance, active_workspace_id=None),
        }
        owner = run["initial"].get("client_scope")
        if owner is not None:
            identity["client_scope"] = owner
        try:
            result = select_operator_model({**identity, "model_id": params["model_id"],
                "scope": "agent_default" if params.get("save_default") else "conversation"
            }) if select else operator_model_facts(identity)
        except OperatorConversationRefused as exc:
            raise DiscussionError(exc.reason) from exc
    return {"member_id": member["member_id"], "facts": result["facts"]}
