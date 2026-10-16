"""Compute mutations use classified existing-only control, reads use observe."""
import pytest

from tests.agent_runtime.test_subagent_compute_ownership import compute, gateway
from tests.agent_runtime.test_subagent_commands import register, guard, fresh_receipts
from tests.agent_runtime.test_subagent_worker_ownership import request


def test_compute_control_dispatch_and_lost_ack_reconcile(compute, monkeypatch):
    server, _, sessions, host, call, frames = compute
    child = register(sessions["ui-owner"], host._transport)
    selected = guard(call)
    supervisor = server._compute_host_supervisor
    original = supervisor.control

    def lose_reply(*args, **kwargs):
        assert kwargs["existing_only"] is True
        original(*args, **kwargs)
        raise RuntimeError("ack lost after dispatch")

    monkeypatch.setattr(supervisor, "control", lose_reply)
    payload = {**selected, "request_id": "once", "text": "compute correction"}
    assert request(call, "steer", **payload)["result"]["data"]["status"] == "unknown"
    assert frames[-1]["type"] == "control" and frames[-1]["route_name"] == "eternia.subagents.steer"
    assert request(call, "receipt", **selected, request_id="once")["result"]["data"]["status"] == "queued"
    assert str(child._drain_pending_steer()) == "compute correction"
    monkeypatch.setattr(supervisor, "control", original)
    assert request(call, "stop", **selected, request_id="stop")["result"]["data"]["status"] == "interrupt_requested"
    assert child._interrupt_requested
    with pytest.raises(RuntimeError):
        supervisor.observe("ui-owner", "eternia.subagents.stop", payload)


def test_missing_compute_owner_does_not_start_a_replacement(compute, monkeypatch):
    server, _, _, _, call, _ = compute
    selected = guard(call)
    def absent(_):
        raise RuntimeError("compute host is not running")
    monkeypatch.setattr(server._compute_host_supervisor, "_send_frame", absent)
    result = request(call, "stop", **selected, request_id="absent")
    assert result["result"]["data"]["status"] == "unknown"
