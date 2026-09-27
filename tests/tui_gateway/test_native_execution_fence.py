"""Exact-execution controls use the native session and real SessionDB receipts."""
from contextlib import nullcontext
import threading

import pytest

from hermes_state import SessionDB
from tui_gateway import server, session_execution as execution


@pytest.fixture
def owner(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    session = {"session_key": "stored", "history_lock": threading.RLock(), "running": True}
    monkeypatch.setattr(server, "_session_db", lambda _: nullcontext(db))
    yield session, db
    db.close()


def complete(session, status="complete"):
    execution.stamp(session, {"method": "event", "params": {
        "type": "message.complete", "payload": {"status": status}}})


def test_old_stop_cannot_cancel_new_execution(owner, monkeypatch):
    session, _ = owner
    interrupted = []
    monkeypatch.setattr(server, "_interrupt_session_turn", lambda *args, **kwargs: interrupted.append(kwargs))
    execution.admit(session, "old")
    complete(session)
    execution.admit(session, "new")
    assert not execution.interrupt("ui", session, "old")
    assert not interrupted
    assert execution.interrupt("ui", session, "new")
    assert interrupted == [{"expected_execution_id": "new"}]
    assert execution.snapshot(session, "new")["status"] == "running"
    assert execution.snapshot(session, "new")["cancel_requested"]


def test_completion_wins_and_uncertain_receipt_is_not_replayed(owner, monkeypatch):
    session, _ = owner
    execution.admit(session, "turn")
    session.pop("native_execution")
    assert execution.snapshot(session, "turn")["status"] == "unknown"
    with pytest.raises(ValueError):
        execution.admit(session, "turn")
    assert execution.adopt(session, {"id": "turn"})
    complete(session)
    monkeypatch.setattr(server, "_interrupt_session_turn", lambda *a, **k: pytest.fail("completed work interrupted"))
    assert not execution.interrupt("ui", session, "turn")
    session.pop("native_execution")
    assert execution.snapshot(session, "turn")["status"] == "complete"


def test_cancel_before_compute_adoption_survives_lost_ack(owner):
    session, _ = owner
    execution.admit(session, "turn")
    assert execution.request_stop(session, "turn")
    child = {"session_key": "stored", "history_lock": threading.RLock()}
    assert not execution.adopt(child, {"id": "turn"})
    assert execution.snapshot(child, "turn")["cancel_requested"]


def test_delayed_compute_completion_keeps_its_original_identity(owner):
    session, _ = owner
    execution.admit(session, "old")
    complete(session)
    execution.admit(session, "new")
    late = {"method": "event", "params": {"execution_id": "old",
            "type": "message.complete", "payload": {"status": "interrupted"}}}
    execution.stamp(session, late)
    assert late["params"]["execution_id"] == "old"
    assert execution.snapshot(session, "new")["status"] == "running"
    assert execution.snapshot(session, "old")["status"] == "complete"
    with pytest.raises(ValueError, match="already settled"):
        execution.adopt(session, {"id": "old"})


def test_interrupt_fences_next_admission_without_holding_history(owner, monkeypatch):
    session, _ = owner
    entered, release, admitted = threading.Event(), threading.Event(), threading.Event()
    execution.admit(session, "old")

    def interrupt(*_, **__):
        entered.set()
        assert release.wait(2)

    def next_turn():
        with execution.control(session), session["history_lock"]:
            execution.admit(session, "new")
            admitted.set()

    monkeypatch.setattr(server, "_interrupt_session_turn", interrupt)
    stopper = threading.Thread(target=lambda: execution.interrupt("ui", session, "old"))
    starter = threading.Thread(target=next_turn)
    stopper.start()
    try:
        assert entered.wait(2)
        assert session["history_lock"].acquire(timeout=1)
        session["history_lock"].release()
        starter.start()
        assert not admitted.wait(.05)
    finally:
        release.set()
        stopper.join(2)
        if starter.ident:
            starter.join(2)
    assert admitted.is_set()


def test_stop_while_agent_builds_settles_the_exact_execution(owner, monkeypatch):
    session, _ = owner
    execution.admit(session, "building")
    server._start_inflight_turn(session, "hello")
    session["_turn_cancel_requested"] = True
    monkeypatch.setattr(server, "_wait_agent_for_prompt", lambda *args: None)
    emitted = []

    def emit(kind, sid, payload):
        frame = {"method": "event", "params": {
            "type": kind, "session_id": sid, "payload": payload}}
        execution.stamp(session, frame)
        emitted.append(frame)

    monkeypatch.setattr(server, "_emit", emit)
    monkeypatch.setattr(server, "_run_prompt_submit", lambda *a, **k: pytest.fail("cancelled turn ran"))
    server._run_after_agent_ready("rpc", "live", session, "hello", None, None, None)
    assert execution.snapshot(session, "building")["status"] == "interrupted"
    assert emitted[-1]["params"]["execution_id"] == "building"
    assert emitted[-1]["params"]["type"] == "message.complete"


def test_native_admission_rechecks_running_inside_the_claim(owner):
    session, _ = owner
    execution.admit(session, "already-running")
    error, _ = server._lock_in_submit_turn(
        "rpc", "live", session, "second", {"execution_id": "second"}, False, None, None, None)
    assert error["error"]["code"] == 4091
    assert execution.snapshot(session, None)["id"] == "already-running"
