"""The cost layer's account: every requested name has exactly one disposition and one reason.

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §3
slice 3. The fixture is the recorded Neko lane ``test_chat_lane_defer`` carries, plus the fork's
own harness tools registered into their real toolsets (``agent_chat``, ``board``) and the lane's
admitted ``launcher_qa`` server — so the requested set comes from upstream's own toolset
definitions (``toolsets.resolve_toolset``) and every rule the note names has a name to move.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.agent_runtime.test_chat_lane_defer import _BUILTINS, _MCP_VERBS, NEKO_DEFER, _names
from tests.tools.test_tool_search import _td
from tests.tools.test_tool_search_downstream import _launcher_qa_registration

#: The fork's harness tools, by the toolset each registers into (``tools/toolset_manifest.json``).
HARNESS_TOOLS = {
    "agent_chat_open": "agent_chat", "agent_chat_threads": "agent_chat",
    "agent_chat_installs": "agent_chat", "agent_chat_log_path": "agent_chat",
    "harness_query": "agent_chat", "board_cards": "board", "board_card_add": "board",
}
ENABLED = ["harness_core", "mcp-launcher_qa"]
OPEN_APP_TAB = "mcp__launcher_qa__mcp_launcher_qa_open_app_tab"
CAPTURE = "mcp__launcher_qa__mcp_launcher_qa_capture_screenshot"


@pytest.fixture
def harness_lane(monkeypatch):
    """``SimpleNamespace(raw, build_agent, registry)``: the recorded lane as the factory reads it."""

    import model_tools
    import tools.tool_search as ts
    from agent_runtime.chat_lane_tool_form import clear_tool_form_memo

    with _launcher_qa_registration() as (registry, registered):
        for name, toolset in HARNESS_TOOLS.items():
            registry.register(name=name, toolset=toolset, schema={"name": name, "description": name},
                              handler=lambda args, **kw: "{}")
        mcp = [_td(name, f"launcher_qa {name}.") for name in registered
               if any(name.endswith(f"__{verb}") for verb in _MCP_VERBS)]
        raw = [_td(name, f"{name} does its job.") for name in (*_BUILTINS, *HARNESS_TOOLS)] + mcp
        monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **_kw: list(raw))
        monkeypatch.setattr(ts, "load_config", lambda: ts.ToolSearchConfig.from_raw(None))
        monkeypatch.setattr(ts, "_profile_config_readonly", lambda: ts.ToolSearchConfig.from_raw(None))
        clear_tool_form_memo()

        def build_agent():
            """The constructor's form: the profile-wide assembly, as upstream builds it."""
            tools = ts.assemble_tool_defs(list(raw), context_length=272_000,
                                          config=ts.ToolSearchConfig.from_raw(None)).tool_defs
            return SimpleNamespace(
                tools=tools, valid_tool_names=_names(tools), enabled_toolsets=list(ENABLED),
                disabled_toolsets=None, context_compressor=SimpleNamespace(context_length=272_000),
            )

        yield SimpleNamespace(raw=raw, build_agent=build_agent, registry=registry)
        clear_tool_form_memo()


def _surface(defer=NEKO_DEFER, **kw):
    from agent_runtime.tool_surface import compute_tool_surface

    return compute_tool_surface(enabled_toolsets=ENABLED, defer_tools=defer, **kw).receipt()


def test_every_requested_name_has_exactly_one_disposition(harness_lane):
    from agent_runtime.tool_surface import STATES, requested_tool_names
    from tools.tool_search import BRIDGE_TOOL_NAMES

    receipt = _surface(blocked_tool_names=("skill_manage",))
    universe = (requested_tool_names(ENABLED) | _names(harness_lane.raw)) - BRIDGE_TOOL_NAMES
    seen: dict[str, list[str]] = {}
    for state in STATES:
        for name in receipt[state]:
            seen.setdefault(name, []).append(state)
    twice = {name: states for name, states in seen.items() if len(states) > 1}
    assert not twice, f"a name in two states: {twice}"
    assert set(seen) == universe, (
        f"unaccounted={sorted(universe - set(seen))} invented={sorted(set(seen) - universe)}")
    # Anti-vacuity: every state is populated on this lane, so the partition is a real one.
    assert all(receipt["counts"][state] for state in STATES), receipt["counts"]


def test_each_absent_name_carries_the_rule_that_moved_it(harness_lane):
    receipt = _surface()
    reasons = {name: row["reason"] for state in ("eager", "deferred") for name, row in receipt[state].items()}
    assert reasons["todo_list"] == "curated_default_defer"
    assert reasons["browser_vault_list"] == "persona_defer"
    assert receipt["deferred"]["browser_vault_list"]["restorable_via"].endswith("chat_lane_defer_tools")
    assert reasons["agent_chat_open"] == "non_core_rule_defer", "R3: the fork's harness tools defer by upstream's rule"
    assert reasons[CAPTURE] == "mcp_defer"
    assert OPEN_APP_TAB in receipt["eager"] and reasons[OPEN_APP_TAB] == "promoted_eager"
    # Positive control: off the persona's list, the core tool is eager — the list moved it.
    control = _surface(defer=tuple(n for n in NEKO_DEFER if n != "browser_vault_list"))
    assert control["eager"]["browser_vault_list"] == {"reason": None}


def test_the_cost_layer_never_adds_a_name(harness_lane):
    import toolsets

    receipt = _surface()
    callable_names = set().union(*(toolsets.resolve_toolset(t) for t in ENABLED)) | _names(harness_lane.raw)
    added = (set(receipt["eager"]) | set(receipt["deferred"])) - callable_names
    assert not added, f"the cost layer added {sorted(added)}"
    assert receipt["bridge"] == ["tool_call", "tool_describe", "tool_search"]


def test_a_faulted_assembly_is_recorded_not_swallowed(harness_lane, monkeypatch):
    import tools.tool_search as ts
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR

    agent = harness_lane.build_agent()
    before = list(agent.tools)

    def _boom(*_a, **_kw):
        raise RuntimeError("assembly fault")

    monkeypatch.setattr(ts, "assemble_tool_defs", _boom)
    assert apply_chat_lane_defer(agent, NEKO_DEFER) is False
    assert agent.tools == before, "the constructor form stands"
    receipt = getattr(agent, AGENT_SURFACE_ATTR, None)
    assert receipt is not None, "the fault left no receipt: a WARNING line is the only record"
    assert receipt["degraded"] == ["assembly:RuntimeError"]
    assert set(receipt["eager"]) == _names(before) - {"tool_search", "tool_call", "tool_describe"}


def test_the_browser_use_swap_is_an_unavailable_row(harness_lane, monkeypatch):
    """The recorded lane carries ``browser_exec`` (``browser.backend: browser-use``): upstream's
    ``browser`` toolset lists every ``browser_*`` core tool by name, check_fn keeps
    ``browser_exec`` (registered into ``browser-use``) and drops the rest."""

    import toolsets
    import model_tools

    swapped = sorted(
        name for name in set(toolsets.resolve_toolset("browser")) | set(toolsets.resolve_toolset("browser-cdp"))
        if name not in _names(harness_lane.raw)
    )
    receipt = _surface()
    assert len(swapped) >= 11, swapped
    assert {name: receipt["unavailable"][name]["reason"] for name in swapped} == {
        name: "backend_swap" for name in swapped}
    # The swap target is on the surface: Neko defers it by name (R1 of the prompt-surface plan),
    # so it rides the listing — available, not eager (the note's "eager" predates that list).
    assert receipt["deferred"]["browser_exec"]["reason"] == "persona_defer"
    # Positive control: without the swap target on the surface the same names are check_fn rows.
    raw = [td for td in harness_lane.raw if td["function"]["name"] != "browser_exec"]
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **_kw: list(raw))
    control = _surface()
    assert {control["unavailable"][name]["reason"] for name in swapped} == {"check_fn_unavailable"}


def test_tool_search_off_is_a_reason_not_a_silence(harness_lane):
    import tools.tool_search as ts

    off = replace(ts.ToolSearchConfig.from_raw(None), enabled="off")
    receipt = _surface(tool_search_config=off)
    assert receipt["tool_search"] == "off"
    assert receipt["deferred"] == {} and receipt["bridge"] == []
    for name in ("todo_list", "browser_vault_list", "agent_chat_open", CAPTURE):
        assert receipt["eager"][name] == {"reason": "tool_search_off"}, name
    # Positive control: a tool no rule would defer is eager with no reason, off or not.
    assert receipt["eager"]["terminal"] == {"reason": None}
