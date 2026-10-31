"""The board tools ride eager: an agent the HUD tells a board exists can see how to use it.

``RT-BOARD-TOOLS-NOT-EVIDENT``. The runtime HUD's "- Board: …" line advertises a workspace board
(``agent_runtime.runtime_hud.hud``); the tools that act on it are upstream plugin tools in the
``board`` toolset, which the bridge would otherwise defer behind ``tool_search``. They are on the
fork's never-defer set, which wins over a curated or a per-persona defer list.
"""

from __future__ import annotations

from tests.tools.test_tool_search import _td


def _assembled_names(defer: frozenset[str], names: list[str]) -> tuple[set[str], set[str]]:
    """``(eager, deferred)`` names after upstream's assembly with ``defer`` curated in."""

    from dataclasses import replace

    from tools.tool_search import BRIDGE_TOOL_NAMES, ToolSearchConfig, assemble_tool_defs

    config = replace(ToolSearchConfig.from_raw({"enabled": "on"}), defer_tools=defer)
    result = assemble_tool_defs([_td(name, f"{name} tool") for name in names], config=config)
    eager = {td["function"]["name"] for td in result.tool_defs} - set(BRIDGE_TOOL_NAMES)
    return eager, set(names) - eager


def test_the_never_defer_board_set_is_every_tool_the_board_toolset_registers():
    import tools.board_tool
    from tools.registry import registry
    from tools.tool_search_downstream import BOARD_TOOLS

    registered = set(registry.get_tool_names_for_toolset("board"))
    assert registered, "the board toolset registers no tool"
    assert set(BOARD_TOOLS) == registered


def test_a_board_tool_stays_eager_even_when_a_persona_defers_it():
    import tools.board_tool
    from tools.tool_search_downstream import BOARD_TOOLS

    neighbour = "cronjob"  # a registered tool the same defer list really does defer
    eager, deferred = _assembled_names(frozenset({*BOARD_TOOLS, neighbour}), [*sorted(BOARD_TOOLS), neighbour])

    assert set(BOARD_TOOLS) <= eager
    # Positive control: the same list, the same assembly, a non-board name — deferred.
    assert neighbour in deferred
