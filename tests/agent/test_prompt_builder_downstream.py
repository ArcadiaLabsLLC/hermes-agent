"""Fork-owned tests moved out of ``tests/agent/test_prompt_builder.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from agent.prompt_builder import (
    build_skills_system_prompt,
    build_context_files_prompt,
)

from tests.agent import test_prompt_builder as _upstream
from tests.agent.test_prompt_builder import (  # noqa: F401 — upstream names the moved tests use
    _drain_truncation_warnings,
)


class TestWindowsNativeToolingHint:
    """The Windows-native tooling hint rides the eternia-harness plugin's
    ``eternia-harness.windows-tooling`` section (lane PF-2); the core environment
    block carries upstream's bash hint only
    (``tests/agent_runtime/test_prompt_guidance_plugin.py``)."""

    def test_environment_block_is_upstream_only(self, monkeypatch):
        import sys as _sys

        import agent.prompt_builder as pb
        from agent_runtime.prompt_guidance import WINDOWS_NATIVE_TOOLING_HINT

        monkeypatch.setattr(_sys, "platform", "win32")
        monkeypatch.setattr(pb, "is_wsl", lambda: False)
        monkeypatch.delenv("TERMINAL_ENV", raising=False)
        out = pb.build_environment_hints()
        assert pb._WINDOWS_BASH_SHELL_HINT in out
        assert WINDOWS_NATIVE_TOOLING_HINT not in out

    def test_upstream_hint_string_unchanged(self):
        """Guard: the upstream string must merge cleanly — keep it byte-stable."""
        from agent.prompt_builder import _WINDOWS_BASH_SHELL_HINT
        assert "NOT PowerShell or cmd.exe" in _WINDOWS_BASH_SHELL_HINT
        assert "will NOT work" in _WINDOWS_BASH_SHELL_HINT


class TestBuildContextFilesPrompt:

    def test_hermes_md_and_agents_md_both_load(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Agent guidelines here.")
        (tmp_path / ".hermes.md").write_text("Hermes project rules.")
        result = build_context_files_prompt(cwd=str(tmp_path))
        assert "Hermes project rules" in result
        assert "Agent guidelines" in result

    def test_agents_md_and_claude_md_both_load(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Agent guidelines here.")
        (tmp_path / "CLAUDE.md").write_text("Claude guidelines here.")
        result = build_context_files_prompt(cwd=str(tmp_path))
        assert "Agent guidelines" in result
        assert "Claude guidelines" in result

    def test_claude_md_and_cursorrules_both_load(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Claude guidelines here.")
        (tmp_path / ".cursorrules").write_text("Cursor rules here.")
        result = build_context_files_prompt(cwd=str(tmp_path))
        assert "Claude guidelines" in result
        assert "Cursor rules" in result

    def test_all_project_context_sources_load(self, tmp_path):
        (tmp_path / ".hermes.md").write_text("Hermes wins.")
        (tmp_path / "AGENTS.md").write_text("Agents load.")
        (tmp_path / "CLAUDE.md").write_text("Claude loads.")
        (tmp_path / ".cursorrules").write_text("Cursor loads.")
        result = build_context_files_prompt(cwd=str(tmp_path))
        assert "Hermes wins" in result
        assert "Agents load" in result
        assert "Claude loads" in result
        assert "Cursor loads" in result


    def test_hermes_md_and_override_both_load_in_priority_order(self, tmp_path):
        """Fork half of upstream's ``test_hermes_md_still_wins_over_agents_override``
        (a strict xfail row): the fork's ``build_context_files_prompt`` loads context
        sources additively, in priority order."""
        (tmp_path / ".hermes.md").write_text("Hermes-first context.")
        (tmp_path / "AGENTS.override.md").write_text("Override context.")
        result = build_context_files_prompt(cwd=str(tmp_path))
        assert "Hermes-first context" in result
        assert "Override context" in result
        assert result.index("Hermes-first context") < result.index("Override context")


class TestBuildSkillsSystemPromptConditional:
    # upstream's class-scoped autouse fixture, imported by name
    _clear_skills_cache = _upstream.TestBuildSkillsSystemPromptConditional._clear_skills_cache

    def test_mission_chat_hides_root_node_only_skills(self, monkeypatch, tmp_path):
        from agent_runtime.skill_resolution import skill_runtime_scope

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        root_only = tmp_path / "skills" / "harness" / "harness-mission-lead"
        root_only.mkdir(parents=True)
        (root_only / "SKILL.md").write_text(
            "---\nname: harness-mission-lead\ndescription: Root mission lead\n"
            "metadata:\n  hermes:\n    surfaces: [mission_worker]\n"
            "    modes: [root_node]\n---\n",
            encoding="utf-8",
        )
        chat_skill = tmp_path / "skills" / "harness" / "harness-continuity"
        chat_skill.mkdir(parents=True)
        (chat_skill / "SKILL.md").write_text(
            "---\nname: harness-continuity\ndescription: Chat-safe continuity\n"
            "metadata:\n  hermes:\n    surfaces: [mission_chat, mission_worker]\n"
            "    modes: [standard, root_node]\n---\n",
            encoding="utf-8",
        )

        with skill_runtime_scope(surface="mission_chat", root_node_mode=False):
            result = build_skills_system_prompt()
        with skill_runtime_scope(surface="mission_worker", root_node_mode=True):
            root_result = build_skills_system_prompt()

        assert "harness-continuity" in result
        assert "harness-mission-lead" not in result
        assert "harness-mission-lead" in root_result
