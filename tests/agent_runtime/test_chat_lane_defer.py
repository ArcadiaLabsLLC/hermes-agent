"""The chat lane's per-persona defer (lane h-prompt-tools S1, rulings R1/R2).

Plan: ``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md`` §1 S1. The
fixture is the tool set Neko's recorded first request carried (``ctx_96cd09894da6e457``,
31 entries), rebuilt as definitions: what each persona keeps eager after the defer is
pinned BY NAME against the ruling, and every deferred tool must stay reachable through
the bridge — found by ``tool_search``, resolved by ``tool_call``.
"""

from __future__ import annotations

import json
import textwrap
from types import SimpleNamespace

import pytest

from tests.tools.test_tool_search import _td
from tests.tools.test_tool_search_downstream import _launcher_qa_registration

#: The 27 non-MCP, non-bridge tools of the recorded request, plus two curated deferrals.
_BUILTINS = (
    "agent_chat_dispatches", "agent_chat_send", "browser_exec", "browser_vault_enter_code",
    "browser_vault_fill", "browser_vault_list", "browser_vault_save_login", "browser_vault_unlock",
    "clarify", "delegate_task", "execute_code", "memory", "patch", "read_file", "search_files",
    "skill_manage", "skill_search", "skill_view", "skills_list", "terminal", "vision_analyze",
    "web_extract", "web_search", "write_file", "process_manage", "todo_list",
)
_MCP_VERBS = (
    "mcp_launcher_qa_open_app_tab", "mcp_launcher_qa_screenshot_window",
    "mcp_launcher_qa_launch_or_attach", "mcp_launcher_qa_capture_screenshot",
    "mcp_launcher_qa_click_button",
)

#: R1: what the supervisor's chat lane never calls (§0.3), and the dev persona's subset.
NEKO_DEFER = (
    "delegate_task", "skill_manage", "browser_exec", "browser_vault_list", "browser_vault_unlock",
    "browser_vault_fill", "browser_vault_save_login", "browser_vault_enter_code", "memory",
    "execute_code", "web_extract", "web_search", "write_file", "patch", "vision_analyze",
)
DEV_DEFER = tuple(n for n in NEKO_DEFER if n not in {"patch", "write_file", "execute_code", "web_search", "web_extract"})

_LAUNCHER_QA_EAGER = {
    "mcp__launcher_qa__mcp_launcher_qa_open_app_tab",
    "mcp__launcher_qa__mcp_launcher_qa_screenshot_window",
    "mcp__launcher_qa__mcp_launcher_qa_launch_or_attach",
}
#: R1 + R2: the supervisor's eager set — fifteen tools.
NEKO_EAGER = {
    "terminal", "read_file", "search_files", "skill_view", "skills_list", "clarify",
    "agent_chat_send", "agent_chat_dispatches", "skill_search",
    "tool_search", "tool_call", "tool_describe", *_LAUNCHER_QA_EAGER,
}
DEV_EAGER = NEKO_EAGER | {"patch", "write_file", "execute_code", "web_search", "web_extract"}


def _names(defs) -> set[str]:
    return {d["function"]["name"] for d in defs}


@pytest.fixture
def lane(monkeypatch):
    """The recorded lane's raw definitions, the launcher_qa server registered through the real
    MCP path, the profile's tool-search config at its defaults; yields ``(raw, build_agent)``."""

    import model_tools
    import tools.tool_search as ts

    with _launcher_qa_registration() as (_registry, registered):
        mcp = [_td(name, f"launcher_qa {name}.") for name in registered
               if any(name.endswith(f"__{verb}") for verb in _MCP_VERBS)]
        raw = [_td(name, f"{name} does its job.") for name in _BUILTINS] + mcp
        monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **_kw: list(raw))
        monkeypatch.setattr(ts, "load_config", lambda: ts.ToolSearchConfig.from_raw(None))
        monkeypatch.setattr(ts, "_profile_config_readonly", lambda: ts.ToolSearchConfig.from_raw(None))

        def build_agent():
            """The constructor's form: the profile-wide assembly, as upstream builds it."""
            tools = ts.assemble_tool_defs(list(raw), context_length=272_000,
                                          config=ts.ToolSearchConfig.from_raw(None)).tool_defs
            return SimpleNamespace(
                tools=tools, valid_tool_names=_names(tools), enabled_toolsets=["harness_core"],
                disabled_toolsets=None, context_compressor=SimpleNamespace(context_length=272_000),
            )

        yield raw, build_agent


def test_the_recorded_lane_carries_thirty_tools_before_the_defer(lane):
    """Anti-vacuity: the fixture reproduces the recorded request's 31 eager tools, less the one
    launcher_qa promotion R2 retired."""
    _raw, build_agent = lane
    agent = build_agent()
    assert len(agent.tools) == 30, sorted(_names(agent.tools))
    assert "mcp__launcher_qa__mcp_launcher_qa_capture_screenshot" not in _names(agent.tools), (
        "R2: capture_screenshot rides the listing, not the eager array")


@pytest.mark.parametrize(("defer", "eager"), [(NEKO_DEFER, NEKO_EAGER), (DEV_DEFER, DEV_EAGER)],
                         ids=["neko_supervisor", "dev"])
def test_each_persona_ships_exactly_its_ruled_eager_set(lane, defer, eager):
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer

    _raw, build_agent = lane
    agent = build_agent()
    assert apply_chat_lane_defer(agent, defer) is True
    assert _names(agent.tools) == eager, (
        f"extra={sorted(_names(agent.tools) - eager)} missing={sorted(eager - _names(agent.tools))}")
    assert agent.valid_tool_names == eager
    listing = next(d for d in agent.tools if d["function"]["name"] == "tool_search")["function"]["description"]
    for name in defer:
        assert name in listing, f"{name} deferred but not named in the tool_search listing"


def test_a_deferred_tool_is_found_and_callable_through_the_bridge(lane):
    """The bridge reads its config through ``load_config_readonly``; the turn's scope adds the
    persona's names there, and ONLY there — the assembly loader never sees them."""
    import tools.tool_search as ts
    from tools.tool_search_downstream import scoped_turn_defer

    raw, _build_agent = lane
    call = {"calls": [{"name": "memory", "arguments": {}}]}
    assert ts.resolve_underlying_call(call)[2], "control: outside the turn, memory is core — not bridge-callable"
    with scoped_turn_defer(NEKO_DEFER):
        name, _args, err = ts.resolve_underlying_call(call)
        assert (name, err) == ("memory", None)
        assert "memory" in ts.scoped_deferrable_names(raw)
        found = json.loads(ts.dispatch_tool_search({"queries": ["memory"]}, current_tool_defs=raw))
        assert "memory" in found["tools"], found
        described = json.loads(ts.dispatch_tool_describe({"names": ["memory"]}, current_tool_defs=raw))
        assert "memory" in described["tools"], described
        assert "memory" not in ts.load_config().effective_defer_tools, (
            "the persona's set reached the assembly loader, whose output is memoized per toolset")
    assert "memory" not in ts.load_config_readonly().effective_defer_tools


def test_a_refresh_that_restores_the_profile_form_is_undone_before_the_next_request(lane):
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer, settle_turn_tool_form

    _raw, build_agent = lane
    agent = build_agent()
    apply_chat_lane_defer(agent, (*NEKO_DEFER, "agent_chat_send"))
    assert "agent_chat_send" in agent.valid_tool_names, "never-defer wins over the persona list"
    assert settle_turn_tool_form(agent, pin=False).source == "unchanged", (
        "a promoted name must not re-trigger a publish")
    fresh = build_agent()  # what tools/mcp_tool_agent publishes on a refresh
    agent.tools, agent.valid_tool_names = fresh.tools, fresh.valid_tool_names
    receipt = settle_turn_tool_form(agent, pin=False)
    assert (receipt.source, receipt.published) == ("memo", True), receipt
    assert _names(agent.tools) == NEKO_EAGER


def test_no_list_leaves_the_constructor_form_alone(lane):
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer

    _raw, build_agent = lane
    agent = build_agent()
    before = list(agent.tools)
    assert apply_chat_lane_defer(agent, None) is False
    assert agent.tools == before


def test_the_knob_is_read_per_persona_from_the_root_config(tmp_path):
    from agent_runtime.config.knobs import chat_lane_defer_tools
    from agent_runtime.config.loader import load_agent_runtime_config

    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent("""\
        agent_runtime:
          personas:
            neko_supervisor:
              chat_lane_defer_tools: [memory, delegate_task]
            dev:
              chat_lane_restore_toolsets: [file]
        """), encoding="utf-8")
    cfg = load_agent_runtime_config(path)
    assert chat_lane_defer_tools("neko_supervisor", cfg) == ["memory", "delegate_task"]
    assert chat_lane_defer_tools("dev", cfg) == []
    assert chat_lane_defer_tools("", cfg) == []


def test_the_bundle_carries_the_list_in_the_tool_contract(monkeypatch):
    """The contract feeds the resident actor's signature: a changed list rebuilds the actor."""
    from agent_runtime import chat_lane_bundle as CLB
    from agent_runtime.models import AgentPersona
    from agent_runtime.tool_visibility import _ensure_tool_registry_populated

    _ensure_tool_registry_populated()
    monkeypatch.setattr(CLB, "chat_lane_defer_tools", lambda persona_id: ["memory", "delegate_task"])
    CLB.invalidate_chat_lane_bundles()
    persona = AgentPersona(id="neko_supervisor", display_name="Neko", role="supervisor", model=None,
                           provider=None, api_mode="codex_responses", toolsets=["skills"],
                           system_prompt_path="personas/neko/system.md")
    bundle = CLB.chat_lane_bundle(persona, session_id="chat-defer")
    assert bundle.defer_tools == ("delegate_task", "memory")
    assert bundle.tool_contract()["chat_lane_defer_tools"] == ["delegate_task", "memory"]
