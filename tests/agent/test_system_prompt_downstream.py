"""Fork-owned tests moved out of ``tests/agent/test_system_prompt.py`` (seam Stages 2 and 5).

The T6b guidance lines ride the ``eternia-harness`` plugin's system-prompt section
(``register_system_prompt_section``, seam Stage 2) — not the core prompt builder —
so they render in the volatile tier's plugin block, gated on the session's tool set.
"""

from unittest.mock import patch

from tests.agent.test_system_prompt import (  # noqa: F401 — upstream names the moved tests use
    _make_agent,
    _prompt_parts,
    _stable_prompt,
)

from agent_runtime.prompt_guidance import (
    BROWSER_PRECONDITION_GUIDANCE,
    CLARIFY_CHOICES_GUIDANCE,
    SHELL_TOOL_PREFERENCE_GUIDANCE,
    SKILL_MANAGE_CONFIRM_GUIDANCE,
    TOOL_DESCRIBE_GUIDANCE,
)

_SECTION_ID = "eternia-harness.tool-guidance"


def _volatile(agent):
    return _prompt_parts(agent)["volatile"]


class TestT6bToolGuidance:
    """T6b: the tool schemas ship brief descriptions; the details-on-demand
    pointer and the policy moves ride the harness plugin's prompt section, each
    line gated on the fixed-per-conversation tool set (no per-turn churn)."""

    def test_section_is_registered_by_the_harness_plugin(self):
        from hermes_cli.plugins import discover_plugins, get_plugin_manager

        discover_plugins()
        section = get_plugin_manager()._system_prompt_sections.get(_SECTION_ID)
        assert section is not None
        assert section.plugin == "eternia-harness"
        assert section.position == "after_memory"

    def test_tool_describe_pointer_present_with_the_tool_absent_without(self):
        with_tool = _volatile(_make_agent(valid_tool_names=["read_file", "tool_describe"]))
        assert TOOL_DESCRIBE_GUIDANCE in with_tool
        assert f"{_SECTION_ID}\n" in with_tool
        assert TOOL_DESCRIBE_GUIDANCE not in _volatile(_make_agent(valid_tool_names=["read_file"]))

    def test_shell_preference_gated_on_terminal(self):
        assert SHELL_TOOL_PREFERENCE_GUIDANCE in _volatile(_make_agent(valid_tool_names=["terminal", "tool_describe"]))
        assert SHELL_TOOL_PREFERENCE_GUIDANCE not in _volatile(_make_agent(valid_tool_names=["clarify", "tool_describe"]))

    def test_clarify_choices_gated_on_clarify(self):
        assert CLARIFY_CHOICES_GUIDANCE in _volatile(_make_agent(valid_tool_names=["clarify", "tool_describe"]))
        assert CLARIFY_CHOICES_GUIDANCE not in _volatile(_make_agent(valid_tool_names=["terminal", "tool_describe"]))

    def test_browser_precondition_gated_on_browser(self):
        assert BROWSER_PRECONDITION_GUIDANCE in _volatile(_make_agent(valid_tool_names=["browser_navigate", "tool_describe"]))
        assert BROWSER_PRECONDITION_GUIDANCE not in _volatile(_make_agent(valid_tool_names=["terminal", "tool_describe"]))

    def test_skill_confirm_before_delete_gated_on_skill_manage(self):
        assert SKILL_MANAGE_CONFIRM_GUIDANCE in _volatile(_make_agent(valid_tool_names=["skill_manage", "tool_describe"]))
        assert SKILL_MANAGE_CONFIRM_GUIDANCE not in _volatile(_make_agent(valid_tool_names=["read_file", "tool_describe"]))

    def test_no_t6b_wire_renders_no_section(self):
        """The lines are the policy moved off the brief wire, so a session without
        ``tool_describe`` (no T6b wire) gets no harness block even when every other
        gating tool is present — which is also what keeps upstream's exact-bytes
        prompt tests (synthetic tool sets) byte-identical."""
        tools = ["terminal", "clarify", "browser_navigate", "skill_manage"]
        assert _SECTION_ID not in _volatile(_make_agent(valid_tool_names=tools))
        # Positive control: the same build plus tool_describe carries the block.
        assert _SECTION_ID in _volatile(_make_agent(valid_tool_names=[*tools, "tool_describe"]))

    def test_guidance_never_enters_the_stable_prefix(self):
        tools = ["terminal", "clarify", "browser_navigate", "skill_manage", "tool_describe"]
        stable = _stable_prompt(_make_agent(valid_tool_names=tools))
        for line in (TOOL_DESCRIBE_GUIDANCE, SHELL_TOOL_PREFERENCE_GUIDANCE, CLARIFY_CHOICES_GUIDANCE,
                     BROWSER_PRECONDITION_GUIDANCE, SKILL_MANAGE_CONFIRM_GUIDANCE):
            assert line not in stable

    def test_guidance_is_byte_stable_across_builds(self):
        """Byte-stability guard (extends T5): the rendered section is
        byte-identical across repeated builds — static lines, no per-turn volatility."""
        tools = ["terminal", "clarify", "browser_navigate", "skill_manage", "tool_describe"]
        with patch("agent.system_prompt._timestamp_line", return_value=""):
            first = _volatile(_make_agent(valid_tool_names=tools))
            second = _volatile(_make_agent(valid_tool_names=tools))
        assert first == second
        for line in (TOOL_DESCRIBE_GUIDANCE, SHELL_TOOL_PREFERENCE_GUIDANCE, CLARIFY_CHOICES_GUIDANCE,
                     BROWSER_PRECONDITION_GUIDANCE, SKILL_MANAGE_CONFIRM_GUIDANCE):
            assert line in first
