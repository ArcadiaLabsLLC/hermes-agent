"""The RPC, journal and existing native worker honor the same message intent."""
import pytest

from agent_runtime.discussions.contract import validate_params
from agent_runtime.discussions.definitions import DefinitionError
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_store import DiscussionError
from agent_runtime.discussions.room_definition import RoomSpec
from tests.agent_runtime.test_discussion_definitions import table_value
from tests.agent_runtime.test_discussion_runtime import engine, begin, settled, wait_until, command

pytestmark = pytest.mark.timeout(90)


def send(service, run, key, *, response=None):
    current = service.runs.get(run["run_id"])
    params = {"workspace_id": "ws", "run_id": run["run_id"],
        "expect_revision": current["revision"], "idempotency_key": key, "message": "Develop this idea"}
    if response is not None:
        params["response"] = response
    return execute(service, "run.send", params, actor_id="operator")


def test_compare_dispatches_independently_and_replay_does_not_resend(engine):
    service, context = engine
    run = begin(service)
    wait_until(lambda: settled(service, run))
    before = len(context.calls)
    context.hold.set()
    response = {"mode": "compare", "members": []}
    send(service, run, "compare", response=response)
    wait_until(lambda: len(context.calls) == before + 2)
    # Both native turns entered before either was allowed to finish.
    assert len({call.session_id for call in context.calls[before:]}) == 2
    send(service, run, "compare", response=response)
    assert len(context.calls) == before + 2
    with pytest.raises(DiscussionError, match="idempotency conflict"):
        send(service, run, "compare", response={"mode": "discuss", "members": []})
    context.hold.clear()
    view = wait_until(lambda: settled(service, run))
    users = [event for event in view["log"]["events"] if event["kind"] == "message.user"]
    assert users[-1]["payload"]["response"] == response
    assert len(users) == 2
    send(service, run, "continue")
    wait_until(lambda: len(context.calls) == before + 4)
    wait_until(lambda: settled(service, run))
    assert "independent answer" not in context.calls[-1].message


def test_target_is_exact_and_unknown_member_is_refused_before_journaling(engine):
    service, context = engine
    run = begin(service)
    view = wait_until(lambda: settled(service, run))
    member = view["members"][1]
    with pytest.raises(DiscussionError, match="member not found"):
        send(service, run, "foreign", response={"mode": "reply", "members": ["foreign"]})
    assert not any(c["command_key"] == "foreign" for c in service.runs.commands(run["run_id"]))
    before = len(context.calls)
    send(service, run, "target", response={"mode": "reply", "members": [member["member_id"]]})
    wait_until(lambda: len(context.calls) == before + 1)
    wait_until(lambda: settled(service, run))
    assert context.calls[-1].session_id == member["session_id"]
    assert len(context.calls) == before + 1


def test_stop_confirms_all_independent_members_without_stopping_another_room(engine):
    service, context = engine
    run = begin(service)
    wait_until(lambda: settled(service, run))
    config = table_value(4)["configuration"]
    other = service.begin_room("ws", RoomSpec.parse({"name": "Other",
        "participants": config["participants"][2:], "settings": config["settings"]}),
        key="other", topic="Other topic", actor_id="operator")
    wait_until(lambda: settled(service, other))
    before = len(context.calls)
    context.hold.set()
    send(service, run, "compare", response={"mode": "compare", "members": []})
    wait_until(lambda: len(context.calls) == before + 2)
    send(service, other, "keep-working")
    wait_until(lambda: len(context.calls) == before + 3)
    command(service, run, "stop")
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "paused")
    view = service.view("ws", run["run_id"])
    assert all(task["status"] in {"settled", "cancelled"} for task in view["tasks"]), [
        (task["status"], task["error"]) for task in view["tasks"]]
    other_view = service.view("ws", other["run_id"])
    assert other_view["run"]["phase"] == "open"
    assert any(task["status"] == "running" for task in other_view["tasks"])
    context.hold.clear()
    wait_until(lambda: settled(service, other))


@pytest.mark.parametrize("response", [None, {}, {"mode": "reply", "members": []},
    {"mode": "infer", "members": []}, {"mode": "compare", "members": "all"}])
def test_wire_refuses_invalid_message_intent(response):
    with pytest.raises(DefinitionError, match="invalid_response"):
        validate_params("run.send", {"workspace_id": "ws", "run_id": "run", "expect_revision": 1,
            "idempotency_key": "send", "message": "Hi", "response": response})
