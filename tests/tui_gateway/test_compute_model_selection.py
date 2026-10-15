"""Idle model writes use the native admission fence and require a child receipt."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from tui_gateway import compute_model_selection, server
from tui_gateway.session_execution import control


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
