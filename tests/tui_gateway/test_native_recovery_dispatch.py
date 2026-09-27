"""A delayed recovery or answer must not strand Stop in the input pipe."""
import threading
from types import SimpleNamespace

import pytest

from tui_gateway import server
from tui_gateway import server_requests


def test_compute_answer_frame_keeps_stop_readable(monkeypatch):
    entered, release, stopped, replied = (threading.Event() for _ in range(4))

    def answer(_):
        entered.set()
        assert release.wait(5)
        replied.set()
        return True

    def stop(rid, _):
        stopped.set()
        return server._err(rid, 4001, "Test session")

    monkeypatch.setattr(server_requests, "resolve_response", lambda _: False)
    monkeypatch.setattr(server, "_relay_compute_host_response", answer)
    monkeypatch.setitem(server._methods, "session.interrupt", stop)
    def input_frames():
        server.dispatch({"id": "srq-child", "result": {"answer": "Yes"}})
        server.dispatch({"id": "stop", "method": "session.interrupt", "params": {"session_id": "live"}})
    reader = threading.Thread(target=input_frames)
    reader.start()
    try:
        assert entered.wait(2)
        assert stopped.wait(2), "Compute answer acknowledgement blocked Stop"
    finally:
        release.set()
        reader.join(5)
    assert replied.wait(2)


@pytest.mark.parametrize("method,params", [
    ("session.recover", {"session_id": "live"}),
    ("session.recovery.history", {"session_id": "live", "position": {
        "session_key": "stored", "through_row": 0, "version": 0}}),
    ("session.recovery.inflight", {"session_id": "live", "execution_id": "turn",
        "field": "assistant", "through": 0}),
    ("session.events.since", {"session_id": "live"}),
    ("session.retire", {"session_id": "live"}),
    ("request.answer", {"session_id": "live", "id": "question", "result": {}}),
])
def test_waiting_native_rpc_leaves_input_thread_free_for_stop(monkeypatch, method, params):
    entered, release, stopped, replied = (threading.Event() for _ in range(4))

    def wait(rid, _):
        entered.set()
        assert release.wait(5)
        return server._err(rid, 5019, "Delayed child")

    def stop(rid, _):
        stopped.set()
        return server._err(rid, 4001, "Test session")

    monkeypatch.setitem(server._methods, method, wait)
    monkeypatch.setitem(server._methods, "session.interrupt", stop)
    transport = SimpleNamespace(write=lambda _: replied.set())

    def input_frames():
        server.dispatch({"id": "read", "method": method, "params": params}, transport)
        server.dispatch({"id": "stop", "method": "session.interrupt",
                         "params": {"session_id": "live"}}, transport)

    reader = threading.Thread(target=input_frames)
    reader.start()
    try:
        assert entered.wait(2)
        assert stopped.wait(2), f"{method} blocked the gateway input thread"
    finally:
        release.set()
        reader.join(5)
    assert replied.wait(2)
