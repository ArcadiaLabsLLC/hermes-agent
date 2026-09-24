"""Fork-owned tests moved out of ``tests/agent/test_external_skills.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import os
from unittest.mock import patch


class TestSharedSkillsDir:
    def test_default_is_root_shared_skills_and_converges_across_profiles(self, tmp_path):
        # In profile mode (HERMES_HOME=<root>/profiles/<name>) the shared root
        # resolves to <root>/shared/skills — the SAME path for every persona,
        # with no env injection. That convergence is what makes one physical
        # skills dir reachable by all personas.
        from hermes_constants import get_shared_skills_dir

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
        from hermes_constants import get_shared_skills_dir

        override = tmp_path / "custom-shared-skills"
        with patch.dict(os.environ, {"HERMES_SHARED_SKILLS": str(override)}):
            assert get_shared_skills_dir() == override
