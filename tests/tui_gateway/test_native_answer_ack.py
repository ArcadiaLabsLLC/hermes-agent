"""The gateway must report the child's verdict, not successful pipe delivery."""
import threading
from types import SimpleNamespace

import pytest

from tui_gateway import server, server_requests


@pytest.fixture
def hosted(monkeypatch):
    sid, request_id = "ack-session", "srq-ack"
    session = {"history_lock": threading.Lock(), "_compute_host_open_request": {
        "id": request_id, "method": "clarify", "params": {"session_id": sid, "question": "Continue?"}}}
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _: True)
    yield sid, request_id, session
    server_requests.reset_for_tests()


@pytest.mark.parametrize("status", ["ok", "expired"])
def test_native_answer_reports_child_verdict(hosted, monkeypatch, status):
    sid, request_id, session = hosted
    calls = []

    def respond(owner, params):
        calls.append((owner, params))
        return {"type": "respond.ack", "response": {"result": {"status": status}}}

    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda: SimpleNamespace(respond=respond))
    reply = server._methods["request.answer"]("answer", {"id": request_id, "result": {"answer": "yes"}})
    assert reply["result"]["status"] == status
    assert calls[0][0] == sid
    assert "_compute_host_open_request" not in session


@pytest.mark.parametrize("failure", [TimeoutError(), {"type": "respond.error"}, {"type": "respond.ack"}])
def test_missing_child_ack_does_not_claim_acceptance_or_forget_question(hosted, monkeypatch, failure):
    _, request_id, session = hosted

    def respond(*_):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda: SimpleNamespace(respond=respond))
    reply = server._methods["request.answer"]("answer", {"id": request_id, "result": {"answer": "yes"}})
    assert "error" in reply
    assert session["_compute_host_open_request"]["id"] == request_id


def test_lost_answer_ack_retry_uses_original_native_receipt():
    request = server_requests.ServerRequest("exact-session", "clarify", {"question": "Continue?"})
    with server_requests._lock:
        server_requests._open[request.id] = request
    frame = {"id": request.id, "result": {"answer": "yes"}}
    try:
        assert not server_requests.resolve_response(frame, session_id="foreign")
        assert server_requests.resolve_response(frame, session_id="exact-session")
        assert request.event.is_set()
        assert server_requests.resolve_response(frame, session_id="exact-session")
        assert not server_requests.resolve_response(frame, session_id="foreign")
        with pytest.raises(ValueError):
            server_requests.resolve_response({**frame, "result": {"answer": "no"}}, session_id="exact-session")
        assert request.result == {"answer": "yes"}
    finally:
        server_requests.reset_for_tests()


def test_child_rejects_another_sessions_request():
    import io
    import json
    from tui_gateway.compute_host import ComputeHost

    output = io.StringIO()
    host = ComputeHost(stdout=output, heartbeat_secs=0)
    request = server_requests.ServerRequest("other", "clarify", {"question": "Private?"})
    with server_requests._lock:
        server_requests._open[request.id] = request
    server._sessions["answerer"] = {"history_lock": threading.Lock()}
    try:
        host._handle_respond({"sid": "answerer", "request_id": "response", "params": {
            "frame": {"id": request.id, "result": {"answer": "yes"}}}})
        assert json.loads(output.getvalue())["response"]["result"]["status"] == "expired"
        assert not request.event.is_set()
    finally:
        server._sessions.pop("answerer")
        server_requests.reset_for_tests()
        host.close()
