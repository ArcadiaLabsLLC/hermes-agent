"""Step 6: the pause lands in the conversation's own worker process, where delegate_task runs."""
import pytest

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import until
from tests.agent_runtime.subagent_read_provider import SubagentProvider

pytestmark = pytest.mark.timeout(120)


def _tool_results(provider):
    return [str(message.get("content")) for body in list(provider.requests)
            for message in body.get("messages", []) if message.get("role") == "tool"]


def test_paused_worker_refuses_spawn(tmp_path):
    from tools.delegate_tool_registry import is_spawn_paused

    provider = SubagentProvider()
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("subagent-proof")  # a canonical profile home: the in-process worker serves by name
    home.mkdir(parents=True)
    provider.configure(home, False)
    service = ConversationService(tmp_path / "runtime", "proof-install", profile_home=lambda _: home)
    scope = ConversationScope("operator", "proof-account", "subagent-proof")
    try:
        sid = service.open(scope, key="parent", cwd=str(tmp_path), expected_home=str(home))["session_id"]
        host = service.subagents(scope, sid, "spawning", {})
        assert (host["host_kind"], host["paused"], host["session_id"]) == ("native_worker", False, sid)
        paused = service.subagents(scope, sid, "spawning.set", {"expected_generation": host["generation"],
                                                                "host_ref": host["host_ref"], "paused": True})
        assert paused["paused"] is True and paused["host_ref"] == host["host_ref"]
        assert not is_spawn_paused()  # the serve's own pause is a different process's
        service.send(scope, sid, "parent-turn", {"text": "Launch the inspection child.", "images": []})
        results = until(lambda: _tool_results(provider), bool, timeout=60)
        assert "spawning is paused" in results[0], results
        assert not provider.entered.is_set()
        assert service.subagents(scope, sid, "spawning", {})["paused"] is True
    finally:
        provider.release.set()
        service.close()
        provider.close()


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
