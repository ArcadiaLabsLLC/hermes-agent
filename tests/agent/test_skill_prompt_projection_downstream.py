"""Behavior receipts for the independently movable fork prompt helpers."""
import pytest

from agent import prompt_builder as pb
from agent_runtime.skill_resolution import skill_frontmatter_runtime_compatibility, skill_runtime_scope


@pytest.mark.parametrize("metadata,expected", [
    (None, {"surfaces": [], "modes": [], "load_policy": "explicit"}),
    ([], {"surfaces": [], "modes": [], "load_policy": "explicit"}),
    ({"hermes": None}, {}),
    ({"hermes": {}}, {"surfaces": [], "modes": [], "load_policy": "explicit"}),
    ({"hermes": {"surfaces": "mission_chat", "modes": "standard", "load_policy": "required_preload"}},
     {"surfaces": ["mission_chat"], "modes": ["standard"], "load_policy": "required_preload"}),
    ({"hermes": {"surfaces": ("mission_worker",), "modes": {"root_node"}, "load_policy": 42}},
     {"surfaces": ["mission_worker"], "modes": ["root_node"], "load_policy": "42"}),
    ({"hermes": {"surfaces": 5, "modes": True, "load_policy": None}},
     {"surfaces": [], "modes": [], "load_policy": "explicit"}),
])
def test_snapshot_runtime_projection_preserves_scan_decisions(tmp_path, metadata, expected):
    frontmatter = {"metadata": metadata}
    result = pb._build_snapshot_entry(tmp_path / "example" / "SKILL.md", tmp_path, frontmatter, "summary")
    assert result["runtime"] == expected
    for surface, mode in [("mission_chat", False), ("mission_worker", True)]:
        assert skill_frontmatter_runtime_compatibility(frontmatter, surface=surface, root_node_mode=mode) == (
            skill_frontmatter_runtime_compatibility(
                {"metadata": {"hermes": result["runtime"]}}, surface=surface, root_node_mode=mode)
        )


@pytest.mark.parametrize("surface,mode,expected", [
    (None, None, ("mission_worker", True)),
    ("mission_chat", False, ("mission_chat", False)),
    (None, False, ("mission_worker", False)),
    ("", None, ("", True)),
])
def test_prompt_explicit_values_override_ambient_defaults(tmp_path, monkeypatch, surface, mode, expected):
    from agent import skill_utils
    monkeypatch.setattr(pb, "get_skills_dir", lambda: tmp_path)
    monkeypatch.setattr(pb, "get_all_skills_dirs", lambda: [tmp_path])
    monkeypatch.setattr(skill_utils, "get_project_skills_dirs", lambda: [])
    monkeypatch.setattr(pb, "_build_skills_system_prompt_inner", lambda *args: args[-2:])
    with skill_runtime_scope(surface="mission_worker", root_node_mode=True):
        assert pb.build_skills_system_prompt(skill_surface=surface, skill_root_node_mode=mode) == expected