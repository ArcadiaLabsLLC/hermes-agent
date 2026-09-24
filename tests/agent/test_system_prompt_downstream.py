"""Fork-owned tests moved out of ``tests/agent/test_system_prompt.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""


from tests.agent.test_system_prompt import (  # noqa: F401 — upstream names the moved tests use
    _make_agent,
    _stable_prompt,
)


class TestT6bToolGuidance:
    """T6b: the tool schemas ship brief descriptions; the details-on-demand
    pointer and the policy moves ride the byte-stable, tool-gated system prompt.
    These extend the byte-stability coverage to the new lines (static, gated on
    the fixed-per-conversation tool set → no per-turn churn)."""

    def test_tool_describe_pointer_present_with_tools_absent_without(self):
        from agent.prompt_builder import TOOL_DESCRIBE_GUIDANCE

        with_tools = _stable_prompt(_make_agent(valid_tool_names=["read_file"]))
        assert TOOL_DESCRIBE_GUIDANCE in with_tools
        no_tools = _stable_prompt(_make_agent(valid_tool_names=[]))
        assert TOOL_DESCRIBE_GUIDANCE not in no_tools

    def test_shell_preference_gated_on_terminal(self):
        from agent.prompt_builder import SHELL_TOOL_PREFERENCE_GUIDANCE

        assert SHELL_TOOL_PREFERENCE_GUIDANCE in _stable_prompt(
            _make_agent(valid_tool_names=["terminal"])
        )
        assert SHELL_TOOL_PREFERENCE_GUIDANCE not in _stable_prompt(
            _make_agent(valid_tool_names=["clarify"])
        )

    def test_clarify_choices_gated_on_clarify(self):
        from agent.prompt_builder import CLARIFY_CHOICES_GUIDANCE

        assert CLARIFY_CHOICES_GUIDANCE in _stable_prompt(
            _make_agent(valid_tool_names=["clarify"])
        )
        assert CLARIFY_CHOICES_GUIDANCE not in _stable_prompt(
            _make_agent(valid_tool_names=["terminal"])
        )

    def test_browser_precondition_gated_on_browser(self):
        from agent.prompt_builder import BROWSER_PRECONDITION_GUIDANCE

        assert BROWSER_PRECONDITION_GUIDANCE in _stable_prompt(
            _make_agent(valid_tool_names=["browser_navigate"])
        )
        assert BROWSER_PRECONDITION_GUIDANCE not in _stable_prompt(
            _make_agent(valid_tool_names=["terminal"])
        )

    def test_skill_confirm_before_delete_gated_on_skill_manage(self):
        confirm = "Confirm with the user before creating or deleting a skill."
        assert confirm in _stable_prompt(_make_agent(valid_tool_names=["skill_manage"]))
        assert confirm not in _stable_prompt(_make_agent(valid_tool_names=["read_file"]))

    def test_guidance_is_byte_stable_across_builds(self):
        """Byte-stability guard (extends T5): the stable tier carrying the T6b
        lines is byte-identical across repeated builds — the additions are
        static and introduce no per-turn volatility."""
        tools = ["terminal", "clarify", "browser_navigate", "skill_manage", "read_file"]
        first = _stable_prompt(_make_agent(valid_tool_names=tools))
        second = _stable_prompt(_make_agent(valid_tool_names=tools))
        assert first == second
        # All four moves + the pointer are present in the one build.
        from agent.prompt_builder import (
            BROWSER_PRECONDITION_GUIDANCE,
            CLARIFY_CHOICES_GUIDANCE,
            SHELL_TOOL_PREFERENCE_GUIDANCE,
            TOOL_DESCRIBE_GUIDANCE,
        )
        for line in (
            TOOL_DESCRIBE_GUIDANCE,
            SHELL_TOOL_PREFERENCE_GUIDANCE,
            CLARIFY_CHOICES_GUIDANCE,
            BROWSER_PRECONDITION_GUIDANCE,
        ):
            assert line in first
