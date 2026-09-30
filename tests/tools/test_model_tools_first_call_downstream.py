"""Fork half (h10b-fix, owner 2026-09-29): the FIRST tool list of a home carries plugin tools.

The conftest gives every test a fresh HERMES_HOME and resets the per-home plugin managers, which is
the shape of a process serving a second profile: ``model_tools``' import-time discovery ran for
another home. ``skill_search`` is registered by the eternia-harness plugin into ``skills``.
"""

from model_tools import get_tool_definitions


def _names(**kw):
    return {t["function"]["name"] for t in get_tool_definitions(quiet_mode=True, **kw)}


def test_first_tool_list_of_a_home_carries_plugin_tools():
    assert "skill_search" in _names(enabled_toolsets=["skills"])


def test_the_plugin_tool_is_in_the_toolset_once_discovered():
    """Positive control: after an explicit discovery the same toolset carries it."""
    from hermes_cli.plugins import discover_plugins

    discover_plugins()
    assert "skill_search" in _names(enabled_toolsets=["skills"])
