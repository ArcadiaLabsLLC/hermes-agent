"""Fork-owned tests moved out of ``tests/agent/test_external_skills.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import os
from unittest.mock import patch

from tests.agent.test_external_skills import (  # noqa: F401 — upstream fixtures the moved test uses
    external_skills_dir,
    hermes_home,
)


class TestSharedSkillsDir:
    def test_default_is_root_shared_skills_and_converges_across_profiles(self, tmp_path):
        # In profile mode (HERMES_HOME=<root>/profiles/<name>) the shared root
        # resolves to <root>/shared/skills — the SAME path for every persona,
        # with no env injection. That convergence is what makes one physical
        # skills dir reachable by all personas.
        from agent_runtime.profile_home import get_shared_skills_dir

        root = tmp_path / ".hermes"
        alice = root / "profiles" / "alice"
        neko = root / "profiles" / "neko"
        alice.mkdir(parents=True)
        neko.mkdir(parents=True)

        with patch.dict(os.environ, {"HERMES_HOME": str(alice)}, clear=False):
            os.environ.pop("HERMES_SHARED_SKILLS", None)
            alice_shared = get_shared_skills_dir()
        with patch.dict(os.environ, {"HERMES_HOME": str(neko)}, clear=False):
            os.environ.pop("HERMES_SHARED_SKILLS", None)
            neko_shared = get_shared_skills_dir()

        assert alice_shared == root / "shared" / "skills"
        assert alice_shared == neko_shared

    def test_env_override_wins(self, tmp_path):
        from agent_runtime.profile_home import get_shared_skills_dir

        override = tmp_path / "custom-shared-skills"
        with patch.dict(os.environ, {"HERMES_SHARED_SKILLS": str(override)}):
            assert get_shared_skills_dir() == override


class TestGetAllSkillsDirs:
    def test_local_first_then_shared_then_external(self, hermes_home, external_skills_dir):
        """Fork half of upstream's ``test_local_always_first`` (a strict xfail row):
        the fork's ``agent.skill_utils.get_all_skills_dirs`` puts the shared
        canonical root between the local profile dir and the config external dirs."""
        (hermes_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        with patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}):
            from agent.skill_utils import get_all_skills_dirs
            from agent_runtime.profile_home import get_shared_skills_dir
            result = get_all_skills_dirs()
            shared = get_shared_skills_dir()
        assert result[0] == hermes_home / "skills"
        assert result[1] == shared
        assert result[2] == external_skills_dir.resolve()
