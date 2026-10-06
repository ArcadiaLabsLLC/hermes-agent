"""A chat's turn 1 and turn 2 send one tools prefix and one prompt-cache key (lane h-cache-hit).

Live evidence (Neko, 2026-10-05 22:51 and 2026-10-06 00:15): turn 1's ``prompt_cache_key`` was
the hash of a ``tool_search`` reading "Search 48 additional tools" (the prewarm's catalog, before
the Launcher's app functions registered) plus the five ``browser_vault_*`` tools the persona
defers, ridden eager; turn 2's was the same tools with "Search 58" -- upstream's between-turns
refresh re-appends the deferred tools, and the fork's re-prune re-assembled the bridge only after
the request was built. The fix settles the persona's form in a ``pre_llm_call`` hook, between the
refresh and the request (``plugins/eternia-harness::settle_turn_tools``).

The turns here run the real pieces in upstream's order: the actor built and deferred
(``apply_chat_lane_defer``), the between-turns refresh (``refresh_agent_mcp_tools``,
``preserve_prefix=True``), the plugin's ``pre_llm_call`` hook, the request from ``agent.tools``
in the Responses shape, then the plugin's ``llm_request`` middleware (briefs + cache routing).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.agent_runtime.test_chat_lane_defer import _names, lane  # noqa: F401 — the fixture
from tests.tools.test_tool_search import _td

VAULT = ("browser_vault_list", "browser_vault_unlock", "browser_vault_fill",
         "browser_vault_save_login", "browser_vault_enter_code")
#: A deferred tool that registers AFTER the prewarm built the actor (the live case: the
#: Launcher's ten app functions, absent from the 22:51:19 prewarm's 43/48 catalog).
LATE_TOOL = "session_search"
SYSTEM = "You are Neko. The stable system prompt."


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_cache_hit_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def chat(lane, monkeypatch):  # noqa: F811 — the imported fixture
    """``(new_actor, turn)``: actors built and deferred as the chat lane builds them, and one
    turn's wire -- ``(responses tools, persona cache routing observability)``."""
    import model_tools
    import tools.tool_search as ts
    from agent.codex_responses_adapter import _responses_tools
    from agent_runtime.cache_routing import persona_cache_scope_id
    from agent_runtime.chat_lane_defer import apply_chat_lane_defer
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from tools.mcp_tool_agent import refresh_agent_mcp_tools

    raw, _build = lane
    config = ts.ToolSearchConfig.from_raw(None)
    # Upstream's get_tool_definitions: the profile-wide assembly, unless the caller skips it.
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **kw: list(raw) if kw.get(
        "skip_tool_search_assembly") else ts.assemble_tool_defs(list(raw), context_length=272_000,
                                                                config=config).tool_defs)
    monkeypatch.setattr("tools.mcp_tool_discovery.has_registered_mcp_tools", lambda: True)
    plugin = _plugin()
    routed = {}
    monkeypatch.setattr("agent_runtime.cache_routing.route_persona_cache",
                        lambda request, **_kw: routed.setdefault("request", request) and None)

    def new_actor(session_id: str):
        tools = model_tools.get_tool_definitions(enabled_toolsets=["harness_core"])
        agent = SimpleNamespace(
            tools=tools, valid_tool_names=_names(tools), enabled_toolsets=["harness_core"],
            disabled_toolsets=None, context_compressor=SimpleNamespace(context_length=272_000),
            session_id=session_id, cache_scope_id=persona_cache_scope_id("personainst_neko_1", session_id),
        )
        assert apply_chat_lane_defer(agent, VAULT) is True
        return agent

    def turn(agent):
        from agent_runtime.cache_routing import apply_persona_cache_routing

        refresh_agent_mcp_tools(agent, quiet_mode=True, preserve_prefix=True)
        with bind_persona_turn_agent(agent):
            plugin.settle_turn_tools(session_id=agent.session_id)
            request = {"model": "gpt-5.6-luna", "instructions": SYSTEM,
                       "tools": _responses_tools(agent.tools), "prompt_cache_key": "x"}
            plugin.brief_tool_descriptions(request, api_mode="codex_responses", session_id=agent.session_id)
        wire = routed.pop("request")
        _, observability = apply_persona_cache_routing(
            wire, cache_scope_id=agent.cache_scope_id, session_id=agent.session_id,
            is_codex_backend=True, is_github_responses=False, is_xai_responses=False)
        return wire["tools"], observability

    return new_actor, turn, raw


def _bytes(tools) -> str:
    return json.dumps(tools, ensure_ascii=False, separators=(",", ":"))


def test_a_prewarmed_chats_turn_one_and_turn_two_send_one_prefix_and_one_key(chat):
    """Positive control (CHANGE commit): drop the ``settle_turn_tools`` call from ``turn``
    (the pre-fix order) -> turn 1 carries the prewarm's bridge and the vault eager, and the
    byte assertion reds."""
    new_actor, turn, raw = chat
    actor = new_actor("chat-a")  # the prewarm, before the late tool registers
    raw.append(_td(LATE_TOOL, f"{LATE_TOOL} does its job."))

    first_tools, first = turn(actor)
    second_tools, second = turn(actor)
    third_tools, third = turn(actor)

    assert _bytes(first_tools) == _bytes(second_tools) == _bytes(third_tools)
    assert first["prompt_cache_key_fingerprint"] == second["prompt_cache_key_fingerprint"] \
        == third["prompt_cache_key_fingerprint"]
    names = {t.get("name") for t in first_tools}
    assert not names & set(VAULT), f"a deferred tool rode the wire eager: {sorted(names & set(VAULT))}"
    listing = next(t for t in first_tools if t.get("name") == "tool_search")["description"]
    assert LATE_TOOL in listing and all(name in listing for name in VAULT)


def test_two_chats_of_one_instance_send_one_prefix_one_key_and_one_scope(chat):
    """Chat A was prewarmed before the late tool registered; chat B was built after. Their
    first turns share the tools prefix, the body key and the instance-scoped Codex header."""
    new_actor, turn, raw = chat
    chat_a = new_actor("chat-a")
    raw.append(_td(LATE_TOOL, f"{LATE_TOOL} does its job."))
    chat_b = new_actor("chat-b")

    a_tools, a = turn(chat_a)
    b_tools, b = turn(chat_b)

    assert _bytes(a_tools) == _bytes(b_tools)
    assert a["prompt_cache_key_fingerprint"] == b["prompt_cache_key_fingerprint"]
    assert a["session_header_fingerprint"] == b["session_header_fingerprint"]
    assert a["cache_scope_source"] == b["cache_scope_source"] == "cache_scope_id"
