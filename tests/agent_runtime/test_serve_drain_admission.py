"""Drain and work admission must have one ordering on every native lane."""
from concurrent.futures import Future
import threading
from types import SimpleNamespace

import pytest

from agent_runtime.chat_turn import ChatTurnSpawnRefused
from agent_runtime.discussions import rpc
from agent_runtime.serve_rpc import handle_request, RpcContext
from agent_runtime.call_authorization import STDIO_OWNER
from tests.agent_runtime.test_serve_idle_drain import rig, request
from tests.agent_runtime.test_discussion_runtime import engine
from tests.agent_runtime.test_native_discussion_room import spec


@pytest.mark.parametrize("lane", ["method", "argv"])
@pytest.mark.parametrize("drain", [True, False])
def test_turn_registration_cannot_cross_an_accepted_drain(rig, monkeypatch, lane, drain):
    session, *_, frames = rig
    ready, release = threading.Event(), threading.Event()
    submitted, errors = [], []
    session.inflight_futures = {}
    session.pool = SimpleNamespace(submit=lambda *args: (submitted.append(args), Future())[1])

    def owner(_connection):
        ready.set()
        assert release.wait(5)
        return "stdio"

    monkeypatch.setattr(session, "_owner_of", owner)
    sink = SimpleNamespace(emit=frames.append)
    argv = ["harness", "persona", "chat", "--message", "hello"]

    def submit():
        try:
            if lane == "method":
                session._spawn_chat_turn(sink, None, "turn", argv, "exact-turn")
            else:
                session._dispatch_argv_request({"id": "turn", "argv": argv}, sink, None)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert ready.wait(5)
        if drain:
            assert request(rig)["event"] == "draining"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert len(submitted) == (0 if drain else 1)
    assert len(session.inflight) == len(submitted)
    if drain:
        if lane == "method":
            assert len(errors) == 1 and isinstance(errors[0], ChatTurnSpawnRefused)
            assert errors[0].reason == "draining"
        else:
            assert not errors
            assert any(frame.get("draining") for frame in frames)
    else:
        assert not errors
        # Only a TURN holds an idle drain; this argv is a stand-in, so mark the
        # registered request as the turn it plays.
        (registered,) = session.inflight.values()
        registered.is_chat_turn = True
        refusal = request(rig)
        assert (refusal["reason"], refusal["held_by"]) == ("busy", "chat_turn")


@pytest.mark.parametrize("busy", [False, True])
def test_discussion_rpc_cannot_start_after_idle_drain_and_failed_claim_leaves_it_open(
    rig, engine, monkeypatch, busy,
):
    session, owner, scope, sid, *_ = rig
    service, context = engine
    session.discussion_owner = service
    monkeypatch.setattr(rpc, "get_service", lambda: service)
    if busy:
        owner.send(scope, sid, "turn", {"text": "hello", "images": []})
    assert request(rig)["event"] == ("drain_deferred" if busy else "draining")
    assert service.accepting is busy
    result = handle_request({"jsonrpc": "2.0", "id": 1,
        "method": "runtime.discussion.run.start_room", "params": {
            "workspace_id": "ws", "spec": spec().to_dict(),
            "idempotency_key": "new-room", "topic": "Review",
        }}, RpcContext(caller=STDIO_OWNER))
    if busy:
        assert result["result"]["run"]["phase"] == "initializing"
    else:
        assert result["error"]["data"]["reason"] == "runtime_stopping"
        assert not service.runs.owned() and not context.calls
