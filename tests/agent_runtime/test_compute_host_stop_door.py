"""RT-SEAM-COMPUTE-HOST-STOP-DOOR: the in-process worker's compute-host stop goes through a public door.

The worker child that once made this stop on its way out (``worker_entry``) is retired; the last in-process
worker to close makes it now (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT).

``tui_gateway.compute_host_bridge.existing_compute_host_supervisor`` is rebound onto
``tui_gateway.server``'s globals by ``bind_module``, where upstream's own getter keeps the
singleton. The positive control makes the supervisor through UPSTREAM'S getter and sees the
worker stop that very object; the negative half proves the door never makes one.
"""

from __future__ import annotations

import pytest

from agent_runtime import _upstream_doors
from agent_runtime.conversations import in_process_peer


class _Supervisor:
    made: list[_Supervisor] = []

    def __init__(self, **_kwargs):
        self.stopped = 0
        _Supervisor.made.append(self)

    def shutdown(self):
        self.stopped += 1


@pytest.fixture
def server(monkeypatch):
    from tui_gateway import host_supervisor, server as gateway_server

    _Supervisor.made = []
    monkeypatch.setattr(host_supervisor, "HostSupervisor", _Supervisor)
    monkeypatch.setattr(gateway_server, "_compute_host_supervisor", None)
    monkeypatch.setattr(gateway_server, "_load_dashboard_process_isolation_config", dict)
    return gateway_server


def test_the_worker_stops_the_supervisor_upstreams_getter_made(server):
    made = server._get_compute_host_supervisor()

    assert server.existing_compute_host_supervisor() is made
    assert _upstream_doors.subagent_compute_supervisor() is made
    in_process_peer.stop_compute_host()
    assert made.stopped == 1


def test_no_supervisor_is_made_to_be_stopped(server):
    in_process_peer.stop_compute_host()

    assert _Supervisor.made == []
    assert server.existing_compute_host_supervisor() is None
    assert _upstream_doors.subagent_compute_supervisor() is None


class _RetireServer:
    """The server surface ``session_retirement.retire`` reads, with the door under test."""

    def __init__(self, supervisor):
        import threading

        self.supervisor = supervisor
        self._session_resume_lock = threading.Lock()
        self._sessions_lock = threading.Lock()
        self._sessions = {}
        self.torn_down = []

    def existing_compute_host_supervisor(self):
        return self.supervisor

    def _session_uses_compute_host(self, session):
        return True

    def _session_is_lru_evictable(self, sid, session, *, require_dead_transport):
        return True

    def _pending_approval_request_payload(self, key):
        return None

    def _pop_session_by_id(self, sid):
        return self._sessions.pop(sid)

    def _teardown_popped_session(self, session, *, end_reason):
        self.torn_down.append(end_reason)


class _Observer:
    def __init__(self):
        self.calls = []

    def observe(self, sid, method, params):
        self.calls.append(method)
        return {"result": {"status": "retired"}}


def _settled_session():
    import threading

    return {"native_execution": {"id": "exec-1", "status": "complete"}, "_compute_host_active": True,
            "history_lock": threading.RLock()}


def test_retirement_observes_through_the_existing_supervisor():
    from agent_runtime.gateway import session_retirement

    observer = _Observer()
    server = _RetireServer(observer)
    session = server._sessions["sid-1"] = _settled_session()

    assert session_retirement.retire(server, "sid-1", session, "exec-1") == {"status": "retired"}
    assert observer.calls == ["session.retire"]


def test_retirement_without_a_supervisor_refuses_instead_of_making_one():
    from agent_runtime.gateway import session_retirement

    server = _RetireServer(None)
    session = server._sessions["sid-1"] = _settled_session()

    with pytest.raises(RuntimeError, match="compute host is not running"):
        session_retirement.retire(server, "sid-1", session, "exec-1")
    assert server._sessions == {"sid-1": session} and server.torn_down == []


def test_the_last_in_process_worker_to_close_stops_the_compute_host_and_no_earlier_one(server, tmp_path):
    """Mutation: ``InProcessPeer.close`` never calls ``stop_compute_host`` (the retired worker's step with no
    in-process twin) -> red; it calls it on every close -> red (the second worker loses its compute host)."""

    from hermes_cli.profiles import get_profile_dir

    made = server._get_compute_host_supervisor()
    peers = []
    for name in ("one", "two"):
        get_profile_dir(name).mkdir(parents=True, exist_ok=True)
        peers.append(in_process_peer.InProcessPeer(get_profile_dir(name), receive=lambda _f: None,
                                                    lost=lambda: None, dispatch=lambda *_a: None))
    peers[0].close()
    assert made.stopped == 0, "the compute host was stopped while another worker still served"
    peers[1].close()
    assert made.stopped == 1
