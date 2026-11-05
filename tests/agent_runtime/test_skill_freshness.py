"""RT-SKILL-FRESHNESS-CHECK: an agent is told when the manual it runs with is behind its shipped source.

HERMES_HOME is a per-test tempdir (conftest), so the shared skills root, its provenance
and its realm inbox are this test's own.
"""
from __future__ import annotations

import dataclasses
import json
import types
from pathlib import Path

import pytest

from agent_runtime.mcp_admission.vocabulary import MCP_OPERATING_SKILL_STALE
from agent_runtime.profile_home import get_shared_skills_dir
from agent_runtime.skill_freshness import render_stale_manual_clause, skill_version, stale_skill
from agent_runtime.skill_promotion import realm_inbox_dir

SKILL = "launcher-mcp-operations"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("HERMES_SHARED_SKILLS", raising=False)


def _package(base: Path, version: str | None, slug: str = SKILL) -> Path:
    pkg = base.joinpath(*slug.split("/"))
    pkg.mkdir(parents=True, exist_ok=True)
    line = f"version: {version}\n" if version is not None else ""
    (pkg / "SKILL.md").write_text(f"---\nname: {slug.split('/')[-1]}\n{line}---\n# Body\n", encoding="utf-8")
    return pkg


def _promoted_from(path: str, slug: str = SKILL) -> None:
    root = get_shared_skills_dir() / ".provenance"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{slug.replace('/', '__')}.json").write_text(
        json.dumps({"skill": slug, "content_hash": "x", "source": {"kind": "path", "path": path}}), encoding="utf-8")


def test_a_newer_promotion_source_makes_the_live_copy_stale(tmp_path):
    _package(get_shared_skills_dir(), "2.1.0")
    source = _package(tmp_path / "launcher" / "agent_prompts" / "skills", "2.2.0")
    _promoted_from(str(source))

    stale = stale_skill(SKILL)

    assert stale is not None
    assert (stale.live_version, stale.shipped_version, stale.source) == ("2.1.0", "2.2.0", f"path:{source}")


@pytest.mark.parametrize("shipped", ["2.1.0", "2.1", "2.0.9", "not-a-version", None])
def test_an_equal_older_or_unreadable_source_says_nothing(tmp_path, shipped):
    _package(get_shared_skills_dir(), "2.1.0")
    _promoted_from(str(_package(tmp_path / "src", shipped)))

    assert stale_skill(SKILL) is None


def test_a_relative_provenance_path_is_ignored_but_the_same_path_absolute_is_read(tmp_path, monkeypatch):
    _package(get_shared_skills_dir(), "2.1.0")
    source = _package(tmp_path / "src", "2.2.0")
    monkeypatch.chdir(tmp_path)
    _promoted_from("src/" + SKILL)
    assert stale_skill(SKILL) is None
    # Positive control: the same directory named absolutely is read.
    _promoted_from(str(source))
    assert stale_skill(SKILL) is not None


def test_a_realm_inbox_copy_ahead_of_the_live_one_is_reported_newest_first(tmp_path):
    _package(get_shared_skills_dir(), "1.0.0")
    _package(realm_inbox_dir("realm-a"), "1.5.0")
    _package(realm_inbox_dir("realm-b"), "3.0.0")
    _promoted_from(str(_package(tmp_path / "src", "2.0.0")))

    stale = stale_skill(SKILL)

    assert stale is not None and stale.shipped_version == "3.0.0" and stale.source == "realm:realm-b"


def test_an_unversioned_live_copy_is_behind_any_versioned_source_and_absence_is_not_staleness(tmp_path):
    assert stale_skill(SKILL) is None  # no live copy: the resolver's fact, not this one
    _package(realm_inbox_dir("realm-a"), "1.0.0")
    assert stale_skill(SKILL) is None
    _package(get_shared_skills_dir(), None)
    assert skill_version(get_shared_skills_dir() / SKILL) is None
    stale = stale_skill(SKILL)
    assert stale is not None and stale.live_version is None


def test_a_categorized_live_copy_is_found_by_its_name(tmp_path):
    _package(get_shared_skills_dir(), "1.0.0", slug=f"qa/{SKILL}")
    _promoted_from(str(_package(tmp_path / "src", "1.1.0")), slug=f"qa/{SKILL}")

    assert stale_skill(SKILL) is not None


def test_the_clause_names_the_code_both_versions_and_the_source(tmp_path):
    _package(get_shared_skills_dir(), "2.1.0")
    source = _package(tmp_path / "src", "2.2.0")
    _promoted_from(str(source))

    clause = render_stale_manual_clause([stale_skill(SKILL)])

    assert MCP_OPERATING_SKILL_STALE in clause and "2.1.0" in clause and "2.2.0" in clause and str(source) in clause
    assert render_stale_manual_clause([]) == ""


def test_the_admission_line_tells_the_agent_its_admitted_manual_is_stale(tmp_path, monkeypatch):
    from agent_runtime import chat_lane_scope
    from agent_runtime.mcp_admission import McpAdmission
    from agent_runtime.mcp_admission.vocabulary import LANE_MISSION_CHAT
    from tests.agent_runtime.persona_samples import sample_personas

    admission = McpAdmission(lane=LANE_MISSION_CHAT, role="qa", permission_mode="profile_default", enabled=True,
                             requested=("launcher_qa",), server_names=("launcher_qa",),
                             server_configs={"launcher_qa": {"command": "noop"}})
    monkeypatch.setattr(chat_lane_scope, "admission_enabled", lambda: True)
    monkeypatch.setattr(chat_lane_scope, "resolve_mcp_admission", lambda *_a, **_k: admission)
    monkeypatch.setattr(chat_lane_scope, "permission_options_for_chat",
                        lambda *_a, **_k: types.SimpleNamespace(permission_mode="profile_default"))
    qa = {persona.id: persona for persona in sample_personas()}["qa"]
    _package(get_shared_skills_dir(), "2.1.0")
    source = _package(tmp_path / "src", "2.2.0")

    fresh = chat_lane_scope.mission_chat_admission_line(qa, session_id=None)
    assert fresh == "- MCP tools: Admitted on this turn: launcher_qa."
    _promoted_from(str(source))
    stale = chat_lane_scope.mission_chat_admission_line(qa, session_id=None)
    assert stale.startswith(fresh) and MCP_OPERATING_SKILL_STALE in stale and "\n" not in stale
    # A persona never granted the manual is never told about it.
    ungranted = dataclasses.replace(qa, skills=["harness-qa-verdict"])
    assert chat_lane_scope.mission_chat_admission_line(ungranted, session_id=None) == fresh


def test_the_level_editing_manual_is_held_to_the_same_freshness_check(tmp_path, monkeypatch):
    """RT-LEVEL-SKILL-PRELOAD: an admitted, granted ``eternia-level-editing`` behind its
    launcher source is named on the admission line like the first manual."""

    from agent_runtime import chat_lane_scope
    from agent_runtime.mcp_admission import McpAdmission
    from agent_runtime.mcp_admission.vocabulary import LANE_MISSION_CHAT
    from tests.agent_runtime.persona_samples import sample_personas

    level = "eternia-level-editing"
    admission = McpAdmission(lane=LANE_MISSION_CHAT, role="qa", permission_mode="profile_default", enabled=True,
                             requested=("launcher_qa",), server_names=("launcher_qa",),
                             server_configs={"launcher_qa": {"command": "noop"}})
    monkeypatch.setattr(chat_lane_scope, "admission_enabled", lambda: True)
    monkeypatch.setattr(chat_lane_scope, "resolve_mcp_admission", lambda *_a, **_k: admission)
    monkeypatch.setattr(chat_lane_scope, "permission_options_for_chat",
                        lambda *_a, **_k: types.SimpleNamespace(permission_mode="profile_default"))
    qa = {persona.id: persona for persona in sample_personas()}["qa"]
    qa = dataclasses.replace(qa, skills=[*qa.skills, level])
    _package(get_shared_skills_dir(), "1.0.0", slug=level)
    _promoted_from(str(_package(tmp_path / "launcher" / "agent_prompts" / "skills", "1.1.0", slug=level)), slug=level)

    line = chat_lane_scope.mission_chat_admission_line(qa, session_id=None)

    assert f"Operating manual {level} is stale ({MCP_OPERATING_SKILL_STALE})" in line
    assert "version 1.0.0" in line and "version 1.1.0" in line


def test_a_from_path_promotion_records_an_absolute_source(tmp_path, monkeypatch):
    from hermes_cli.harness_parts.skills_promotion_commands import _source_from_path

    _package(tmp_path / "skills", "1.0.0")
    monkeypatch.chdir(tmp_path)
    _source_dir, source, _ = _source_from_path(f"skills/{SKILL}", SKILL, types.SimpleNamespace())

    assert Path(source["path"]).is_absolute() and Path(source["path"]) == (tmp_path / "skills" / SKILL).resolve()
