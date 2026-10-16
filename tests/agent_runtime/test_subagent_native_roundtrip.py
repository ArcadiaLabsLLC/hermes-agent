"""Real delegate_task children are inspectable through the production service."""
import pytest
import json

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import until
from tests.agent_runtime.subagent_read_provider import SubagentProvider

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize("mode", ["native-worker", "isolated-compute", "in-process"])
@pytest.mark.parametrize("action", ["steer", "stop"])
def test_owned_child_reads_across_execution_hosts(tmp_path, mode, action):
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
        assert {"settings", "settings.set", "spawning", "spawning.set"} <= set(service.subagents(scope, sid, "capabilities", {})["operations"])
        spawning = service.subagents(scope, sid, "spawning", {})
        host_guard = {"expected_generation": spawning["generation"], "host_ref": spawning["host_ref"]}
        assert service.subagents(scope, sid, "spawning.set", {**host_guard, "paused": True})["paused"]
        assert service.subagents(scope, sid, "spawning", {})["paused"]
        assert service.subagents(scope, sid, "list", {})["children"][0]["subagent_id"] == child["subagent_id"]
        assert not service.subagents(scope, sid, "spawning.set", {**host_guard, "paused": False})["paused"]
        if mode == "native-worker" and action == "steer":
            capture = {"settings": service.subagents(scope, sid, "settings", {}), "spawning": spawning}
            (tmp_path / "subagent-native-settings.json").write_text(json.dumps(capture, indent=2), encoding="utf-8")
        if mode != "isolated-compute":
            assert service.subagents(scope, sibling, "list", {})["children"] == []
        else:
            # The sibling has no compute session. Reading it cannot construct one.
            from agent_runtime.subagents.model import SubagentError
            with pytest.raises(SubagentError):
                service.subagents(scope, sibling, "tail", guard)
        command = {**guard, "request_id": "real-command", **({"text": "Check the boundary."} if action == "steer" else {})}
        receipt = service.subagents(scope, sid, action, command)
        assert receipt["status"] == ("queued" if action == "steer" else "interrupt_requested")
        assert service.subagents(scope, sid, action, command)["status"] == receipt["status"]
        provider.release.set()
        until(lambda: service.subagents(scope, sid, "list", {}), lambda r: not r["children"])
        settled = service.subagents(scope, sid, "receipt", {**guard, "request_id": "real-command"})
        assert settled["status"] == receipt["status"]
        if action == "steer":
            settled = until(lambda: service.subagents(scope, sid, "receipt", {**guard, "request_id": "real-command"}),
                            lambda r: r["missed_steer"] is not None)
            assert settled["missed_steer"] is True
        from agent_runtime.subagents.model import Refusal, SubagentError
        with pytest.raises(SubagentError) as stale:
            service.subagents(scope, sid, "tail", guard)
        assert stale.value.reason == Refusal.STALE
        history = until(lambda: service.subagents(scope, sid, "history", {}), lambda r: bool(r["results"]))
        persisted = service.subagents(scope, sid, "result", {"expected_generation": history["generation"],
            "history_ref": history["results"][0]["history_ref"]})["result"]
        assert persisted["model"] == "test-model"
        assert persisted["status"] in {"completed", "interrupted"}
        # An unused native chat has no durable session yet; it cannot borrow
        # this parent's results or create a worker merely to answer history.
        with pytest.raises(SubagentError) as unused:
            service.subagents(scope, sibling, "history", {})
        assert unused.value.reason == Refusal.UNAVAILABLE
    finally:
        provider.release.set()
        service.close()
        provider.close()
    reopened = ConversationService(tmp_path / "runtime", "proof-install", profile_home=lambda _: home,
        worker_factory=lambda *args, **kwargs: pytest.fail("history recreated an execution worker"))
    try:
        assert reopened.subagents(scope, sid, "history", {})["results"]
    finally:
        reopened.close()
