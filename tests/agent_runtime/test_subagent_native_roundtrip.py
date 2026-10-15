"""Real delegate_task children are inspectable through the production service."""
import pytest

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import until
from tests.agent_runtime.subagent_read_provider import SubagentProvider

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize("mode", ["native-worker", "isolated-compute", "in-process"])
def test_owned_child_reads_across_execution_hosts(tmp_path, mode):
    from hermes_cli.profiles import get_profile_dir
    from agent_runtime.conversations.in_process_peer import start_in_process_worker

    provider = SubagentProvider()
    home = get_profile_dir("subagent-proof") if mode == "in-process" else tmp_path / "profile"
    home.mkdir(parents=True, exist_ok=True)
    provider.configure(home, mode == "isolated-compute")
    options = {"worker_factory": start_in_process_worker} if mode == "in-process" else {}
    service = ConversationService(tmp_path / "runtime", "proof-install", profile_home=lambda _: home, **options)
    scope = ConversationScope("operator", "proof-account", "subagent-proof")
    try:
        sid = service.open(scope, key="parent", cwd=str(tmp_path), expected_home=str(home))["session_id"]
        sibling = service.open(scope, key="sibling", cwd=str(tmp_path), expected_home=str(home))["session_id"]
        service.send(scope, sid, "parent-turn", {"text": "Launch the inspection child.", "images": []})
        assert provider.entered.wait(35), str(provider.requests)[-5000:]
        roster = until(lambda: service.subagents(scope, sid, "list", {}), lambda r: bool(r["children"]))
        child = roster["children"][0]
        assert child["goal"] == "CHILD_READ_PROOF" and child["model"] == "test-model"
        assert child["status"] == "running" and child["child_ref"]
        guard = {"expected_generation": roster["generation"], "child_ref": child["child_ref"]}
        tail = until(lambda: service.subagents(scope, sid, "tail", guard),
                     lambda r: "Child public progress." in r["text"])
        assert len(tail["text"].encode()) <= 16384 and "PRIVATE_KICKOFF_CONTEXT" not in tail["text"]
        assert tail["subagent_id"] == child["subagent_id"]
        assert service.subagents(scope, sid, "capabilities", {})["operations"] == ["list", "tail"]
        if mode != "isolated-compute":
            assert service.subagents(scope, sibling, "list", {})["children"] == []
        else:
            # The sibling has no compute session. Reading it cannot construct one.
            from agent_runtime.subagents.model import SubagentError
            with pytest.raises(SubagentError):
                service.subagents(scope, sibling, "tail", guard)
        provider.release.set()
        until(lambda: service.subagents(scope, sid, "list", {}), lambda r: not r["children"])
        from agent_runtime.subagents.model import Refusal, SubagentError
        with pytest.raises(SubagentError) as stale:
            service.subagents(scope, sid, "tail", guard)
        assert stale.value.reason == Refusal.STALE
    finally:
        provider.release.set()
        service.close()
        provider.close()
