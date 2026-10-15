"""The no-progress guard sees the filesystem MCP read tools under the name the registry gives them."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent import tool_guardrails
from tools.mcp_tool_schema import mcp_prefixed_tool_name


@pytest.fixture
def restore_idempotent_names(monkeypatch):
    monkeypatch.setattr(tool_guardrails, "IDEMPOTENT_TOOL_NAMES", tool_guardrails.IDEMPOTENT_TOOL_NAMES)


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_guardrail_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NullCtx:
    def __getattr__(self, name):
        return lambda *a, **k: None


def test_plugin_register_makes_the_registry_spelled_read_tools_idempotent(restore_idempotent_names):
    _plugin().register(_NullCtx())
    config = tool_guardrails.ToolCallGuardrailConfig()
    for name in ("read_file", "directory_tree", "search_files"):
        assert mcp_prefixed_tool_name("filesystem", name) in config.idempotent_tools
    assert "read_file" in config.idempotent_tools  # upstream's own names are kept


def test_a_replayed_registry_spelled_read_is_blocked_as_no_progress(restore_idempotent_names):
    from agent_runtime.guardrail_mcp_names import add_registry_spelled_filesystem_reads

    add_registry_spelled_filesystem_reads()
    config = tool_guardrails.ToolCallGuardrailConfig(hard_stop_enabled=True)
    guard = tool_guardrails.ToolCallGuardrailController(config)
    name = mcp_prefixed_tool_name("filesystem", "read_file")
    args = {"path": "a.txt"}
    for _ in range(config.no_progress_block_after):
        assert guard.before_call(name, args).action != "block"
        guard.after_call(name, args, "same bytes", failed=False)
    assert guard.before_call(name, args).action == "block"
