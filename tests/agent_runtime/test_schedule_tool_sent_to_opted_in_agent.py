"""``RT-SCHEDULE-TOOL-HIDDEN-FROM-OPTED-IN-AGENT``: an agent opted into scheduling is SENT its tool.

Seen live 2026-11-12 (Eternia lane w1112b-work3, hermes 7bb8dbd9f6): a persona whose bound profile
declares ``toolsets: [harness_core, schedule]`` was sent 35 tools on three turns and ``schedule_manage``
was not among them. The declaration was read correctly (``declared_lane_toolsets``: ``profile_config``,
``schedule`` in it) and the tool was registered — but it is a plugin tool, and upstream's assembly defers
every plugin tool behind ``tool_search`` (the turn's surface: 32 eager, 226 deferred, the count one higher
than before the opt-in). An agent told it may schedule had to guess a search to find how.

``schedule_manage`` is on the fork's never-defer set now. It exists only in a run whose profile declares
``schedule``, so naming it there un-hides it for exactly those agents and grants nothing to anyone else.

Nothing between the profile and the model's list is faked: the profile's ``config.yaml`` is a real file
read by ``declared_lane_toolsets``, the plugin is discovered as agent init does, and the list is
``model_tools.get_tool_definitions`` over the declared toolsets.

Killing mutation (recorded red in the commit body): drop ``SCHEDULE_TOOLS`` from ``_BUILTIN_NEVER_DEFER``
→ ``test_an_agent_opted_into_scheduling_is_sent_schedule_manage`` red.
"""

from __future__ import annotations

import textwrap

import pytest

from agent_runtime.models import AgentPersona
from agent_runtime.parse_cache import clear_parse_cache
from agent_runtime.persona_profiles import declared_lane_toolsets
from agent_runtime.personas import TOOLSET_SOURCE_PROFILE_CONFIG


@pytest.fixture
def sent_tools(bundled_persona_profiles):
    """``config body -> the tool names a turn of the persona bound to that profile sends the model``."""

    from hermes_cli.plugins import discover_plugins
    from hermes_cli.profiles import get_profile_dir
    from model_tools import _clear_tool_defs_cache, get_tool_definitions

    def _sent(body: str) -> set[str]:
        home = get_profile_dir("gpt-launcher")
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
        clear_parse_cache()
        persona = AgentPersona(id="dev", display_name="Dev", role="dev", model=None, provider=None,
                               api_mode="codex_responses", system_prompt_path="", hermes_profile="gpt-launcher")
        declaration = declared_lane_toolsets(persona)
        assert declaration.source == TOOLSET_SOURCE_PROFILE_CONFIG, declaration.row()
        discover_plugins()
        _clear_tool_defs_cache()
        defs = get_tool_definitions(enabled_toolsets=list(declaration.toolsets), quiet_mode=True)
        return {d["function"]["name"] for d in defs}

    return _sent


def test_an_agent_opted_into_scheduling_is_sent_schedule_manage(sent_tools):
    names = sent_tools("toolsets:\n  - harness_core\n  - schedule\n")
    assert "tool_search" in names, "the lane defers behind tool_search: the case the live turn ran in"
    assert "schedule_manage" in names, "declared, registered, and still not in the list the model is sent"


def test_an_agent_not_opted_in_is_not_sent_it(sent_tools):
    """The never-defer set grants nothing: without ``schedule`` in the profile the tool is not there at all."""

    names = sent_tools("toolsets:\n  - harness_core\n  - discord\n")
    assert "terminal" in names and "schedule_manage" not in names


def test_the_never_defer_schedule_set_is_every_tool_the_schedule_toolset_registers():
    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry
    from tools.tool_search_downstream import SCHEDULE_TOOLS, never_defer_tool_names

    discover_plugins()
    registered = set(registry.get_tool_names_for_toolset("schedule"))
    assert registered, "the schedule toolset registers no tool"
    assert set(SCHEDULE_TOOLS) == registered and set(SCHEDULE_TOOLS) <= never_defer_tool_names()
