"""Fork-owned tests moved out of ``tests/agent/test_skills_auto_load.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

from unittest.mock import patch

from tests.agent.test_skills_auto_load import (  # noqa: F401 — upstream names the moved tests use
    _write_skill,
)


class TestBuildAutoLoadPrompt:
    def test_required_preload_keeps_runtime_note_and_auto_load_dedup(self, tmp_path):
        """The fork's required-skill emphasis now rides the mission-chat preload resolver
        on top of upstream's own note (lane DOORS-A 2026-09-24), not a threaded parameter."""
        from agent_runtime.mission_chat_turn_context import _default_build_preloaded_skills_prompt

        _write_skill(tmp_path, "optional-skill", "OPTIONAL CONTENT")
        _write_skill(tmp_path, "required-skill", "REQUIRED CONTENT")
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            prompt, loaded, missing = _default_build_preloaded_skills_prompt(
                ["optional-skill", "required-skill"], task_id="t",
                required_skill_names={"required-skill"},
            )
            bare, _, _ = _default_build_preloaded_skills_prompt(
                ["optional-skill", "required-skill"], task_id="t", required_skill_names=None,
            )
        assert loaded == ["optional-skill", "required-skill"] and missing == []
        assert "REQUIRED CONTENT" in prompt and "OPTIONAL CONTENT" in prompt
        assert 'Runtime policy requires the "required-skill" skill on this surface' in prompt
        assert '"optional-skill" skill on this surface' not in prompt
        # Positive control: same skills, nothing required -> no policy line.
        assert "Runtime policy requires" not in bare
