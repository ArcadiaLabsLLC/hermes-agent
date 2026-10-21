"""Step 6 profile delegation defaults: the next child's values, written to the profile's file."""
import pytest

from agent_runtime.subagents.model import Refusal, SubagentError
from agent_runtime.subagents.settings import DELEGATION_FIELDS, read_settings, write_settings
from tests.agent_runtime.test_native_conversation import runtime, opened
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # autouse: the operator chat head


def _field(reply, key):
    return next(field for field in reply["fields"] if field["key"] == key)


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text("delegation:\n  max_iterations: 7\n", encoding="utf-8")
    return home


@pytest.fixture
def managed(tmp_path, monkeypatch):
    from hermes_cli.managed_scope import invalidate_managed_cache

    scope = tmp_path / "managed"
    scope.mkdir()
    (scope / "config.yaml").write_text("delegation:\n  max_spawn_depth: 3\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(scope))
    invalidate_managed_cache()
    yield scope
    invalidate_managed_cache()


def test_managed_key_is_read_only_and_refuses_write(home, managed):
    before = read_settings(home)
    pinned = _field(before, "max_spawn_depth")
    assert (pinned["writable"], pinned["source"], pinned["value"]) == (False, "managed", 3)
    with pytest.raises(SubagentError) as refused:
        write_settings(home, before["revision"], {"max_spawn_depth": 2})
    assert refused.value.reason == Refusal.MANAGED
    assert "max_spawn_depth" not in (home / "config.yaml").read_text(encoding="utf-8")


def test_stale_revision_refuses(home):
    before = read_settings(home)
    write_settings(home, before["revision"], {"max_iterations": 9})
    with pytest.raises(SubagentError) as stale:
        write_settings(home, before["revision"], {"max_iterations": 11})
    assert stale.value.reason == Refusal.STALE
    assert _field(read_settings(home), "max_iterations")["value"] == 9


def test_unknown_key_refuses_and_writes_nothing(home):
    before = read_settings(home)
    for changes in ({"subagent_auto_approve": True}, {"max_iterations": "many"}, {"orchestrator_enabled": 1}):
        with pytest.raises(SubagentError) as invalid:
            write_settings(home, before["revision"], changes)
        assert invalid.value.reason == Refusal.INVALID
    text = (home / "config.yaml").read_text(encoding="utf-8")
    assert "subagent_auto_approve" not in text and "many" not in text and "orchestrator_enabled" not in text


def test_value_is_the_getter_result_not_the_file_or_env(home, monkeypatch):
    """``value`` is what the next child gets: upstream's getter floors 0 to 1, and the knob's env
    fallback is shadowed by DEFAULT_CONFIG's own value (measured 2026-10-19), so it never shows."""
    (home / "config.yaml").write_text("delegation:\n  max_spawn_depth: 0\n", encoding="utf-8")
    monkeypatch.setenv("DELEGATION_MAX_CONCURRENT_CHILDREN", "7")
    reply = read_settings(home)
    depth = _field(reply, "max_spawn_depth")
    assert (depth["value"], depth["configured"], depth["source"]) == (1, 0, "profile")
    children = _field(reply, "max_concurrent_children")
    assert (children["value"], children["configured"], children["source"]) == (10, None, "native_default")


def test_null_deletes_and_every_field_is_on_the_wire(home):
    before = read_settings(home)
    assert [field["key"] for field in before["fields"]] == [field.key for field in DELEGATION_FIELDS]
    assert all(field["value"] is not None and field["default"] is not None for field in before["fields"])
    after = write_settings(home, before["revision"], {"max_iterations": None, "worktree_isolation": True})
    assert _field(after, "max_iterations")["source"] == "native_default"
    assert _field(after, "worktree_isolation")["configured"] is True
    assert after["revision"] != before["revision"]


def test_native_route_reads_its_recorded_home_without_a_worker(runtime):
    service, factory, root = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    calls = list(worker.calls)
    reply = service.subagents(scope, sid, "settings", {})
    assert (reply["session_id"], reply["profile"], reply["profile_label"]) == (sid, "a", "a")
    saved = service.subagents(scope, sid, "settings.set", {"expected_generation": reply["generation"],
        "expected_revision": reply["revision"], "changes": {"model": "child-model"}})
    assert saved["generation"] == reply["generation"] and _field(saved, "model")["value"] == "child-model"
    assert "child-model" in (root / "a" / "config.yaml").read_text(encoding="utf-8")
    assert worker.calls == calls
    with pytest.raises(SubagentError):
        service.subagents(scope, sid, "settings.set", {"expected_generation": "forged",
            "expected_revision": saved["revision"], "changes": {"model": "x"}})


def test_operator_route_defaults_and_serve_wide_pause(placed_agent):
    from tools.delegate_tool_registry import is_spawn_paused, set_spawn_paused

    params = target(placed_agent["persona_instance_id"])
    reply = inspect("subagents.settings", params)
    assert "result" in reply, reply
    reply = reply["result"]
    assert reply["scope"] == "profile_defaults" and len(reply["fields"]) == len(DELEGATION_FIELDS)
    host = inspect("subagents.spawning", params)["result"]
    assert (host["host_kind"], host["paused"]) == ("operator_runtime", False)
    guard = {**params, "expected_generation": host["generation"]}
    try:
        paused = inspect("subagents.spawning.set", {**guard, "host_ref": host["host_ref"], "paused": True})["result"]
        assert paused["paused"] is True and paused["host_ref"] == host["host_ref"] and is_spawn_paused()
        assert "error" in inspect("subagents.spawning.set", {**guard, "host_ref": "old-host", "paused": False})
    finally:
        set_spawn_paused(False)
