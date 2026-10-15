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


def _misses():
    from tools.tool_defs_observability import _tool_defs_counters

    return getattr(_tool_defs_counters, "misses", 0)


def test_the_first_tool_list_of_a_home_is_built_once():
    """The discovery that a first list triggers bumps the registry generation; the memo is keyed
    after it, so the SAME request a second time is a hit, not a second build."""
    from model_tools import _clear_tool_defs_cache

    _clear_tool_defs_cache()
    before = _misses()
    _names(enabled_toolsets=["skills"])
    _names(enabled_toolsets=["skills"])
    assert _misses() - before == 1


def test_a_different_request_is_still_a_miss():
    """Positive control for the counter above: a second, different request builds again."""
    from model_tools import _clear_tool_defs_cache

    _clear_tool_defs_cache()
    before = _misses()
    _names(enabled_toolsets=["skills"])
    _names(enabled_toolsets=["file"])
    assert _misses() - before == 2
