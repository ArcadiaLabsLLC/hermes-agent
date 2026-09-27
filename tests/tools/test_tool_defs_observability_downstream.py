"""Fork-owned: ``model_tools._compute_tool_definitions`` carries the standalone
``tool_describe`` whenever the tool-search assembly runs (``tools/tool_defs_observability.py``,
lane FOOTPRINT-DROP 2026-09-27)."""

from __future__ import annotations

import model_tools


def _names(**kwargs) -> list[str]:
    tools = model_tools._compute_tool_definitions(enabled_toolsets=["file"], quiet_mode=True, **kwargs)
    return [tool["function"]["name"] for tool in tools]


def test_tool_describe_is_injected_when_the_assembly_runs():
    assert "tool_describe" in _names(skip_tool_search_assembly=False)


def test_positive_control_a_skipped_assembly_gets_no_injection():
    assert "tool_describe" not in _names(skip_tool_search_assembly=True)
