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


def test_parent_and_child_updates_cannot_erase_stop_or_terminal_evidence(owner):
    parent, _ = owner
    execution.admit(parent, "turn")
    child = {"session_key": "stored", "history_lock": threading.RLock()}
    assert execution.adopt(child, {"id": "turn"})
    assert execution.request_stop(parent, "turn")
    child["_submit_user_row"] = {"_row_id": 7}
    execution.submitted(child)
    assert execution.snapshot(child, "turn")["cancel_requested"]
    complete(child)
    execution.uncertain(parent, "turn")
    assert execution.snapshot(parent, "turn")["status"] == "complete"
    assert execution.snapshot(parent, "turn")["user_row_id"] == 7
    assert not execution.request_stop(parent, "turn")


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


def test_storage_rejection_settles_admitted_execution_without_starting_work(owner, monkeypatch):
    session, _ = owner
    execution.admit(session, "rejected")
    server._start_inflight_turn(session, "hello")
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _: False)
    monkeypatch.setattr(server, "_release_active_session_slot", lambda _: None)
    response = server._persist_session_row_for_submit("rpc", session, "hello")
    assert response["error"]["code"] == 5072
    assert not session["running"]
    session.pop("native_execution")
    assert execution.snapshot(session, "rejected")["status"] == "error"


def test_unwritable_rejection_receipt_remains_uncertain(owner, monkeypatch):
    session, db = owner
    execution.admit(session, "rejected")
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _: False)
    monkeypatch.setattr(server, "_release_active_session_slot", lambda _: None)
    def unavailable(*args):
        raise OSError("isolated storage fault")
    monkeypatch.setattr(db, "update_meta", unavailable)
    assert server._persist_session_row_for_submit("rpc", session, "hello")["error"]["code"] == 5072
    assert not session["running"]
    session.pop("native_execution")
    assert execution.snapshot(session, "rejected")["status"] == "unknown"


def test_uncertain_compute_dispatch_never_falls_back_to_an_inline_execution(owner, monkeypatch):
    session, _ = owner
    session["running"] = False
    monkeypatch.setitem(server._sessions, "live", session)
    monkeypatch.setattr(server, "_sess_nowait", lambda *args: (session, None))
    monkeypatch.setattr(server, "_legacy_group_fence_error", lambda *args: None)
    monkeypatch.setattr(server, "_ensure_active_session_slot", lambda *args: None)
    monkeypatch.setattr(server, "_reattach_refusal", lambda *args: None)
    monkeypatch.setattr(server, "current_transport", lambda: None)
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda *args: True)
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", lambda: {})
    monkeypatch.setattr(server, "_submit_prompt_to_compute_host",
        lambda *a, **k: server._err("rpc", 5019, "dispatch acknowledgement lost"))
    monkeypatch.setattr(server, "_persist_session_row_for_submit",
        lambda *a, **k: pytest.fail("uncertain child execution was dispatched inline"))
    response = server._methods["prompt.submit"]("rpc", {
        "session_id": "live", "text": "hello", "execution_id": "native-turn", "reject_if_busy": True})
    assert response["error"]["code"] == 5019
    assert execution.snapshot(session, "native-turn")["status"] == "unknown"
