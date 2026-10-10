"""The per-part prompt-surface receipt (lane h-prompt-tools S0).

Plan: ``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md`` §1 S0. Every
turn's model-input record says what its request is made of, in chars of the WIRE form:
per tool, per system-prompt block, and the parts summed — so a cut lands against a number.
"""

from __future__ import annotations

import json
import logging
import math
from types import SimpleNamespace

from agent_runtime.profile_runner.model_input_observability import (
    _model_input_observability,
    _prompt_block_receipts,
)
from agent_runtime.profile_runner.models import AgentRunRequest
from tests.tools.test_tool_search import _td

_PROMOTED = "mcp__launcher_qa__mcp_launcher_qa_open_app_tab"
_SYSTEM = (
    "You are Neko.\n\n# Finishing the job\nFinish it.\n\n## Skills\nUse them.\n"
    "<available_skills>\n  creative:\n    - comic: draw\n    - cozy: paint\n"
    "  ops [names only]: a, b\n</available_skills>\n\n<missing_context>\nAsk.\n</missing_context>\n"
)
_HUD = "<runtime_context>\nboard: 3 cards\n</runtime_context>"


def _agent(tools, *, prior_assistant: bool = False):
    messages = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}] if prior_assistant else []
    messages.append({"role": "user", "content": f"hi\n{_HUD}"})
    return SimpleNamespace(
        tools=tools, messages=messages, _persist_user_message_idx=len(messages) - 1,
        _cached_system_prompt=_SYSTEM, valid_tool_names=set(),
    )


def _record(agent):
    return _model_input_observability(
        agent=agent, request=AgentRunRequest(profile="neko", user_message=f"hi\n{_HUD}"))


#: The weight rides a parameter: the wire collapses every description to one line
#: (lane h-prompt-brief) but carries parameter schemas whole.
_HEAVY_PARAMS = {"payload": {"type": "string", "description": "x" * 2000}}


def _tools():
    return [
        _td("read_file", "Read a file."),
        _td("heavy_tool", "Heavy.", _HEAVY_PARAMS),
        _td(_PROMOTED, "Composed Stage C workflow: launch, gate and navigate in one call. " + "More. " * 300),
        _td("tool_search", "Search 2 additional tools.\n\nEvery deferred capability is listed below.\n\n- memory\n- patch"),
    ]


def test_the_heaviest_tool_heads_the_per_tool_map_at_its_wire_size():
    record = _record(_agent(_tools()))
    per_tool = record["tool_schema"]["per_tool_chars"]

    assert next(iter(per_tool)) == "heavy_tool", per_tool
    heavy = _td("heavy_tool", "Heavy.", _HEAVY_PARAMS)
    assert per_tool["heavy_tool"] == len(json.dumps(heavy, ensure_ascii=False, separators=(",", ":")))
    assert list(per_tool.values()) == sorted(per_tool.values(), reverse=True)


def test_the_map_measures_the_wire_brief_not_the_registry_text():
    record = _record(_agent(_tools()))
    raw = _td(_PROMOTED, "Composed Stage C workflow: launch, gate and navigate in one call. " + "More. " * 300)

    assert record["tool_schema"]["per_tool_chars"][_PROMOTED] < len(json.dumps(raw)) // 3
    assert record["prompt_surface"]["promoted_mcp_chars"] == record["tool_schema"]["per_tool_chars"][_PROMOTED]


def test_the_surface_sums_the_parts():
    surface = _record(_agent(_tools()))["prompt_surface"]

    assert surface["tools"] == 4
    assert surface["tool_chars"] == sum(_record(_agent(_tools()))["tool_schema"]["per_tool_chars"].values())
    assert surface["listing_chars"] == len("Every deferred capability is listed below.\n\n- memory\n- patch")
    assert surface["system_chars"] == len(_SYSTEM)
    assert surface["skills_entries"] == 2
    assert surface["hud_chars"] == len(_HUD)
    assert surface["chars_per_token"] == 4


def test_the_log_line_fires_on_the_first_turn_only(caplog):
    logger = "agent_runtime.profile_runner.model_input_observability"
    with caplog.at_level(logging.INFO, logger=logger):
        _record(_agent(_tools()))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("prompt_surface ")]
    assert len(lines) == 1 and " tools=4 " in lines[0] and " skills_entries=2 " in lines[0], lines

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=logger):
        _record(_agent(_tools(), prior_assistant=True))
    assert not [r for r in caplog.records if r.getMessage().startswith("prompt_surface ")]


def test_blocks_split_on_headings_and_keep_a_tag_block_whole():
    blocks = _prompt_block_receipts(_SYSTEM)

    assert [b["heading"] for b in blocks] == [
        "(preamble)", "# Finishing the job", "## Skills", "<available_skills>", "<missing_context>"]
    assert sum(b["chars"] for b in blocks) == len(_SYSTEM)


def test_the_safe_view_keeps_names_and_counts():
    from agent_runtime.prompt_observability.safe_views import _safe_final_model_input

    record = _record(_agent(_tools()))
    record["system_prompt_sections"] = [{"kind": "stable", "name": "Stable", "start_char": 0,
                                         "end_char": 10, "chars": 10, "truncated": False,
                                         "blocks": [{"heading": "# Finishing the job", "chars": 10}]}]
    safe = _safe_final_model_input(record)

    assert safe["tool_schema"]["per_tool_chars"] == record["tool_schema"]["per_tool_chars"]
    assert safe["prompt_surface"]["skills_entries"] == 2
    assert safe["system_prompt_sections"][0]["blocks"] == [{"heading": "# Finishing the job", "chars": 10}]


def test_the_visibility_token_figure_is_measured_from_the_schema():
    """The names-only envelope (~12 tokens a tool) read 1,149 for a ~16.6k request."""
    from agent_runtime.tool_visibility import _estimate_model_tool_tokens, _ensure_tool_registry_populated
    from tools.downstream_schema import wire_tool_chars
    from tools.registry import registry

    _ensure_tool_registry_populated()
    entry = registry.get_entry("terminal")
    wire = wire_tool_chars([{"type": "function", "function": {**entry.schema, "name": "terminal"}}])

    assert _estimate_model_tool_tokens(["terminal"]) == math.ceil(wire["terminal"] / 4)
    assert _estimate_model_tool_tokens(["terminal"]) > (len("terminal") + 96) // 4
    assert _estimate_model_tool_tokens(["no_such_tool_xyz"]) == (len("no_such_tool_xyz") + 96) // 4


# ── toolvis slice 4: one receipt, three readers ──────────────────────────────
# Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §2(c),
# §3 slice 4, §5 item 1. The receipt is the tool form owner's (``chat_lane_tool_form``), set with
# the form it describes; the wire capture runs AFTER the transport aliased the bridge
# (``hermes_tool_search``), so the join reverses the transport's own alias map.

from tests.agent_runtime.test_chat_lane_defer import NEKO_DEFER  # noqa: E402
from tests.agent_runtime.test_tool_surface import harness_lane  # noqa: E402,F401 - fixture

_BLOCK = ("skill_manage",)


def _factory_agent(lane):
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer

    agent = lane.build_agent()
    apply_chat_lane_defer(agent, NEKO_DEFER, blocked=_BLOCK)
    return agent


def test_the_wire_names_are_the_surface_eager_set_plus_bridge(harness_lane):  # noqa: F811
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent, capture_final_request_tools
    from agent_runtime.tool_surface import receipt_names, unaliased_wire_names

    agent = _factory_agent(harness_lane)
    agent.api_mode = "codex_responses"
    agent.messages = [{"role": "user", "content": "hi"}]
    agent._persist_user_message_idx = 0
    agent._cached_system_prompt = _SYSTEM
    # What the Responses transport emits for an OpenAI/Codex endpoint: the bridge under its alias.
    agent._transport_cache = {"codex_responses": SimpleNamespace(
        _last_wire_aliases={"hermes_tool_search": "tool_search"})}
    wire_tools = [
        {**td, "function": {**td["function"], "name": "hermes_tool_search"}}
        if td["function"]["name"] == "tool_search" else td
        for td in agent.tools
    ]
    with bind_persona_turn_agent(agent):
        capture_final_request_tools({"tools": wire_tools})
    schema = _record(agent)["tool_schema"]
    surface = schema["surface"]

    assert "hermes_tool_search" in schema["final_model_tools"], "the record keeps the wire's spelling"
    joined = unaliased_wire_names({"names": schema["final_model_tools"], "bridge_aliases": schema["bridge_aliases"]})
    assert sorted(joined) == sorted([*receipt_names(surface, "eager"), *surface["bridge"]])
    assert schema["resolution_id"] == surface["resolution_id"]
    assert agent._hermes_turn_wire_tool_receipt["listing_chars"] > 0, "the aliased bridge's listing read as 0"
    # Anti-vacuity: the block and the persona's defer both moved names off this wire.
    assert "skill_manage" in surface["blocked"] and "memory" in surface["deferred"]


def test_hud_renders_the_deferred_line(harness_lane):  # noqa: F811
    from agent_runtime.runtime_hud.capability import render_capability_block, resolve_capability_block
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR

    from agent_runtime.tool_surface import receipt_names

    receipt = getattr(_factory_agent(harness_lane), AGENT_SURFACE_ATTR)
    block = resolve_capability_block(surface=receipt)
    # ONE definition of "deferred" for both readers: the HUD's count IS the receipt's
    # ``counts.deferred`` (non-MCP); the admitted MCP servers' names ride as ``mcp_count``.
    count = receipt["counts"]["deferred"]
    mcp_count = len(receipt["mcp"]["deferred"])
    assert mcp_count, "anti-vacuity: the lane defers MCP names"
    assert count == len(receipt["deferred"]) and count + mcp_count == len(receipt_names(receipt, "deferred"))
    assert block["deferred"]["count"] == count and block["deferred"]["via"] == "tool_search"
    assert block["deferred"]["mcp_count"] == mcp_count
    assert "agent_runtime.personas.<persona>.chat_lane_defer_tools" in block["deferred"]["restorable_via"]
    text = render_capability_block(block)
    assert f"- {count} tools deferred (and {mcp_count} MCP tools), reachable through tool_search" in text
    assert "nothing is missing" in text
    # Positive control: no surface, no line — the account stays silent when it knows nothing.
    assert "deferred" not in render_capability_block(resolve_capability_block())


def test_the_safe_view_keeps_reasons_and_counts_only(harness_lane):  # noqa: F811
    from agent_runtime.prompt_observability.safe_views import _safe_tool_schema
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR

    receipt = getattr(_factory_agent(harness_lane), AGENT_SURFACE_ATTR)
    tainted = {**receipt, "deferred": {name: {**row, "schema": {"description": "SECRET body"}}
                                       for name, row in receipt["deferred"].items()}}
    safe = _safe_tool_schema({
        "final_model_tools": ["terminal"], "per_tool_chars": {"terminal": 900},
        "surface": tainted, "resolution_id": receipt["resolution_id"],
    })
    surface = safe["surface"]
    assert set(surface) == {"schema_version", "resolution_id", "tool_search", "eager", "deferred",
                            "unavailable", "blocked", "mcp", "bridge", "counts", "degraded"}
    for part in (surface, surface["mcp"]):
        for state in ("eager", "deferred", "unavailable", "blocked"):
            for name, row in part[state].items():
                assert set(row) <= {"reason", "restorable_via"}, (state, name, row)
    assert surface["mcp"] == receipt["mcp"], "the MCP rows survive the whitelist"
    assert "SECRET" not in repr(surface) and "per_tool_chars" not in surface
    assert surface["counts"] == receipt["counts"]
    # Positive control: the reasons themselves survive the whitelist.
    assert surface["deferred"]["browser_vault_list"]["reason"] == "persona_defer"
    assert safe["resolution_id"] == receipt["resolution_id"]
