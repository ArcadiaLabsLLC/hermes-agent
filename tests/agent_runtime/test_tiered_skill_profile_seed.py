"""Profile-owner seeding qualifies tiered roots without write-on-scan."""

from agent import skill_utils
from agent_runtime.profile_home import get_shared_skills_dir, seed_profile_skill_roots
from hermes_cli.config import read_user_config_raw
from hermes_cli.profiles import _finish_profile_layout


def test_two_profile_layouts_preserve_user_roots_exclusions_and_live_switch(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    shared = root / "shared" / "skills"
    shared.mkdir(parents=True)
    extra, external = tmp_path / "user-extra", tmp_path / "external"
    extra.mkdir()
    external.mkdir()
    for name in ("alice", "bob"):
        home = root / "profiles" / name
        home.mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.delenv("HERMES_SHARED_SKILLS", raising=False)
        config = home / "config.yaml"
        config.write_text(f"custom: {name}\nskills:\n  extra_dirs: [{extra.as_posix()}]\n  external_dirs: [{external.as_posix()}]\n  excluded_dirs: [user-hidden]\n  disabled: [demo]\n", encoding="utf-8")
        _finish_profile_layout(home, no_skills=True, clone_all=True, description=None)
        data = read_user_config_raw(config)
        assert data["custom"] == name
        assert data["skills"]["extra_dirs"] == [extra.as_posix(), str(shared)]
        assert data["skills"]["external_dirs"] == [external.as_posix()]
        assert data["skills"]["disabled"] == ["demo"]
        assert data["skills"]["excluded_dirs"] == ["user-hidden", ".realm_inbox", ".provenance"]
        before = config.read_bytes()
        assert not seed_profile_skill_roots(home)
        roots = skill_utils.get_skill_search_roots(include_project=False)
        assert (skill_utils.TIER_EXTRA, shared) in roots
        assert (skill_utils.TIER_EXTRA, extra) in roots
        assert (skill_utils.TIER_EXTERNAL, external) in roots
        assert get_shared_skills_dir() == shared
        assert not skill_utils.is_external_skill_path(shared / "demo" / "SKILL.md")
        assert skill_utils.is_external_skill_path(external / "demo" / "SKILL.md")
        assert config.read_bytes() == before
        assert "user-hidden" in skill_utils.excluded_skill_dirs()


def test_malformed_profile_skills_are_preserved_on_refusal(tmp_path):
    import pytest
    path = tmp_path / "config.yaml"
    path.write_text("skills: invalid\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="mapping"):
        seed_profile_skill_roots(tmp_path)
    assert path.read_bytes() == before


def test_explicit_user_shared_root_is_preserved_without_duplicate(tmp_path, monkeypatch):
    home, shared = tmp_path / "profile", tmp_path / "shared"
    home.mkdir()
    shared.mkdir()
    monkeypatch.setenv("HERMES_SHARED_SKILLS", str(shared))
    path = home / "config.yaml"
    path.write_text(f"skills:\n  extra_dirs: [{shared.as_posix()}]\n  excluded_dirs: [user]\n", encoding="utf-8")
    assert seed_profile_skill_roots(home)
    data = read_user_config_raw(path)
    assert data["skills"]["extra_dirs"] == [shared.as_posix()]
    assert data["skills"]["excluded_dirs"] == ["user", ".realm_inbox", ".provenance"]
