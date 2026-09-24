"""The eternia-harness plugin's defaults: background notify at spawn, the kanban claim TTL."""

from __future__ import annotations

import pytest

from agent_runtime.background_completion import default_background_notify


def test_a_background_spawn_that_says_nothing_gets_notify_on():
    args = {"command": "make", "background": True}
    assert default_background_notify("terminal", args) == {**args, "notify": True}
    assert "notify" not in args  # the caller's dict is not mutated


@pytest.mark.parametrize(
    "explicit",
    [{"notify": False}, {"notify": ["ready"]}, {"notify_on_complete": False}, {"watch_patterns": ["x"]}],
)
def test_a_spawn_that_decided_for_itself_is_left_alone(explicit):
    assert default_background_notify("terminal", {"command": "x", "background": True, **explicit}) is None


def test_foreground_and_other_tools_are_untouched():
    assert default_background_notify("terminal", {"command": "ls"}) is None
    assert default_background_notify("process_manage", {"background": True}) is None


def _plugin():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NullCtx:
    def __getattr__(self, name):
        return lambda *a, **k: None


def test_register_defaults_the_kanban_claim_ttl_and_the_operator_env_wins(monkeypatch):
    """Upstream's `HERMES_KANBAN_CLAIM_TTL_SECONDS` is the door (claims AND heartbeats)."""
    from hermes_cli import kanban_db

    monkeypatch.delenv("HERMES_KANBAN_CLAIM_TTL_SECONDS", raising=False)
    _plugin().register(_NullCtx())
    assert kanban_db._resolve_claim_ttl_seconds() == 45 * 60

    monkeypatch.setenv("HERMES_KANBAN_CLAIM_TTL_SECONDS", "120")
    _plugin().register(_NullCtx())
    assert kanban_db._resolve_claim_ttl_seconds() == 120


def test_the_plugin_applies_it_through_tool_request_middleware(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_CLAIM_TTL_SECONDS", raising=False)
    module = _plugin()
    registered = []

    class _Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: registered.append((name, a)) if name == "register_middleware" else None

    module.register(_Ctx())
    callbacks = {a[0]: a[1] for name, a in registered}
    result = callbacks["tool_request"](tool_name="terminal", args={"command": "x", "background": True})
    assert result["args"]["notify"] is True
