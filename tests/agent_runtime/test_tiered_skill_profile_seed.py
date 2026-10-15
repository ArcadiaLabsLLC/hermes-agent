"""The daily fix 6294875480 (2026-10-07) re-cut against the current skill tiers.

That commit seeded ``skills.extra_dirs`` (``TIER_EXTRA``) at profile publication so the
canonical shared skills root was searched, writable-tier and never external, with the
realm inbox and provenance dirs excluded. Upstream removed the extra tier before
v0.21.6; the 2026-10-08 merge re-applied the shared root as ``TIER_LOCAL`` in
``agent.skill_utils.get_skill_search_roots`` and the two exclusions in
``EXCLUDED_SKILL_DIRS``, with no configuration write at all. This pins the fix's
guarantees at that mechanism, for two profiles: user roots and settings survive a
profile layout byte-for-byte, the shared root is a local-tier root, an external root
stays external, and the realm inbox / provenance trees are never scanned.
"""

from __future__ import annotations

from agent import skill_utils
from agent_runtime.profile_home import get_shared_skills_dir
from hermes_cli.profiles import _finish_profile_layout


def test_two_profile_layouts_keep_user_roots_and_search_the_shared_root_as_local(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    shared = root / "shared" / "skills"
    shared.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.delenv("HERMES_SHARED_SKILLS", raising=False)
    for name in ("alice", "bob"):
        home = root / "profiles" / name
        home.mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(home))
        config = home / "config.yaml"
        config.write_text(
            f"custom: {name}\nskills:\n  external_dirs: [{external.as_posix()}]\n"
            "  disabled: [demo]\n",
            encoding="utf-8",
        )
        before = config.read_bytes()
        _finish_profile_layout(home, no_skills=True, clone_all=True, description=None)
        skill_utils._raw_config_cache_clear()

        assert config.read_bytes() == before
        assert get_shared_skills_dir() == shared
        roots = skill_utils.get_skill_search_roots(include_project=False)
        assert (skill_utils.TIER_LOCAL, shared) in roots
        assert (skill_utils.TIER_EXTERNAL, external) in roots
        assert not skill_utils.is_external_skill_path(shared / "demo" / "SKILL.md")
        assert skill_utils.is_external_skill_path(external / "demo" / "SKILL.md")


def test_realm_inbox_and_provenance_trees_are_never_scanned(tmp_path):
    shared = tmp_path / "shared" / "skills"
    assert skill_utils.is_excluded_skill_path(shared / ".realm_inbox" / "x" / "SKILL.md")
    assert skill_utils.is_excluded_skill_path(shared / ".provenance" / "x" / "SKILL.md")
    assert not skill_utils.is_excluded_skill_path(shared / "x" / "SKILL.md")
