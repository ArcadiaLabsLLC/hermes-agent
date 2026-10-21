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
    home = tmp_path / "profile"
    home.mkdir()
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
