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


def _tools():
    return [
        _td("read_file", "Read a file."),
        _td("heavy_tool", "x" * 2000),
        _td(_PROMOTED, "Composed Stage C workflow: launch, gate and navigate in one call. " + "More. " * 300),
        _td("tool_search", "Search 2 additional tools.\n\nEvery deferred capability is listed below.\n\n- memory\n- patch"),
    ]


def test_the_heaviest_tool_heads_the_per_tool_map_at_its_wire_size():
    record = _record(_agent(_tools()))
    per_tool = record["tool_schema"]["per_tool_chars"]

    assert next(iter(per_tool)) == "heavy_tool", per_tool
    heavy = _td("heavy_tool", "x" * 2000)
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
