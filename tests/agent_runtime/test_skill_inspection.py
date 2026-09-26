"""Client inspection shares the real tool resolver without executing instructions."""
import json

import pytest

from agent_runtime.skill_inspection import MAX_DOCUMENT_BYTES, SkillInspectionError
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from agent_runtime.skill_inspection import skill_inspection_reader


def put_skill(home, name, body="Full instructions\nLast line"):
    path = home / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Example instructions\n---\n{body}", encoding="utf-8")
    return path


def test_inspection_is_profile_scoped_complete_and_never_preprocesses(tmp_path):
    homes = [tmp_path / "a", tmp_path / "b"]
    for home, name in zip(homes, ("alpha", "beta")):
        put_skill(home, name, "!`echo must-not-run`\nLast line")
    for home, name, other in [(homes[0], "alpha", "beta"), (homes[1], "beta", "alpha"),
                               (homes[0], "alpha", "beta")]:
        token = set_hermes_home_override(home)
        try:
            reader = skill_inspection_reader()
            rows = reader.catalog(can_load=True)
            assert name in {row["id"] for row in rows}
            assert other not in {row["id"] for row in rows}
            detail = reader.detail(name, can_load=True)
            assert detail["content"].replace("\r\n", "\n").endswith("!`echo must-not-run`\nLast line")
            assert detail["source"] == "profile_local"
            assert not (home / ".env").exists()
            assert not (home / "skills" / ".usage.json").exists()
        finally:
            reset_hermes_home_override(token)


def test_disabled_inspection_and_limits_do_not_grant_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = put_skill(tmp_path, "paused")
    (tmp_path / "config.yaml").write_text("skills:\n  disabled: [paused]\n", encoding="utf-8")
    reader = skill_inspection_reader()
    assert reader.detail("paused", can_load=True)["status"] == "disabled"
    put_skill(tmp_path, "active")
    assert reader.detail("active", can_load=False)["status"] == "tool_unavailable"
    with pytest.raises(SkillInspectionError, match="unavailable"):
        reader.detail("../config.yaml", can_load=True)
    path.write_bytes(path.read_bytes() + b"x" * MAX_DOCUMENT_BYTES)
    with pytest.raises(SkillInspectionError, match="document_too_large"):
        reader.detail("paused", can_load=True)


def test_ambiguous_skills_refuse_and_unknown_names_are_not_file_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    put_skill(tmp_path, "duplicate", "one")
    other = tmp_path / "external"
    put_skill(other, "duplicate", "two")
    (tmp_path / "config.yaml").write_text(json.dumps({
        "skills": {"external_dirs": [str(other / "skills")]}}), encoding="utf-8")
    reader = skill_inspection_reader()
    with pytest.raises(SkillInspectionError, match="unavailable"):
        reader.detail("duplicate", can_load=True)
    with pytest.raises(SkillInspectionError, match="unavailable"):
        reader.detail(str(tmp_path / "config.yaml"), can_load=True)


def test_workspace_discovery_requires_the_runtime_trust_and_quarantine_gates(tmp_path, monkeypatch):
    from agent.runtime_cwd import reset_session_cwd, set_session_cwd
    from agent.skill_utils import PROJECT_SKILLS_SUBDIRS
    from tools.skills_guard import scan_skill

    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    (workspace / ".git").mkdir(parents=True)
    skill_dir = workspace / PROJECT_SKILLS_SUBDIRS[0] / "project-example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: project-example\ndescription: Review code\n---\nRead and review code.", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    token = set_session_cwd(str(workspace))
    try:
        reader = skill_inspection_reader()
        assert "project-example" not in {row["id"] for row in reader.catalog(can_load=True)}
        (home / "config.yaml").write_text(json.dumps({"skills": {
            "trusted_project_dirs": [str(workspace)]}}), encoding="utf-8")
        # The real scanner participates; this fixture contains no execution directives.
        assert scan_skill(skill_dir).verdict != "dangerous"
        assert reader.detail("project-example", can_load=True)["content"].endswith("Read and review code.")
    finally:
        reset_session_cwd(token)
