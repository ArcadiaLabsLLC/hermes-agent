"""Fork-owned profile-home authorities (``agent_runtime.profile_home``).

Stage 4 of ``docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md``
moved these out of the upstream files ``hermes_constants.py`` and
``hermes_cli/profiles.py``; the roster answer below is upstream's
``list_profile_names()`` and nothing of our own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hermes_constants
from agent_runtime import profile_home
from hermes_constants import (
    mark_named_profile_deleted,
    reset_hermes_home_override,
    set_hermes_home_override,
)


@pytest.fixture
def profiles_root(tmp_path, monkeypatch):
    """``Path.home()`` and ``HERMES_HOME`` inside ``tmp_path``; returns ``<root>/profiles``."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None)
    root = home / "profiles"
    root.mkdir()
    return root


def _live(root: Path, name: str) -> Path:
    profile = root / name
    profile.mkdir()
    (profile / "config.yaml").write_text("{}\n", encoding="utf-8")
    return profile


def test_the_prune_roster_lists_live_profiles_only(profiles_root):
    """One roster: a tombstoned dir and a marker-less shell are NOT profiles.

    ``_profile_template_names`` feeds the orphan prune; a raw ``iterdir`` walk
    there counted a deleted profile whose directory a stale writer re-created,
    so a persona bound to it was never prunable. ``alice`` is the positive
    control: the same walk that must drop the other two must list her.
    """
    from agent_runtime.persona_instance_identity import _profile_template_names

    _live(profiles_root, "alice")
    mark_named_profile_deleted(_live(profiles_root, "ghost"))
    (profiles_root / "shell" / "logs").mkdir(parents=True)

    assert _profile_template_names() == ["alice"]


def test_the_prune_roster_never_carries_default(profiles_root):
    """``list_profile_names()`` leads with ``default``; the prune's roster must not.

    An always-non-empty roster would make ``profile_catalog_authoritative``
    true on a machine with no named profiles at all.
    """
    from agent_runtime.persona_instance_identity import _profile_template_names

    assert _profile_template_names() == []


class TestSharedCharactersDir:
    """The install-wide character library, and the ladder it must ride.

    The library is ONE directory per hermes root — every persona profile under
    that root computes it from its own ``HERMES_HOME`` with no env injection,
    which is what makes a mis-resolved persona home stop being a characters
    incident (launcher plan §A-1 argument 1). The pins below are the two halves
    of that claim: convergence across profiles, and the ContextVar ladder the
    convergence has to be built on.
    """

    def test_profiles_under_one_root_converge_on_one_library(self, tmp_path, monkeypatch):
        root = tmp_path / ".hermes"
        (root / "profiles" / "alice").mkdir(parents=True)
        (root / "profiles" / "base").mkdir(parents=True)
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)

        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "alice"))
        alice = profile_home.get_shared_characters_dir()
        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "base"))
        base = profile_home.get_shared_characters_dir()

        assert alice == root / "shared" / "characters"
        assert alice == base

    def test_a_bare_home_is_its_own_root(self, tmp_path, monkeypatch):
        """A home that is not ``<root>/profiles/<name>`` IS the root.

        This is the shape every test home and every plain-hermes install has,
        and it is what makes a tmpdir-scoped test isolated for free.
        """
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))

        assert profile_home.get_shared_characters_dir() == tmp_path / "home" / "shared" / "characters"

    def test_the_contextvar_override_is_the_home_the_library_derives_from(
        self, tmp_path, monkeypatch
    ):
        """The control on a bare-env implementation.

        ``get_default_hermes_root()`` reads ``os.environ["HERMES_HOME"]`` and
        never consults the context-local override, so a resolver built on it
        answers the PROCESS home while an in-process persona binding is scoped
        to another one — the cross-persona bleed the serve lane just retired.
        Two arms, and the second is the one that reds: an override under the
        same root must agree (nothing moved), and an override under a DIFFERENT
        root must answer THAT root's library.
        """
        monkeypatch.delenv("HERMES_SHARED_CHARACTERS", raising=False)
        process_root = tmp_path / "process"
        other_root = tmp_path / "other"
        (process_root / "profiles" / "base").mkdir(parents=True)
        (process_root / "profiles" / "alice").mkdir(parents=True)
        (other_root / "profiles" / "neko").mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(process_root / "profiles" / "base"))

        token = set_hermes_home_override(process_root / "profiles" / "alice")
        try:
            same_root = profile_home.get_shared_characters_dir()
        finally:
            reset_hermes_home_override(token)
        token = set_hermes_home_override(other_root / "profiles" / "neko")
        try:
            foreign_root = profile_home.get_shared_characters_dir()
        finally:
            reset_hermes_home_override(token)

        assert same_root == process_root / "shared" / "characters"
        assert foreign_root == other_root / "shared" / "characters"

    def test_the_env_override_wins_over_derivation(self, tmp_path, monkeypatch):
        """An install-wide override is identical for every persona by definition.

        That is why a bare ``os.environ`` read is sound for THIS authority and
        not for the derivation below it: an operator/test that names the library
        has named it for the whole install, so there is no persona-scoped answer
        for a ContextVar to carry.
        """
        override = tmp_path / "custom-library"
        monkeypatch.setenv("HERMES_SHARED_CHARACTERS", str(override))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes" / "profiles" / "alice"))

        assert profile_home.get_shared_characters_dir() == override
