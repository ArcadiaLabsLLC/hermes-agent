"""R6: the chat lane's skill SURFACE filter is kept, and what it hides is a typed drop.

Plan ``docs/agent-runtime-harness/planned/chat-lane-context-and-memory-gaps.md`` R6,
owner ruling 2026-10-27 (``RT-CHAT-LANE-GAPS-RULING``). The chat turn passes
``skill_surface="mission_chat"`` on every permission mode, so an assigned skill whose
``SKILL.md`` excludes that surface is absent from the lane's index and refused by
``skill_view``. These tests pin that the absence is ACCOUNTED on
``chat_lane_capability_drops`` — on ``unbounded`` too — and that a skill the lane can
load (the positive control) is never reported.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_runtime import chat_lane_bundle as CLB
from agent_runtime.chat_lane_toolsets import (
    DROP_KIND_SKILL,
    SKILL_DROPPED_BY_CHAT_LANE_SURFACE,
    chat_lane_drop_rows,
    chat_lane_skill_drops,
)
from agent_runtime.runtime_hud.capability import render_capability_block, resolve_capability_block
from agent_runtime.tool_permissions import PERMISSION_MODE_UNBOUNDED
from tests.agent_runtime.persona_samples import sample_personas

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _manifest(root, name: str, hermes: str) -> None:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\nmetadata:\n  hermes:\n{hermes}---\nbody\n", encoding="utf-8"
    )


@pytest.fixture
def skill_root(tmp_path, monkeypatch):
    from agent import skill_utils

    shared = tmp_path / "shared"
    _manifest(shared, "chat-ok", "    surfaces: [mission_chat]\n    modes: [standard]\n")
    _manifest(shared, "worker-only", "    surfaces: [mission_worker]\n")
    _manifest(shared, "root-node-only", "    modes: [root_node]\n")
    monkeypatch.setattr(skill_utils, "get_shared_skills_dir", lambda: shared)
    monkeypatch.setattr("agent_runtime.skill_resolution.get_shared_skills_dir", lambda: shared)
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: [shared])
    return shared


def _qa(skills):
    qa = {persona.id: persona for persona in sample_personas()}["qa"]
    return dataclasses.replace(qa, skills=list(skills))


def _skill_drops(drops):
    return [drop for drop in drops if drop.kind == DROP_KIND_SKILL]


def test_an_assigned_skill_the_surface_excludes_is_a_typed_drop(skill_root):
    persona = _qa(["chat-ok", "worker-only", "root-node-only", "not-installed"])
    drops = _skill_drops(
        CLB.chat_lane_capability_drops(
            persona, session_id="s1", permission_mode=PERMISSION_MODE_UNBOUNDED
        )
    )

    # Surface and mode exclusions are both drops, each naming the manifest key
    # that decides it; the compatible skill (the positive control) and the
    # unresolved one (readiness's row) are not.
    assert [(d.subject, d.restorable_via) for d in drops] == [
        ("worker-only", "metadata.hermes.surfaces"),
        ("root-node-only", "metadata.hermes.modes"),
    ]
    assert {d.code for d in drops} == {SKILL_DROPPED_BY_CHAT_LANE_SURFACE}


def test_a_persona_whose_skills_all_load_claims_no_skill_drop(skill_root):
    persona = _qa(["chat-ok"])
    assert _skill_drops(
        CLB.chat_lane_capability_drops(
            persona, session_id="s1", permission_mode=PERMISSION_MODE_UNBOUNDED
        )
    ) == []


def test_the_skill_row_names_the_manifest_not_the_restore_knob():
    (drop,) = chat_lane_skill_drops(
        [("worker-only", {"compatible": False, "reason": "surface_not_supported"})],
        surface="mission_chat",
    )
    (row,) = chat_lane_drop_rows([drop], role="qa", entry_point_lane="mission_chat")

    assert row["code"] == SKILL_DROPPED_BY_CHAT_LANE_SURFACE
    assert row["skill"] == "worker-only"
    assert "SKILL.md" in row["summary"]
    assert "surface 'mission_chat'" in row["summary"]
    assert "`metadata.hermes.surfaces`" in row["fix_hint"]
    assert "ROOT config.yaml" not in row["fix_hint"]


def test_the_hud_tells_the_agent_and_keeps_the_config_restore_clause_honest():
    drops = chat_lane_skill_drops(
        [("worker-only", {"compatible": False, "reason": "surface_not_supported"})],
        surface="mission_chat",
    )
    block = resolve_capability_block(drops=drops)

    assert block["skills_dropped"] == ["worker-only"]
    # A manifest key is not a root config key: it must not reach the restore list.
    assert "restorable_via" not in block
    text = render_capability_block(block)
    assert "worker-only" in text and "SKILL.md" in text
    assert "ROOT config.yaml" not in text
