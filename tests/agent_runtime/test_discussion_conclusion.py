"""An optional conclusion uses the existing worker, journal and cancellation."""
from dataclasses import replace

import pytest

from agent_runtime.discussions.definitions import DefinitionError
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.mission_chat_turns import transition_mission_chat_turn
from tests.agent_runtime.test_discussion_runtime import engine, wait_until, settled, command
from tests.agent_runtime.test_native_discussion_room import spec

pytestmark = pytest.mark.timeout(90)


def start(service, *, enabled=True, rounds=1):
    value = spec(2)
    settings = replace(value.settings, rounds=rounds, synthesize=enabled, moderator=value.participants[0])
    return service.begin_room("ws", replace(value, settings=settings), key="conclude",
                              topic="Review the design", actor_id="operator")


@pytest.mark.parametrize("enabled,expected", [(False, 2), (True, 3)])
@pytest.mark.parametrize("rounds", [1, 3])
def test_conclusion_is_opt_in_and_exactly_once_across_reconstruction(engine, enabled, expected, rounds):
    service, ctx = engine
    ctx.lose_callback = True
    run = start(service, enabled=enabled, rounds=rounds)
    view = wait_until(lambda: settled(service, run))
    assert len(ctx.calls) == expected
    if enabled:
        assert "scheduled final synthesis" in ctx.calls[-1].message
        assert "Review the design" in ctx.calls[-1].message
        assert ctx.calls[-1].session_id == ctx.calls[0].session_id
        assert ctx.calls[-1].client_message_id != ctx.calls[0].client_message_id
        assert view["log"]["events"][-1]["payload"]["reason_code"] == "conclusion_completed"
    service.close()
    restored = DiscussionService(ctx, active_poll_interval=.02)
    try:
        restored.start()
        restored.prepare(restored.bindings()[0])
        assert len(ctx.calls) == expected
        assert restored.view("ws", run["run_id"])["log"]["events"] == view["log"]["events"]
    finally:
        restored.close()


@pytest.mark.parametrize("outcome", ["failure", "stop"])
def test_conclusion_failure_and_confirmed_stop_keep_public_history(engine, outcome):
    service, ctx = engine
    def invoke(args):
        if "scheduled final synthesis" in args.message:
            ctx.failure = outcome == "failure"
            if outcome == "stop":
                ctx.hold.set()
        return ctx.model(args)
    ctx.invoke = invoke
    run = start(service)
    if outcome == "failure":
        view = wait_until(lambda: settled(service, run))
        assert view["log"]["events"][-1]["payload"]["reason_code"] == "conclusion_failed"
    else:
        wait_until(lambda: len(ctx.calls) == 3)
        view = service.view("ws", run["run_id"])
        task = next(t for t in view["tasks"] if t["status"] == "running")
        assert task["round_index"] == 1
        assert task["source_event_seq"] >= 1
        command(service, run, "stop")
        wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "paused")
        view = service.view("ws", run["run_id"])
        assert not service.turns._live
    assert len([e for e in view["log"]["events"] if e["kind"] == "message.member"]) == 2
    assert len(ctx.calls) == 3


def test_conclusion_requires_an_explicit_member():
    value = spec(2).to_dict()
    value["settings"]["moderator"] = None
    value["settings"]["synthesize"] = True
    with pytest.raises(DefinitionError, match="moderator_required"):
        type(spec(2)).parse(value)


def test_conclusion_approval_survives_owner_reconstruction_and_answers_exact_turn(engine):
    service, ctx = engine
    def invoke(args):
        if "scheduled final synthesis" not in args.message:
            return ctx.model(args)
        ctx.calls.append(args)
        metadata = {"root_chat_session_id": args.session_id}
        for state in ("pending", "executing"):
            transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
                turn_id=args.client_message_id, state=state, metadata=metadata)
        metadata.update(native_committed=True, stored_reply="Choose a conclusion format.",
            auxiliary_result={"clarify": {"question": "Brief or detailed?", "choices": ["Brief", "Detailed"]}})
        transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
            turn_id=args.client_message_id, state="native_committed", metadata=metadata)
        args.payload_sink({"ok": True, "reply": metadata["stored_reply"]})
        return 0
    ctx.invoke = invoke
    run = start(service)
    question = wait_until(lambda: next((t for t in service.view("ws", run["run_id"])["tasks"] if t["question"]), None))
    assert len(ctx.calls) == 3
    original = ctx.calls[-1]
    service.close()
    restored = DiscussionService(ctx, active_poll_interval=.02)
    try:
        restored.start()
        recovered = next(t for t in restored.view("ws", run["run_id"])["tasks"] if t["question"])
        assert recovered["native_id"] == question["native_id"]
        assert recovered["question"]["question"] == "Brief or detailed?"
        assert len(ctx.calls) == 3
        command(restored, run, "answer", task_id=recovered["task_id"], generation=recovered["generation"],
                native_id=recovered["native_id"], answer="Brief")
        view = wait_until(lambda: settled(restored, run))
        assert len(ctx.calls) == 4
        assert ctx.calls[-1].message == "Brief"
        assert ctx.calls[-1].session_id == original.session_id
        assert view["log"]["events"][-1]["payload"]["reason_code"] == "conclusion_completed"
    finally:
        restored.close()


def test_stop_before_conclusion_does_not_schedule_it(engine):
    service, ctx = engine
    ctx.hold.set()
    run = start(service)
    assert ctx.entered.wait(10)
    command(service, run, "stop")
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "paused")
    service.prepare(service.bindings()[0])
    assert len(ctx.calls) == 1
