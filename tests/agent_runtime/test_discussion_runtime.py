"""Native room execution with real SQLite/session/journal state and deterministic turns.

The provider boundary is injected; room policy, workers, attempts, recovery,
leases, definitions and commands are the production implementations.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent_runtime.auxiliary_chat import is_auxiliary_chat
from agent_runtime.discussions.native import NativeContext
from agent_runtime.discussions.run_store import DiscussionError
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.discussions.definitions import DefinitionError, ParticipantRef
from agent_runtime.discussions.rpc import execute
from agent_runtime.mission_chat_turns import transition_mission_chat_turn, MissionChatTurnPersistOutcome
from gateway import hosted_rooms
from hermes_constants import get_hermes_head_home
from tests.agent_runtime.test_discussion_definitions import table_value

pytestmark = pytest.mark.timeout(180)


class ExecutionContext(NativeContext):
    def __init__(self, tmp_path):
        self.calls = []
        self.hold = threading.Event()
        self.entered = threading.Event()
        self.lose_callback = False
        self.clarify = False
        self.failure = False
        self.missing = set()
        self.profile = "shared"
        super().__init__(tmp_path / "runtime", tmp_path / "home", "install_A", invoke=self.model)

    def workspace(self, workspace_id):
        if workspace_id != "ws":
            raise DiscussionError("workspace_not_found")
        return SimpleNamespace(id="ws", archived=False)

    def resolve(self, ref, workspace_id):
        self.workspace(workspace_id)
        if ref.instance_id in self.missing:
            raise DiscussionError("instance_retired")
        if ref.install_id != self.install_id:
            raise DiscussionError("remote_members_not_supported")
        return {**ref.to_dict(), "persona_id": "shared_persona", "profile": self.profile, "display_name": "Same name"}

    def roster(self, workspace_id):
        return [{**self.resolve(ParticipantRef("install_A", f"personainst_{i}"), workspace_id), "available": True, "reason": None} for i in range(12)]

    def model(self, args):
        assert is_auxiliary_chat(args.persona_instance_id, args.session_id)
        assert get_hermes_head_home().resolve() == self.home
        self.calls.append(args)
        self.entered.set()
        if self.hold.is_set():
            from agent.interrupt_scope import track_in_interrupt_scope
            scope = SimpleNamespace(reason=None)
            def interrupted(message=None):
                scope.reason = message or "stopped"
            agent = SimpleNamespace(interrupt=interrupted)
            with track_in_interrupt_scope(agent):
                while self.hold.is_set() and scope.reason is None:
                    time.sleep(.01)
        else:
            scope = None
        metadata = {"root_chat_session_id": args.session_id}
        for state in ("pending", "executing"):
            assert transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
                turn_id=args.client_message_id, state=state, metadata=metadata) == MissionChatTurnPersistOutcome.PERSISTED
        if self.failure or (scope is not None and scope.reason):
            state = "interrupted" if scope is not None and scope.reason else "failed"
            transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
                turn_id=args.client_message_id, state=state, metadata=metadata)
            return 1
        first = sum(call.session_id == args.session_id for call in self.calls) == 1
        question = {"question": "Which option?", "choices": ["A", "B"]} if self.clarify and first else None
        metadata.update(native_committed=True, stored_reply="Need your choice" if question else "A considered reply.",
                        auxiliary_result={"clarify": question})
        assert transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
            turn_id=args.client_message_id, state="native_committed", metadata=metadata) == MissionChatTurnPersistOutcome.PERSISTED
        if self.lose_callback:
            raise RuntimeError("transport vanished after native commit")
        args.payload_sink({"ok": True, "reply": metadata["stored_reply"]})
        return 0


@pytest.fixture
def engine(tmp_path):
    context = ExecutionContext(tmp_path)
    service = DiscussionService(context, active_poll_interval=.02)
    service.start()
    yield service, context
    context.hold.clear()
    service.close()


def wait_until(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.02)
    raise AssertionError("condition did not become true")


def begin(service, count=2, key="start", table="table"):
    value = table_value(count)
    value["configuration"]["settings"]["allow_invitations"] = True
    saved = service.definitions.save_table("ws", table, value, expect_revision=0)
    return service.begin("ws", table, expect_revision=saved.revision, key=key, topic="Review the design", actor_id="operator")


def command(service, run, op, **body):
    view = service.view("ws", run["run_id"])
    return service.command("ws", run["run_id"], op, key=f"{op}-{view['run']['revision']}",
                           expect_revision=view["run"]["revision"], body=body, actor_id="operator")


def settled(service, run):
    view = service.view("ws", run["run_id"])
    return view if any(e["kind"] == "room.activity" for e in view["log"]["events"]) else None


def test_twelve_same_profile_instances_run_distinct_sessions_and_end_retains_history(engine):
    service, ctx = engine
    run = begin(service, 12)
    view = wait_until(lambda: settled(service, run))
    assert len(ctx.calls) == 12
    assert len({a.session_id for a in ctx.calls}) == 12
    assert len({a.persona_instance_id for a in ctx.calls}) == 12
    assert all(len(a.message.encode()) <= 12000 for a in ctx.calls)
    public = [e for e in view["log"]["events"] if e["kind"] == "message.member"]
    assert len(public) == 12
    assert len({e["payload"]["member_id"] for e in public}) == 12
    command(service, run, "end")
    ended = wait_until(lambda: (v if (v := service.view("ws", run["run_id"]))["run"]["phase"] == "ended" else None))
    hosted_rooms.prune_disbanded_rooms(service.db_path, now=time.time() + 365 * 86400)
    assert len([e for e in service.view("ws", run["run_id"])["log"]["events"] if e["kind"] == "message.member"]) == 12
    # End released both definition edit and embodied-instance claims.
    table = service.definitions.get("table", "ws", "table")
    updated = service.definitions.save_table("ws", "table", table.spec, expect_revision=table.revision)
    second = service.begin("ws", "table", expect_revision=updated.revision, key="new-topic", topic="New topic", actor_id="operator")
    assert second["run_id"] != run["run_id"]
    wait_until(lambda: settled(service, second))
    assert len(ctx.calls) == 24
    assert len({a.session_id for a in ctx.calls}) == 24


def test_start_replay_and_busy_edit_are_transactional(engine):
    service, ctx = engine
    run = begin(service)
    replay = service.begin("ws", "table", expect_revision=1, key="start", topic="Review the design", actor_id="operator")
    assert replay["run_id"] == run["run_id"]
    with pytest.raises(DiscussionError, match="idempotency conflict"):
        service.begin("ws", "table", expect_revision=1, key="start", topic="DIFFERENT", actor_id="operator")
    with pytest.raises(DefinitionError, match="table_busy"):
        service.definitions.save_table("ws", "table", table_value(), expect_revision=1)
    with pytest.raises(DefinitionError, match="table_busy"):
        service.definitions.delete("table", "ws", "table", expect_revision=1)
    wait_until(lambda: settled(service, run))
    assert len(ctx.calls) == 2


def test_two_tables_cannot_claim_one_embodied_instance(engine):
    service, ctx = engine
    for name in ("left", "right"):
        service.definitions.save_table("ws", name, table_value(), expect_revision=0)
    def submit(name):
        try:
            return service.begin("ws", name, expect_revision=1, key=name, topic="Go", actor_id="operator")["run_id"]
        except DiscussionError as exc:
            return exc.reason
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(submit, ("left", "right")))
    assert result.count("instance_busy") == 1
    assert len(service.runs.list("ws")) == 1
    run = service.runs.list("ws")[0]
    wait_until(lambda: settled(service, run))


def test_lost_callback_after_commit_never_reexecutes_native_turn(engine):
    service, ctx = engine
    ctx.lose_callback = True
    run = begin(service)
    wait_until(lambda: settled(service, run))
    assert len(ctx.calls) == 2
    for _ in range(3):
        service.prepare(service.bindings()[0])
    assert len(ctx.calls) == 2
    assert all(t["status"] == "settled" for t in service.view("ws", run["run_id"])["tasks"])


def test_clarification_resumes_same_member_session_with_fresh_turn_identity(engine):
    service, ctx = engine
    ctx.clarify = True
    run = begin(service)
    question = wait_until(lambda: next((t for t in service.view("ws", run["run_id"])["tasks"] if t["question"]), None))
    first = ctx.calls[0]
    command(service, run, "answer", task_id=question["task_id"], generation=question["generation"], native_id=question["native_id"], answer="A")
    wait_until(lambda: len(ctx.calls) >= 2)
    assert ctx.calls[1].session_id == first.session_id
    assert ctx.calls[1].client_message_id != first.client_message_id
    assert ctx.calls[1].message == "A"
    other = wait_until(lambda: next((t for t in service.view("ws", run["run_id"])["tasks"] if t["question"] and t["task_id"] != question["task_id"]), None))
    command(service, run, "answer", task_id=other["task_id"], generation=other["generation"], native_id=other["native_id"], answer="B")
    view = wait_until(lambda: settled(service, run))
    assert len(ctx.calls) == 4
    assert all(t["status"] == "settled" for t in view["tasks"])


def test_missing_member_refuses_start_without_claims_or_model_calls(engine):
    service, ctx = engine
    ctx.missing.add("personainst_1")
    with pytest.raises(DiscussionError, match="instance retired"):
        begin(service)
    assert not service.runs.list("ws")
    assert not ctx.calls
    # Positive control: a retry with the same key works once admission is legal.
    ctx.missing.clear()
    run = service.begin("ws", "table", expect_revision=1, key="start", topic="Review the design", actor_id="operator")
    wait_until(lambda: settled(service, run))


def test_stop_is_exact_and_end_waits_for_turn_exit(engine):
    service, ctx = engine
    ctx.hold.set()
    run = begin(service)
    assert ctx.entered.wait(10)
    command(service, run, "end")
    ended = wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "ended")
    assert ended
    assert len(ctx.calls) == 1  # Unstarted second member never ran.
    assert not service.turns._live


def test_wire_shapes_validate_and_produce_real_authoring_response(engine):
    service, _ctx = engine
    record = execute(service, "table.save", {"workspace_id": "ws", "table_id": "table", "expect_revision": 0, "spec": table_value()}, actor_id="operator")["record"]
    assert record["seat_plan"]["capacity"] == 2
    assert len(record["seat_plan"]["assignments"]) == 2
    for payload in ({"workspace_id": "ws", "caller": "admin"}, {"workspace_id": "ws", "limit": True}):
        with pytest.raises(DefinitionError):
            execute(service, "table.list", payload, actor_id="operator")
    assert execute(service, "capabilities", {}, actor_id="operator")["accepting"] is True
