"""Fork half of ``tests/hermes_cli/test_deleted_profile_tombstone.py``'s marker-less shell node (PR #121224).

Upstream's node passes the stray dir to ``pytest.raises(match=...)`` raw; ``match=`` is a regex and a
Windows path ("C:\\Users\\...") is not a valid one ("incomplete escape \\U"). This copy escapes it;
upstream's node is skipped on Windows (``tests/_downstream/id_markers/fork_marks.py``) so upstream's
file keeps its bytes (FH-FOOTPRINT-FORK-TEST-HUNKS-OUT). Both go when the PR merges.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hermes_cli.profiles import (
    backfill_profile_envs,
    create_profile,
    profile_exists,
    profiles_to_serve,
    resolve_profile_env,
)
from tests.hermes_cli.test_deleted_profile_tombstone import _named_homes, profile_env  # noqa: F401


def test_marker_less_shell_is_not_a_profile_on_any_path_spelling(profile_env):  # noqa: F811
    """A ``profiles/<name>`` dir with no identity file is not listed, served, or seeded with the
    default install's ``.env``; ``profile create`` fails closed naming the stray dir, on every OS."""
    default_env = profile_env / ".hermes" / ".env"
    default_env.write_text("OPENAI_API_KEY=sk-real\n", encoding="utf-8")
    shell = profile_env / ".hermes" / "profiles" / "ghost"
    (shell / "cron").mkdir(parents=True)
    (shell / "cron" / "ticker_heartbeat").write_text("1\n", encoding="utf-8")
    legacy = profile_env / ".hermes" / "profiles" / "legacy"
    legacy.mkdir()
    (legacy / "state.db").write_bytes(b"")

    assert backfill_profile_envs(quiet=True) == ["legacy"]
    assert not (shell / ".env").exists()
    assert _named_homes(profile_env) == ["legacy"]
    assert [name for name, _ in profiles_to_serve(True)] == ["default", "legacy"]
    assert not profile_exists("ghost")
    with pytest.raises(FileNotFoundError):
        resolve_profile_env("ghost")
    assert Path(resolve_profile_env("legacy")) == legacy

    (shell / "skills" / "my-skill").mkdir(parents=True)
    (shell / "skills" / "my-skill" / "SKILL.md").write_text("# mine\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match=re.escape(str(shell))):
        create_profile("ghost", no_alias=True, no_skills=True)
    assert (shell / "skills" / "my-skill" / "SKILL.md").exists()
    assert "ghost" not in _named_homes(profile_env)
