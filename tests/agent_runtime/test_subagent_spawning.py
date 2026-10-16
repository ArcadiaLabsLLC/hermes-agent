"""Pause controls reach native state through the real registered owner routes."""
import json
from types import SimpleNamespace

import pytest

from tests.agent_runtime.test_subagent_worker_ownership import registered, request
from tests.agent_runtime import test_subagent_compute_ownership as compute_fixture
from tools.delegate_tool import delegate_task, is_spawn_paused, set_spawn_paused

gateway = compute_fixture.gateway
compute = compute_fixture.compute


@pytest.fixture(autouse=True)
def clear_pause():
    set_spawn_paused(False)
    yield
    set_spawn_paused(False)


def test_native_pause_guards_exact_host_and_leaves_existing_children(gateway, tmp_path):
    _, owner, transport, call = gateway
    child = registered(owner, transport)
    before = request(call, "spawning")["result"]["data"]
    guard = {"expected_generation": before["generation"], "host_ref": before["host_ref"], "paused": True}
    for invalid in ({"host_ref": "foreign"}, {"expected_generation": "old"}, {"paused": "true"}):
        assert "error" in request(call, "spawning.set", **{**guard, **invalid})
        assert not is_spawn_paused()
    assert "error" in request(call, "spawning.set", via=SimpleNamespace(write=lambda _: True), **guard)
    paused = request(call, "spawning.set", **guard)["result"]["data"]
    assert paused["paused"] and is_spawn_paused()
    assert "spawning is paused" in json.dumps(delegate_task(goal="should not launch", parent_agent=SimpleNamespace()))
    assert request(call, "list")["result"]["data"]["children"][0]["subagent_id"] == child._subagent_id
    resumed = request(call, "spawning.set", **{**guard, "paused": False})["result"]["data"]
    assert not resumed["paused"] and not is_spawn_paused()
    assert resumed["host_kind"] == "native_worker"
    (tmp_path / "subagent-spawning.json").write_text(json.dumps(resumed, indent=2), encoding="utf-8")


def test_compute_pause_uses_existing_control_and_lost_ack_is_unknown(compute, monkeypatch):
    server, _, _, _, call, frames = compute
    before = request(call, "spawning")["result"]["data"]
    assert before["host_kind"] == "isolated_compute"
    guard = {"expected_generation": before["generation"], "host_ref": before["host_ref"], "paused": True}
    original = server._compute_host_supervisor.control
    def lost(*args, **kwargs):
        assert kwargs["existing_only"] is True
        original(*args, **kwargs)
        raise RuntimeError("ack lost")
    monkeypatch.setattr(server._compute_host_supervisor, "control", lost)
    assert request(call, "spawning.set", **guard)["error"]["code"] == 4605
    assert frames[-1]["type"] == "control" and frames[-1]["route_name"] == "eternia.subagents.spawning.set"
    assert request(call, "spawning")["result"]["data"]["paused"]
