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
    if "group" not in run["initial"]:
        raise DiscussionError("group_models_unsupported")
    if not service.accepting or run["phase"] not in {"open", "paused"}:
        raise DiscussionError("runtime_stopping")
    member = next((m for m in service.runs.members(run["run_id"])
                   if m["member_id"] == params["member_id"] and m["status"] == "active"), None)
    if member is None:
        raise DiscussionError("member_not_found")
    conversations = service.executions.profiles.turns.conversations()
    scope, facts = open_member(conversations, run, member)
    if select:
        facts = conversations.select_model(scope, member["session_id"], params["model_id"],
                                            save_default=params.get("save_default", False))
    return {"member_id": member["member_id"], "facts": facts}
