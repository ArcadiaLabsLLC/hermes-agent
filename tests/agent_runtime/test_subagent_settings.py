"""Real profile writer and public owner routes; no execution-worker acquisition."""
import json

import pytest
import yaml

from agent_runtime.conversations.model import ConversationError, ConversationScope
from agent_runtime.subagents.model import Refusal, SubagentError
from tests.agent_runtime import test_native_conversation as native_fixture
from tests.hermes_cli import test_model_switch_user_provider_slug_verbatim as route_fixture

runtime = native_fixture.runtime
endpoint = route_fixture.endpoint


def reserved(runtime):
    service, factory, root = runtime
    scope = ConversationScope("operator", "account", "a")
    route = service.store.reserve(scope, "settings", str(root / "work"), str(root / "a"))[0]
    return service, factory, root / "a" / "config.yaml", scope, route.id


def patch(service, scope, sid, before, changes):
    return service.subagents(scope, sid, "settings.set", {"expected_generation": before["generation"],
        "expected_revision": before["revision"], "changes": changes})


def fields(reply):
    return {field["key"]: field for field in reply["fields"]}


def test_owned_settings_save_preserves_native_file_without_worker(runtime, tmp_path):
    service, factory, path, scope, sid = reserved(runtime)
    path.write_text("# keep this comment\ndelegation:\n  api_key: secret-test-key\n  max_iterations: 99\ncustom: keep\n", encoding="utf-8")
    before = service.subagents(scope, sid, "settings", {})
    assert fields(before)["max_iterations"]["value"] == 99
    assert before["advanced_route"] and "secret-test-key" not in json.dumps(before)
    assert not fields(before)["model"]["writable"]
    saved = patch(service, scope, sid, before, {"max_iterations": 31, "max_spawn_depth": 2})
    assert fields(saved)["max_iterations"]["value"] == 31
    assert fields(saved)["max_spawn_depth"]["value"] == 2
    assert saved["revision"] != before["revision"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["custom"] == "keep" and raw["delegation"]["api_key"] == "secret-test-key"
    assert "# keep this comment" in path.read_text(encoding="utf-8")
    reset = patch(service, scope, sid, saved, {"max_iterations": None})
    assert fields(reset)["max_iterations"]["configured"] is None
    assert fields(reset)["max_iterations"]["value"] == fields(reset)["max_iterations"]["default"]
    assert not factory.workers
    for wrong in (ConversationScope("other", scope.client, scope.profile),
                  ConversationScope(scope.actor, "other", scope.profile),
                  ConversationScope(scope.actor, scope.client, "b")):
        with pytest.raises(ConversationError):
            patch(service, wrong, sid, reset, {"max_iterations": 5})
    (tmp_path / "subagent-native-settings.json").write_text(json.dumps({"settings": reset}, indent=2), encoding="utf-8")


def test_external_change_managed_policy_and_malformed_config_refuse(runtime, tmp_path, monkeypatch):
    service, _, path, scope, sid = reserved(runtime)
    before = service.subagents(scope, sid, "settings", {})
    path.write_text("delegation:\n  max_iterations: 77\n", encoding="utf-8")
    with pytest.raises(SubagentError) as stale:
        patch(service, scope, sid, before, {"max_iterations": 4})
    assert stale.value.reason == Refusal.STALE
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text("delegation:\n  max_iterations: 42\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    before = service.subagents(scope, sid, "settings", {})
    assert fields(before)["max_iterations"]["value"] == 42
    assert not fields(before)["max_iterations"]["writable"]
    with pytest.raises(SubagentError) as pinned:
        patch(service, scope, sid, before, {"max_iterations": 4})
    assert pinned.value.reason == Refusal.MANAGED
    saved = patch(service, scope, sid, before, {"max_spawn_depth": 3})
    assert fields(saved)["max_spawn_depth"]["value"] == 3
    path.write_text("delegation: [broken", encoding="utf-8")
    with pytest.raises(SubagentError) as unreadable:
        patch(service, scope, sid, saved, {"max_spawn_depth": 4})
    assert unreadable.value.reason == Refusal.CONFIG_UNREADABLE
    assert path.read_text(encoding="utf-8") == "delegation: [broken"


@pytest.mark.parametrize("changes", [{"api_key": "secret"}, {"max_iterations": True},
    {"max_spawn_depth": 0}, {"child_timeout_seconds": 2}, {"compression_threshold_tokens": 10},
    {"reasoning_effort": "invented"}, {"worktree_isolation": "false"}, {}])
def test_invalid_values_never_write(runtime, changes):
    service, _, path, scope, sid = reserved(runtime)
    before = service.subagents(scope, sid, "settings", {})
    with pytest.raises(SubagentError) as invalid:
        patch(service, scope, sid, before, changes)
    assert invalid.value.reason == Refusal.INVALID
    assert not path.exists()


def test_native_route_validation_and_each_default_use_profile_writer(runtime, endpoint):
    from hermes_cli.config import get_config_path
    service, _, path, scope, sid = reserved(runtime)
    path.write_text(get_config_path().read_text(encoding="utf-8"), encoding="utf-8")
    changes = {"model": "deepseek-v4-flash-0731", "provider": "custom:hyper", "reasoning_effort": "none",
        "max_iterations": 7, "max_concurrent_children": 2, "max_spawn_depth": 2,
        "orchestrator_enabled": False, "child_timeout_seconds": 30, "worktree_isolation": True,
        "independent_completions": True, "oneshot_max_children": 3, "compression_threshold_tokens": 16000,
        "surface_child_process_notifications": True, "inherit_mcp_toolsets": False}
    before = service.subagents(scope, sid, "settings", {})
    saved = patch(service, scope, sid, before, changes)
    assert {key: field["value"] for key, field in fields(saved).items()} == changes
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["providers"]["hyper"]["base_url"] == endpoint


def test_next_native_child_consumes_saved_budget_without_rebuilding_parent(runtime):
    from unittest.mock import MagicMock, patch as mocked
    from agent_runtime.profile_context import process_home_scope
    from tests.tools.test_delegate import _make_mock_parent
    from tools.delegate_tool import delegate_task

    service, _, path, scope, sid = reserved(runtime)
    before = service.subagents(scope, sid, "settings", {})
    patch(service, scope, sid, before, {"max_iterations": 7})
    parent = _make_mock_parent()
    child = MagicMock(model="test-model", session_prompt_tokens=0, session_completion_tokens=0)
    child.run_conversation.return_value = {"final_response": "done", "completed": True,
        "interrupted": False, "api_calls": 1, "messages": []}
    with process_home_scope(path.parent), mocked("run_agent.AIAgent", return_value=child) as constructor:
        result = json.loads(delegate_task(goal="Use saved defaults", parent_agent=parent, max_iterations=99))
    assert result["results"][0]["summary"] == "done"
    assert constructor.call_args.kwargs["max_iterations"] == 7
    assert parent.model == "anthropic/claude-sonnet-4"
