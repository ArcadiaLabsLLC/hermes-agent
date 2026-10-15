"""Real supervisor/compute dispatch with only the process boundary doubled."""
import io
from types import SimpleNamespace

import pytest

from tui_gateway.compute_host import ComputeHost
from tui_gateway.host_supervisor import HostSupervisor
from tools.delegation_live_log import LiveTranscriptWriter
from tests.tui_gateway.test_subagent_snapshot import runtime as gateway
from tests.agent_runtime.test_subagent_worker_ownership import registered, request


@pytest.fixture
def compute(gateway, monkeypatch, tmp_path):
    server, outer, _, call = gateway
    host = ComputeHost(stdout=io.StringIO(), heartbeat_secs=0)
    supervisor = HostSupervisor(registry_path=tmp_path / "host.json", autostart=False,
                                expected_build_sha="test", expected_hermes_home=str(tmp_path))
    inner = {"session_key": "parent", "history": [], "transport": host._transport}
    sessions = {"ui-owner": inner}
    frames = []

    def send(frame):
        frames.append(frame)
        with monkeypatch.context() as child:
            child.setattr(server, "_sessions", sessions)
            host.handle_frame(frame)

    def forbidden_start():
        pytest.fail("inspection started or replaced compute")

    monkeypatch.setattr(supervisor, "start", forbidden_start)
    monkeypatch.setattr(supervisor, "_send_frame", send)
    monkeypatch.setattr(host, "emit", supervisor._handle_host_frame)
    monkeypatch.setattr(server, "_compute_host_supervisor", supervisor)
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda session: session is outer)
    child = registered(inner, host._transport)
    writer = LiveTranscriptWriter("compute", 0, "task", root=tmp_path)
    writer.assistant_text("compute-owned output")
    child._live_transcript_path = str(writer.path)
    try:
        yield server, outer, sessions, host, call, frames
    finally:
        host._executor.shutdown(wait=True)


def test_compute_reads_keep_both_transport_generations_and_exact_child(compute):
    _, outer, sessions, _, call, frames = compute
    roster = request(call, "list")["result"]["data"]
    ref = dict(child_ref=roster["children"][0]["child_ref"], expected_generation=roster["generation"])
    assert request(call, "tail", **ref)["result"]["data"]["text"].endswith("compute-owned output")
    before = len(frames)
    foreign = SimpleNamespace(write=lambda _: True)
    assert request(call, "tail", via=foreign, **ref)["error"]["code"] == 4601
    assert len(frames) == before
    # Reattaching the outer conversation cannot keep the previous reference.
    original = outer["transport"]
    outer["transport"] = foreign
    assert request(call, "tail", via=foreign, **ref)["error"]["code"] == 4602
    outer["transport"] = original
    # A host/session replacement likewise invalidates its original generation.
    sessions["ui-owner"] = dict(sessions["ui-owner"])
    assert request(call, "tail", **ref)["error"]["code"] == 4602
    sessions["ui-owner"]["transport"] = foreign
    assert request(call, "list")["error"]["code"] == 4601


def test_detached_outer_owner_cannot_receive_a_late_compute_reply(compute, monkeypatch):
    server, outer, _, _, call, _ = compute
    observe = server._compute_host_supervisor.observe

    def detached(*args, **kwargs):
        reply = observe(*args, **kwargs)
        outer["transport"] = SimpleNamespace(write=lambda _: True)
        return reply

    monkeypatch.setattr(server._compute_host_supervisor, "observe", detached)
    assert request(call, "list")["error"]["code"] == 4601


def test_compute_observer_keeps_controls_closed_and_session_id_server_owned(compute):
    server, _, _, _, call, frames = compute
    roster = request(call, "list")["result"]["data"]
    assert len(roster["children"]) == 1
    supervisor = server._compute_host_supervisor
    with pytest.raises(RuntimeError, match="unavailable"):
        supervisor.observe("ui-owner", "subagent.interrupt", {"subagent_id": "child"})
    response = supervisor.observe("missing", "eternia.subagents.list", {
        "session_id": "ui-owner", "owner_scope": "forged", "worker_generation": "forged"})
    assert response["error"]["code"] == 4601
    assert frames[-1]["sid"] == "missing"
