"""An uncertain pipe write keeps the original compute owner and completion path."""
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from hermes_state import SessionDB
from tui_gateway import server, session_execution
from tui_gateway.host_supervisor import HostSupervisor


def test_observation_waits_for_exact_child_start_ack_without_blocking_controls(tmp_path, monkeypatch):
    supervisor = HostSupervisor(registry_path=tmp_path / "host.json", autostart=False)
    monkeypatch.setattr(supervisor, "start", lambda: None)
    monkeypatch.setattr(supervisor, "_send_frame", lambda _: None)
    observed = threading.Event()
    def reply(*args):
        observed.set()
        return {"type": "observe.ack", "response": {"result": {"running": True}}}
    monkeypatch.setattr(supervisor, "_await_reply", reply)
    supervisor.submit_turn({"sid": "session", "request_id": "dispatch"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        read = pool.submit(supervisor.observe, "session", "session.recover", {}, timeout=2)
        assert not observed.wait(.03)
        supervisor.interrupt("session", expected_execution_id="native-turn")
        supervisor._handle_host_frame({"type": "turn.started", "request_id": "wrong"})
        assert not observed.wait(.03)
        supervisor._handle_host_frame({"type": "turn.started", "request_id": "dispatch"})
        assert read.result() == {"result": {"running": True}}


@pytest.mark.parametrize("native", [True, False])
def test_failed_write_preserves_only_native_completion_waiter(tmp_path, monkeypatch, native):
    supervisor = HostSupervisor(registry_path=tmp_path / "host.json", autostart=False)
    monkeypatch.setattr(supervisor, "start", lambda: None)
    sent, completed = [], []

    def uncertain_write(frame):
        sent.append(frame)
        raise OSError("reply lost after delivery")

    monkeypatch.setattr(supervisor, "_send_frame", uncertain_write)
    frame = {"sid": "session", "request_id": "dispatch"}
    if native:
        frame["native_execution"] = {"id": "execution"}
    with pytest.raises(OSError):
        supervisor.submit_turn(frame, on_complete=completed.append)
    assert len(sent) == 1
    if native:
        assert not completed
        supervisor._handle_host_frame({"type": "turn.end", "request_id": "dispatch", "sid": "session"})
        assert completed == [{"type": "turn.end", "request_id": "dispatch", "sid": "session"}]
    else:
        assert completed[0]["reason"] == "send_failed"
    assert not supervisor._pending_turns


def test_uncertain_bridge_keeps_child_observation_and_original_completion(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    session = server._deferred_session_record("stored", cols=80, cwd=str(tmp_path), history=[], lease=None, lazy=True)
    monkeypatch.setattr(server, "_session_db", lambda _: nullcontext(db))
    session_execution.admit(session, "execution")
    session["running"] = True
    supervisor = HostSupervisor(registry_path=tmp_path / "host.json", autostart=False)
    monkeypatch.setattr(supervisor, "start", lambda: None)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda *a: supervisor)
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", lambda: {"turn_isolation": True})
    monkeypatch.setattr(supervisor, "_send_frame", lambda _: (_ for _ in ()).throw(OSError("uncertain")))
    completed = []
    monkeypatch.setattr(server, "_on_compute_host_turn_done", lambda *args: completed.append(args[-1]))
    try:
        response = server._submit_prompt_to_compute_host("rpc", "live", session, "hello")
        assert response["error"]["code"] == 5019
        assert session["_compute_host_active"]
        assert server._session_uses_compute_host(session)
        dispatch = session["_compute_host_turn_id"]
        supervisor._handle_host_frame({"type": "turn.end", "request_id": dispatch, "sid": "live"})
        assert len(completed) == 1
        assert "_compute_host_turn_id" not in session
    finally:
        db.close()
