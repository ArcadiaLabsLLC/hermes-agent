"""Group model setup reuses native sessions and never resends a failed turn."""
import pytest

from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.conversations.model import ConversationError
from tests.agent_runtime import test_discussion_profile_groups as profile_groups
from tests.agent_runtime.test_discussion_profile_groups import (
    create, act, complete, idle, sends, wait_until,
)

groups = profile_groups.groups
pytestmark = pytest.mark.timeout(90)


def model_call(service, run, member, **values):
    operation = "run.member_model" if values else "run.member_models"
    return execute(service, operation, {
        "workspace_id": run["workspace_id"], "run_id": run["run_id"],
        "client_scope": "account", "member_id": member["member_id"], **values,
    }, actor_id="operator")["facts"]


def test_missing_model_is_independent_and_can_be_fixed_without_resending(groups):
    service, _, factory, _ = groups
    run = create(groups)
    a, b = service.runs.members(run["run_id"])
    facts = model_call(service, run, b)
    worker = factory.workers[0]
    sid = next(iter(worker.models))
    worker.models[sid] = None
    assert model_call(service, run, b)["model_selection_required"]
    assert not sends(factory)
    act(service, run, "send", "first", message="Discuss an idea")
    wait_until(lambda: len(sends(factory)) == 1)
    complete(factory)
    before = wait_until(lambda: idle(service, run, 1))
    failures = [e for e in before["log"]["events"] if e["kind"] == "turn.failed"]
    assert len(failures) == 1 and failures[0]["payload"]["member_id"] == b["member_id"]
    assert failures[0]["payload"]["reason_code"] == "missing_config"
    assert any(e["kind"] == "message.member" and e["payload"]["member_id"] == a["member_id"]
               for e in before["log"]["events"])
    chosen = model_call(service, run, b, model_id='["local","model-b"]')
    assert chosen["current_model_id"] == '["local","model-b"]'
    assert chosen["session_id"] == facts["session_id"] == b["session_id"]
    assert len(sends(factory)) == 1
    assert service.view(run["workspace_id"], run["run_id"])["log"] == before["log"]


def test_group_model_controls_refuse_foreign_scope_member_and_drain(groups):
    service, _, _, _ = groups
    run = create(groups)
    member = service.runs.members(run["run_id"])[0]
    for actor, client in (("other", "account"), ("operator", "other")):
        with pytest.raises(DiscussionError, match="conversation owner changed"):
            execute(service, "run.member_models", {"workspace_id": run["workspace_id"],
                "run_id": run["run_id"], "member_id": member["member_id"], "client_scope": client}, actor_id=actor)
    with pytest.raises(DiscussionError, match="member not found"):
        model_call(service, run, {"member_id": "foreign"})
    service.begin_drain()
    with pytest.raises(DiscussionError, match="runtime stopping"):
        model_call(service, run, member, model_id='["local","model-b"]')


def test_model_choice_keeps_busy_guard_and_peer_selection(groups):
    service, _, factory, _ = groups
    run = create(groups)
    a, b = service.runs.members(run["run_id"])
    original = model_call(service, run, b)
    chosen = model_call(service, run, a, model_id='["local","model-b"]')
    assert chosen["current_model_id"] == '["local","model-b"]'
    assert model_call(service, run, b)["current_model_id"] == original["current_model_id"]
    act(service, run, "send", "working", message="An idea", response={"mode": "compare", "members": []})
    wait_until(lambda: len(sends(factory)) == 2)
    with pytest.raises(ConversationError):
        model_call(service, run, a, model_id='["local","model-a"]')
    assert model_call(service, run, a)["current_model_id"] == chosen["current_model_id"]
    complete(factory)
    wait_until(lambda: idle(service, run, 1))
