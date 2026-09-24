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
        from agent.skill_commands import build_preloaded_skills_prompt

        _write_skill(tmp_path, "pinned-skill", "PINNED CONTENT")
        _write_skill(tmp_path, "required-skill", "REQUIRED CONTENT")
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            prompt, loaded, missing = build_preloaded_skills_prompt(
                ["pinned-skill", "required-skill"],
                excluded_loaded_names={"pinned-skill"},
                required_skill_names={"pinned-skill", "required-skill"},
            )
        assert loaded == ["pinned-skill", "required-skill"] and missing == []
        assert "PINNED CONTENT" not in prompt
        assert "REQUIRED CONTENT" in prompt
        assert 'Runtime policy requires the "required-skill" skill' in prompt
