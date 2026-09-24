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
from hermes_constants import mark_named_profile_deleted


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
