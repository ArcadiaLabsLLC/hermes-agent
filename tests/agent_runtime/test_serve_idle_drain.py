"""Automatic restart is admitted by the same owners that admit work."""
import io
import threading
from types import SimpleNamespace

import pytest

from agent_runtime.conversations.model import ConversationError, ConversationScope, TurnState
from agent_runtime.conversations.service import ConversationService
from hermes_cli.harness_parts.serve.handle_message import MessageHandling
from hermes_cli.harness_parts.serve.manifest import ops_manifest
from hermes_cli.harness_parts.serve.session import ServeSession
from tests.agent_runtime.conversation_support import WorkerFactory
from tests.agent_runtime.test_discussion_runtime import engine, begin, command, settled, wait_until

__all__ = ["engine"]  # Export the imported pytest fixture for this module's tests.


@pytest.fixture
def rig(tmp_path):
    factory = WorkerFactory()
    owner = ConversationService(tmp_path, "test", profile_home=lambda _: tmp_path, worker_factory=factory)
    scope = ConversationScope("operator", "test", "a")
    sid = owner.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(tmp_path))["session_id"]
    frames = []
    session = ServeSession(io.StringIO(), io.StringIO())
    session.inflight_lock, session.inflight = threading.RLock(), {}
    session.drain_state = None
    session.conversation_owner, session.discussion_owner = owner, None
    session.frames = SimpleNamespace(emit=frames.append)
    session.liveness_stop = threading.Event()
    session.socket_lock = session.socket_server = session.gateway_server = None
    session.boot_id = "boot"
    session._broadcast_lanes = lambda frame: None
    session._drain_monitor = lambda state: None
    yield session, owner, scope, sid, factory.workers[0], frames
    owner.close()


def request(rig, *, connection=None):
    session, *_, frames = rig
    MessageHandling._handle_message(
        session, {"op": "drain_if_idle", "id": "maintenance", "force": True},
        SimpleNamespace(emit=frames.append), connection=connection,
    )
    return frames[-1]


@pytest.mark.parametrize("state", [TurnState.RUNNING, TurnState.UNKNOWN])
def test_native_active_and_uncertain_work_keeps_every_listener_open(rig, state):
    session, owner, scope, sid, worker, _ = rig
    owner.send(scope, sid, "turn", {"text": "hello", "images": []})
    owner.store.settle(sid, "turn", state)
    assert request(rig) == {"event": "drain_deferred", "id": "maintenance", "reason": "busy",
                            "held_by": "conversation_turn"}
    assert session.drain_state is None and not session.liveness_stop.is_set()
    assert owner.capabilities()["accepting"]
    assert session._busy_frame()["work"] == 1
    worker.event("native-0", "message.complete", text="done", status="complete")
    assert request(rig)["event"] == "draining"
    assert not owner.capabilities()["accepting"]
    with pytest.raises(ConversationError, match="runtime_stopping"):
        owner.send(scope, sid, "second", {"text": "must not run", "images": []})
    assert len([m for m, _ in worker.calls if m == "prompt.submit"]) == 1


def _argv(*, chat=False, long_run=False, stream=False):
    return SimpleNamespace(is_chat_turn=chat, is_long_run=long_run, is_runtime_stream=stream)


@pytest.mark.parametrize(("item", "held_by"), [
    (_argv(chat=True), "chat_turn"),
    (_argv(long_run=True), "long_run"),
])
def test_a_running_turn_or_long_run_refuses_with_its_typed_hold(rig, item, held_by):
    session, owner, *_ = rig
    session.inflight["turn"] = item
    session.inflight["read"] = _argv()
    refusal = request(rig)
    assert (refusal["reason"], refusal["held_by"]) == ("busy", held_by)
    assert session.drain_state is None and owner.capabilities()["accepting"]


def test_startup_requests_and_standing_subscriptions_never_defer_the_drain(rig):
    # The request that triggered the launcher's attach, a read, a prewarm: all
    # finish inside the drain, so none of them may refuse it (2026-10-08).
    # MUTATION: count any non-stream request as busy again and this reddens.
    session, owner, *_ = rig
    session.inflight["status"] = _argv()
    session.inflight["console"] = _argv(stream=True)
    reply = request(rig)
    assert reply["event"] == "draining" and reply["request_ids"] == ["console", "status"]
    assert not owner.capabilities()["accepting"]


def test_open_discussion_blocks_maintenance_between_rounds(rig, engine):
    session, owner, *_ = rig
    session.discussion_owner = engine[0]
    begin(engine[0])
    assert (request(rig)["reason"], request(rig)["held_by"]) == ("busy", "discussion")
    assert owner.capabilities()["accepting"]
    assert session._busy_frame()["work"] == 1


def test_paused_native_discussion_allows_update_only_after_every_owner_settles(rig, engine, monkeypatch):
    session, owner, *_ = rig
    service = engine[0]
    session.discussion_owner = service
    run = begin(service)
    wait_until(lambda: settled(service, run))
    command(service, run, "stop")
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "paused")
    assert service.pending_count() == 0
    # Each hold must work alone, including during crash recovery of a paused room.
    with monkeypatch.context() as m:
        m.setattr(service.runs, "pending", lambda *_: [{"command_key": "queued"}])
        assert request(rig)["held_by"] == "discussion"
    with monkeypatch.context() as m:
        m.setattr(service.state, "unresolved", lambda *_: True)
        assert request(rig)["held_by"] == "discussion"
    assert request(rig)["event"] == "draining"
    assert not service.accepting and not owner.capabilities()["accepting"]


def test_unreadable_owner_is_not_idle(rig, monkeypatch):
    session, owner, *_ = rig
    def unreadable():
        raise OSError("unavailable")
    monkeypatch.setattr(owner.store, "unsettled", unreadable)
    refusal = request(rig)
    assert (refusal["reason"], refusal["held_by"]) == ("unavailable", "unreadable")
    assert session.drain_state is None and owner.capabilities()["accepting"]
    assert session._busy_frame()["work"] == 1


def test_idle_claim_and_admission_share_one_lock(rig):
    _, owner, *_ = rig
    entered = threading.Event()
    with owner._lock:
        thread = threading.Thread(target=lambda: (owner.begin_idle_drain(), entered.set()))
        thread.start()
        assert not entered.wait(0.05)
        assert owner.capabilities()["accepting"]
    thread.join(2)
    assert entered.is_set() and not owner.capabilities()["accepting"]


def test_gateway_never_advertises_or_accepts_local_maintenance(rig):
    assert "drain_if_idle" in ops_manifest(transport="socket")["ops"]
    assert "drain_if_idle" not in ops_manifest(transport="gateway")["ops"]
    assert request(rig, connection=SimpleNamespace(transport="gateway"))["error"] == "op_not_available_on_gateway"
    assert rig[0].drain_state is None


def test_a_cron_job_running_in_this_process_holds_the_idle_drain(rig, tmp_path, monkeypatch):
    # RL-20 x cron (audit D4): a manual `cronjob_manage run` finishes on the
    # scheduler's pool after its turn ends; a pull then must not kill it.
    # MUTATION: drop the `_cron_job_hold` call and the first request drains.
    from cron import scheduler

    session, owner, *_ = rig
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    marker = object()
    assert scheduler.try_register_running_job("brief", owner=marker)
    try:
        refusal = request(rig)
        assert (refusal["reason"], refusal["held_by"]) == ("busy", "cron_job")
        assert session.drain_state is None and owner.capabilities()["accepting"]
    finally:
        scheduler.release_running_job("brief", owner=marker)
    assert request(rig)["event"] == "draining"


def test_unreadable_cron_registry_is_not_idle(rig, monkeypatch):
    from cron import scheduler

    session, owner, *_ = rig
    def unreadable():
        raise RuntimeError("registry")
    monkeypatch.setattr(scheduler, "get_running_job_ids", unreadable)
    assert request(rig)["held_by"] == "unreadable"
    assert session.drain_state is None and owner.capabilities()["accepting"]


def test_a_scheduled_turn_on_the_send_queue_holds_the_idle_drain(rig):
    # RT-SCHEDULE-TURN-RUNNING-WORK: a scheduler fire runs on the queued-send runner, outside every
    # turn table, so only its send-queue entry says it exists.
    # MUTATION: drop `_queued_turn_hold()` from `claim_idle_drain` and the first request drains.
    from agent_runtime import chat_root_send_queue as send_queue

    session, owner, *_ = rig
    origin = {send_queue.SCHEDULE_ORIGIN_KEY: "standup", "owner": None}
    send_queue.enqueue("root-sched", "schedule-standup", {send_queue.ORIGIN_ARG: origin, "message": "go"})
    refusal = request(rig)
    assert (refusal["reason"], refusal["held_by"]) == ("busy", "scheduled_turn")
    assert session.drain_state is None and owner.capabilities()["accepting"]
    send_queue.remove("root-sched", "schedule-standup")
    assert request(rig)["event"] == "draining"


def test_a_messaging_turn_on_the_send_queue_holds_the_idle_drain(rig):
    # p10-messaging: a platform message is a queued send on the bound instance's root, run by the
    # queued-send runner outside every turn table; a stale-code restart must not drain under it.
    # MUTATION: drop the MESSAGING_ORIGIN_KEY row from `_QUEUED_TURN_HOLDS` and the first request drains.
    from agent_runtime import chat_root_send_queue as send_queue

    session, owner, *_ = rig
    origin = {"kind": "messaging", send_queue.MESSAGING_ORIGIN_KEY: {"platform": "telegram", "chat_id": "-1001"}}
    send_queue.enqueue("root-tg", "msg-telegram-1000", {send_queue.ORIGIN_ARG: origin, "message": "hi"})
    refusal = request(rig)
    assert (refusal["reason"], refusal["held_by"]) == ("busy", "messaging_turn")
    assert session.drain_state is None and owner.capabilities()["accepting"]
    send_queue.remove("root-tg", "msg-telegram-1000")
    assert request(rig)["event"] == "draining"
