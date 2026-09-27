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
    assert request(rig) == {"event": "drain_deferred", "id": "maintenance", "reason": "busy"}
    assert session.drain_state is None and not session.liveness_stop.is_set()
    assert owner.capabilities()["accepting"]
    assert session._busy_frame()["work"] == 1
    worker.event("native-0", "message.complete", text="done", status="complete")
    assert request(rig)["event"] == "draining"
    assert not owner.capabilities()["accepting"]
    with pytest.raises(ConversationError, match="runtime_stopping"):
        owner.send(scope, sid, "second", {"text": "must not run", "images": []})
    assert len([m for m, _ in worker.calls if m == "prompt.submit"]) == 1


def test_mission_control_work_blocks_but_standing_subscriptions_do_not(rig):
    session, owner, *_ = rig
    session.inflight["console"] = SimpleNamespace(is_runtime_stream=False)
    assert request(rig)["reason"] == "busy"
    assert owner.capabilities()["accepting"]
    session.inflight["console"].is_runtime_stream = True
    assert request(rig)["event"] == "draining"


def test_open_discussion_blocks_maintenance_between_rounds(rig):
    session, owner, *_ = rig
    session.discussion_owner = SimpleNamespace(pending_count=lambda: 1)
    assert request(rig)["reason"] == "busy"
    assert owner.capabilities()["accepting"]
    assert session._busy_frame()["work"] == 1


def test_unreadable_owner_is_not_idle(rig, monkeypatch):
    session, owner, *_ = rig
    def unreadable():
        raise OSError("unavailable")
    monkeypatch.setattr(owner.store, "unsettled", unreadable)
    assert request(rig)["reason"] == "unavailable"
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
