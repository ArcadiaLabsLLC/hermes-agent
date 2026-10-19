"""The hand-off guidance line: which of delegate_task / agent_chat_send / Work to pick.

RT-DELEGATE-VS-CHAT-VS-WORK (plan ``p10-agent-2026-10-19.md`` §4). The line rides the
``eternia-harness.tool-guidance`` plugin section, gated on BOTH hand-off tools being in
the session (``_gate_open``: every name in the gate present). The Work clause is joined
onto it only when a ``WORK_SUBMIT_TOOLS`` verb is present too — inert today, since every
persona lane blocks the kanban toolset.

Killing mutations (2026-10-19), reds recorded in the landing commit:
``_gate_open`` -> ``any`` reds ``test_the_line_renders_only_with_both_hand_off_tools``;
``_work_clause_gate`` without the Work verbs reds ``test_the_work_clause_waits_for_a_work_verb``;
the hand-off row removed from ``_TOOL_GUIDANCE`` reds ``test_the_receipt_block_grows_by_the_line``.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import patch

from agent_runtime.profile_runner.model_input_observability import _model_input_observability
from agent_runtime.profile_runner.models import AgentRunRequest
from agent_runtime.prompt_guidance import (
    DELEGATION_HANDOFF_GUIDANCE,
    DELEGATION_HANDOFF_WORK_CLAUSE,
    TOOL_DESCRIBE_GUIDANCE,
    WORK_SUBMIT_TOOLS,
)
from tests.agent.test_system_prompt import _make_agent

_SECTION = "eternia-harness.tool-guidance"
_HANDOFF = ("delegate_task", "agent_chat_send")


def _plugin():
    return importlib.import_module("plugins.eternia-harness")


def _render(*tools: str) -> str:
    return _plugin().render_tool_guidance({"tool_names": ",".join(sorted({"tool_describe", *tools}))})


def test_the_line_renders_only_with_both_hand_off_tools():
    assert _render(*_HANDOFF).count(DELEGATION_HANDOFF_GUIDANCE) == 1
    assert DELEGATION_HANDOFF_GUIDANCE not in _render("delegate_task")
    assert DELEGATION_HANDOFF_GUIDANCE not in _render("agent_chat_send")
    assert DELEGATION_HANDOFF_GUIDANCE not in _render("read_file")


def test_the_work_clause_waits_for_a_work_verb():
    assert WORK_SUBMIT_TOOLS == frozenset({"kanban_create"})
    assert "submit Work" not in _render(*_HANDOFF)
    with_work = _render(*_HANDOFF, *WORK_SUBMIT_TOOLS)
    joined = DELEGATION_HANDOFF_GUIDANCE.removesuffix(".") + DELEGATION_HANDOFF_WORK_CLAUSE
    assert joined in with_work.splitlines(), "the clause is joined onto the hand-off line, not a new line"
    # a Work verb without both hand-off tools opens nothing
    assert "submit Work" not in _render("delegate_task", *WORK_SUBMIT_TOOLS)


def test_the_five_fixed_lines_render_as_before():
    plugin = _plugin()
    assert [attr for gate, attr in plugin._TOOL_GUIDANCE[:5]] == [
        "TOOL_DESCRIBE_GUIDANCE", "SHELL_TOOL_PREFERENCE_GUIDANCE", "CLARIFY_CHOICES_GUIDANCE",
        "BROWSER_PRECONDITION_GUIDANCE", "SKILL_MANAGE_CONFIRM_GUIDANCE"]
    assert all(isinstance(gate, str) for gate, _ in plugin._TOOL_GUIDANCE[:5])
    assert _render() == TOOL_DESCRIBE_GUIDANCE


def _tool_guidance_block_chars(tools: list[str]) -> int:
    """The receipt's ``system_prompt_sections`` block chars for the tool-guidance section."""

    agent = _make_agent(valid_tool_names=tools)
    with (
        patch("agent.prompt_builder.load_soul_md", return_value=""),
        patch("agent.prompt_builder.build_environment_hints", return_value=""),
        patch("agent.prompt_builder.build_context_files_prompt", return_value=""),
        patch("agent.system_prompt._timestamp_line", return_value=""),
    ):
        from agent.system_prompt import build_system_prompt_parts

        parts = build_system_prompt_parts(agent)
        merged = SimpleNamespace(**vars(agent), tools=[], messages=[{"role": "user", "content": "hi"}],
                                 _persist_user_message_idx=0,
                                 _cached_system_prompt="\n\n".join(v for v in (
                                     parts.get("stable"), parts.get("context"), parts.get("volatile")) if v))
        record = _model_input_observability(agent=merged, request=AgentRunRequest(profile="p", user_message="hi"))
    blocks = [b for section in record.get("system_prompt_sections", []) for b in section["blocks"]
              if b["heading"].endswith(_SECTION)]
    assert len(blocks) == 1, f"no single {_SECTION} block in the receipt: {record.get('system_prompt_sections')}"
    return blocks[0]["chars"]


def test_the_receipt_block_grows_by_the_line():
    baseline = _tool_guidance_block_chars(["read_file", "tool_describe"])
    with_line = _tool_guidance_block_chars(["read_file", "tool_describe", *_HANDOFF])
    # the line plus the newline joining it to the line before; the section's char
    # header keeps its digit count across both (both contents are 3-digit lengths)
    assert len(str(len(TOOL_DESCRIBE_GUIDANCE))) == len(str(len(TOOL_DESCRIBE_GUIDANCE) + 1 + len(DELEGATION_HANDOFF_GUIDANCE)))
    delta = with_line - baseline
    assert delta == len(DELEGATION_HANDOFF_GUIDANCE) + 1, delta
    print(f"hand-off line: {len(DELEGATION_HANDOFF_GUIDANCE)} chars, block +{delta} chars, "
          f"~{len(DELEGATION_HANDOFF_GUIDANCE) // 4} tokens (chars/4)")
