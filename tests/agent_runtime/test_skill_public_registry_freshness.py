from agent_runtime.skill_resolution import resolve_skill, skill_root_manifests, skill_root_registry_scope
from agent_runtime.snapshot.context import SnapshotBuildContext, snapshot_build_context_scope
from agent_runtime.chat_lane_skill_index import compact_skill_categories


def test_reused_snapshot_context_sees_skill_edits(tmp_path):
    root = tmp_path / "skills"
    directory = root / "group" / "first"
    directory.mkdir(parents=True)
    manifest = directory / "SKILL.md"
    manifest.write_text("---\nname: original\ndescription: first\n---\nBody", encoding="utf-8")
    context = SnapshotBuildContext()
    with snapshot_build_context_scope(context), skill_root_registry_scope(context.skill_root_registries):
        assert resolve_skill("original", roots=[root]).status == "resolved"
        with snapshot_build_context_scope(context):
            assert context.skill_root_registries
    manifest.write_text("---\nname: renamed\ndescription: changed\n---\nBody", encoding="utf-8")
    with snapshot_build_context_scope(context), skill_root_registry_scope(context.skill_root_registries):
        assert resolve_skill("renamed", roots=[root]).status == "resolved"
        assert resolve_skill("original", roots=[root]).status == "missing"


def test_public_manifests_preserve_resolver_aliases_and_category_scope(tmp_path):
    root = tmp_path / "skills"
    directory = root / "group" / "directory-name"
    directory.mkdir(parents=True)
    manifest = directory / "SKILL.md"
    manifest.write_text("---\nname: public-alias\ndescription: first\n---\nBody", encoding="utf-8")
    entries = skill_root_manifests(root)
    entry = next(item for item in entries if item.manifest == manifest)
    assert "public-alias" in entry.aliases
    assert resolve_skill("public-alias", roots=[root]).candidate.skill_md == entry.manifest
    assert compact_skill_categories(["public-alias"], roots=[root]) == frozenset()
    assert compact_skill_categories([], roots=[root]) == frozenset({"group"})


def test_default_resolver_roots_reuse_profile_memo(tmp_path, monkeypatch):
    from agent import skill_utils
    from agent_runtime import skill_resolution
    root = tmp_path / "skills"
    root.mkdir()
    calls = []
    def roots():
        calls.append(1)
        return [root]
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", roots)
    monkeypatch.setattr(skill_utils, "get_skill_create_dir", lambda: None)
    skill_resolution._SEARCH_ROOTS_CACHE.clear()
    resolve_skill("first-missing")
    resolve_skill("second-missing")
    assert len(calls) == 1
