"""Step 6: the isolated compute host answers its own spawning pause, over the existing lanes."""
import pytest

from agent_runtime.subagents import spawning
from tools.delegate_tool_registry import is_spawn_paused, set_spawn_paused
from tests.agent_runtime.test_subagent_compute_ownership import compute, gateway
from tests.agent_runtime.test_subagent_worker_ownership import request


@pytest.fixture(autouse=True)
def unpaused():
    set_spawn_paused(False)
    yield
    set_spawn_paused(False)


def test_isolated_compute_pause_round_trip(compute):
    _, _, _, _, call, frames = compute
    reply = request(call, "spawning")
    assert "result" in reply, reply
    host = reply["result"]["data"]
    assert (host["scope"], host["host_kind"], host["paused"]) == ("execution_host", "isolated_compute", False)
    assert frames[-1]["method"] == "eternia.subagents.spawning"
    reply = request(call, "spawning.set", expected_generation=host["generation"], host_ref=host["host_ref"], paused=True)
    assert "result" in reply, reply
    assert reply["result"]["data"]["paused"] is True and reply["result"]["data"]["host_ref"] == host["host_ref"]
    assert frames[-1]["type"] == "control" and frames[-1]["route_name"] == "eternia.subagents.spawning.set"
    assert is_spawn_paused()
    assert request(call, "spawning")["result"]["data"]["paused"] is True


def test_stale_host_ref_after_restart(compute, monkeypatch):
    _, _, _, _, call, _ = compute
    old = request(call, "spawning")["result"]["data"]
    monkeypatch.setattr(spawning, "_BOOT", spawning._BOOT + 1)  # the compute host process was replaced
    reply = request(call, "spawning.set", expected_generation=old["generation"], host_ref=old["host_ref"], paused=True)
    assert reply["error"]["code"] == 4602, reply
    assert not is_spawn_paused()
    fresh = request(call, "spawning")["result"]["data"]
    assert fresh["host_ref"] != old["host_ref"]
