"""Public RPC → supervisor pipe → actual child pending owner → acknowledged result."""
import sys
import threading

import pytest

from tui_gateway import server
from tui_gateway.host_supervisor import HostSupervisor

pytestmark = pytest.mark.timeout(60)


def test_child_ack_roundtrip_and_lost_ack_retry(tmp_path, monkeypatch):
    supervisor = HostSupervisor(registry_path=tmp_path / "host.json", autostart=False,
        argv=[sys.executable, "-u", "-m", "tests.tui_gateway.native_answer_child"])
    sid, rid = "answer-session", "native-question"
    session = {"history_lock": threading.RLock(), "_compute_host_open_request": {
        "id": rid, "method": "clarify", "params": {"session_id": sid, "question": "Continue?"}}}
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setitem(server._sessions, "other-session", {"history_lock": threading.RLock()})
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _: True)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda: supervisor)
    request = {"id": rid, "session_id": sid, "result": {"answer": "yes"}}
    try:
        supervisor.start()
        before = supervisor.observe(sid, "session.events.since", {"last_seen": 0})
        assert before["result"]["open_requests"][0]["id"] == rid
        foreign = server._methods["request.answer"]("foreign", {**request, "session_id": "other-session"})
        assert foreign["result"]["status"] == "expired"
        original = supervisor.respond

        def lose_ack(*args, **kwargs):
            assert original(*args, **kwargs)["response"]["result"]["status"] == "ok"
            raise TimeoutError("ack deliberately dropped after child acceptance")

        monkeypatch.setattr(supervisor, "respond", lose_ack)
        assert "error" in server._methods["request.answer"]("lost", request)
        assert session["_compute_host_open_request"]["id"] == rid
        monkeypatch.setattr(supervisor, "respond", original)
        assert server._methods["request.answer"]("retry", request)["result"]["status"] == "ok"
        assert "_compute_host_open_request" not in session
        assert server._methods["request.answer"]("repeat", request)["result"]["status"] == "ok"
        changed = server._methods["request.answer"]("changed", {**request, "result": {"answer": "no"}})
        assert "error" in changed
        after = supervisor.observe(sid, "session.events.since", {"last_seen": 0})
        assert after["result"]["open_requests"] == []
    finally:
        supervisor.shutdown()
