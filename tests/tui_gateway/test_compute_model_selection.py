"""Idle model writes use the native admission fence and require a child receipt."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from tui_gateway import server
from agent_runtime.gateway import compute_model_selection
from agent_runtime.gateway.session_execution import control
from tests.tui_gateway.test_compute_host_pending_model_switch import _session


def test_model_change_rechecks_busy_after_waiting_for_admission():
    session = {"running": False}
    entered = Event()
    boundary = SimpleNamespace(_err=server._err)
    def select():
        entered.set()
        return compute_model_selection.forward(boundary, "pick", {"session_id": "s"}, session)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with control(session):
            result = pool.submit(select)
            assert entered.wait(2)
            session["running"] = True
        assert result.result(2)["error"]["code"] == 5032
    assert compute_model_selection.apply(boundary, {}, session) == {"error": "session busy"}


@pytest.mark.parametrize("outcome", ["refused", "timeout", "confirm"])
def test_unconfirmed_child_write_keeps_the_previous_pick(monkeypatch, outcome):
    pending = {"raw": "previous"}
    session = {"running": False, "pending_model_switch": pending}
    def send(*args, **kwargs):
        if outcome == "timeout":
            raise TimeoutError("no receipt")
        if outcome == "refused":
            return {"type": "control.error", "message": "session busy"}
        return {"type": "control.ack", "result": {"confirm_required": True}}
    monkeypatch.setattr(server, "_send_compute_host_control", send)
    if outcome == "timeout":
        with pytest.raises(TimeoutError):
            compute_model_selection.forward(server, "pick", {"session_id": "s"}, session)
    else:
        result = compute_model_selection.forward(server, "pick", {"session_id": "s"}, session)
        assert "error" in result if outcome == "refused" else result["result"]["confirm_required"]
    assert session["pending_model_switch"] is pending
    assert "_metadata_mirror" not in session


def test_idle_model_change_returns_the_compute_owners_receipt(monkeypatch):
    session = _session(_compute_host_active=True)
    monkeypatch.setitem(server._sessions, "idle-selection", session)
    calls = []
    result = {"key": "model", "value": "selected", "scope": "session"}
    def control(sid, **kwargs):
        calls.append((sid, kwargs))
        return {"type": "control.ack", "result": result,
                "session_info": {"model": "selected", "provider": "test"}}
    monkeypatch.setattr(server, "_send_compute_host_control", control)
    monkeypatch.setattr(server, "_start_agent_build", lambda *a: pytest.fail("must not create a second agent"))
    response = server.handle_request({"id": "selection", "method": "config.set",
        "params": {"session_id": "idle-selection", "key": "model", "value": "selected --provider test"}})
    assert response["result"] == result
    assert calls[0][0] == "idle-selection"
    assert calls[0][1]["route_name"] == "config.set.model"
    assert session["_metadata_mirror"] == {"model": "selected", "provider": "test"}
    assert "pending_model_switch" not in session
