"""Step 6: a worker's spawn pause is its profile's, never the serve's process flag."""
import pytest

pytestmark = pytest.mark.timeout(120)


def test_a_paused_profile_leaves_every_other_agent_in_the_serve_spawning(tmp_path):
    """RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT: the worker runs in the serve, so its pause is
    its profile's, never the process flag. Mutation: ``inspect_spawning`` sets upstream's process flag for a
    ``native_worker`` (the pause as it was) -> red (the other profile and the serve are paused too)."""

    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.delegate_tool_registry import is_spawn_paused

    from agent_runtime.subagents.spawning import host_ref, inspect_spawning, spawn_pause_refusal

    def as_profile(name, call):
        token = set_hermes_home_override(str(tmp_path / name))
        try:
            return call()
        finally:
            reset_hermes_home_override(token)

    params = {"host_ref": host_ref("native_worker"), "paused": True}
    try:
        assert as_profile("a", lambda: inspect_spawning(
            "spawning.set", params, generation="g", host_kind="native_worker"))["paused"] is True
        assert as_profile("a", lambda: spawn_pause_refusal("delegate_task", {"goal": "x"})) is not None
        assert as_profile("b", lambda: spawn_pause_refusal("delegate_task", {"goal": "x"})) is None
        assert as_profile("b", lambda: inspect_spawning(
            "spawning", {}, generation="g", host_kind="native_worker"))["paused"] is False
        assert not is_spawn_paused()
        assert as_profile("a", lambda: spawn_pause_refusal("delegate_task", {"action": "list"})) is None
    finally:
        as_profile("a", lambda: inspect_spawning("spawning.set", {**params, "paused": False},
                                                 generation="g", host_kind="native_worker"))
