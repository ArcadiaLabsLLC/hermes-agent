"""The serve's resident core, moved by the frames the hub fans out, equals a full
rebuild at the same offset (row RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-
CHANGES-IT-COULD-APPLY-IN-PLACE, step 3).

Covers ``agent_runtime.resident_core.holder.observe`` (seed, chain, fold, drop)
through ``agent_runtime.resident_core.fold.apply_patch_row`` on the real producer:
``stream_frames`` over a seeded root, real store writes, then a fresh
``build_snapshot`` compared by ``core_cache.shadow.compare_cores`` section by
section.
"""

from __future__ import annotations

import pytest

from agent_runtime import resident_core
from agent_runtime.core_cache.shadow import compare_cores
from agent_runtime.office_store import OfficeStore
from agent_runtime.parity import core_event_offset
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.serde import to_jsonable
from agent_runtime.snapshot.build import _build_snapshot_uncoalesced
from agent_runtime.store import WorkspaceStore
from agent_runtime.stream import stream_frames
from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.office_seed import seed_workspace_record, settle_task_activity
from tests.agent_runtime.persona_instance_mint import mint_free_floating

#: Eternia's declaration (``kMissionFoldDeclaredEntities``), so every batch here rides the lane it rides live.
ETERNIA_FOLD_ENTITIES = (
    "persona_instance", "incident", "office_actor", "office_actor_lifecycle", "persona_instance_create",
    "office_surface", "office_surface_fold", "scope", "office_conflict", "persona_chat_turn",
    "persona_chat_open", "running_work_section", "persona",
)

WORKSPACE_A = "ws_resident_a"
WORKSPACE_B = "ws_resident_b"


@pytest.fixture
def patches_on(monkeypatch):
    from agent_runtime import state_patches as sp
    from agent_runtime import stream as st
    from agent_runtime.config import load_agent_runtime_config

    def _loader(*args, **kwargs):
        cfg = load_agent_runtime_config(*args, **kwargs)
        cfg.read_model.delta_patches = True
        return cfg

    monkeypatch.setattr(sp.emit, "load_root_runtime_config", _loader)
    patch_where_bound(monkeypatch, st, "delta_patches_enabled", lambda config=None: True)


def _actor(persona_id: str, instance: str, *, x: float) -> dict:
    return {
        "persona_id": persona_id,
        "persona_instance_id": instance,
        "items": [
            {"item_id": instance, "kind": "agent", "persona_id": persona_id, "position": [x, 0.0],
             "folder": "Agents", "display_name": f"{persona_id} agent"},
        ],
    }


def _differing_sections(resident: dict, fresh: dict) -> list[str]:
    """Every section ``compare_cores`` would name, not only the first."""

    names = []
    for key in sorted(set(resident) | set(fresh)):
        if key == "parity":
            continue
        if compare_cores({key: resident.get(key)}, {key: fresh.get(key)}) is not None:
            names.append(key)
    parity_only = compare_cores({"parity": resident.get("parity")}, {"parity": fresh.get("parity")})
    left, right = dict(resident.get("parity") or {}), dict(fresh.get("parity") or {})
    while parity_only is not None:
        names.append(parity_only)
        field = parity_only.split(".", 1)[1]
        left.pop(field, None)
        right.pop(field, None)
        parity_only = compare_cores({"parity": left}, {"parity": right})
    return names


def _next_content(frames) -> dict:
    """The next frame that is not liveness, observed exactly as the hub observes it."""

    while True:
        frame = to_jsonable(next(frames))
        resident_core.observe(frame)
        if frame.get("type") != "heartbeat":
            return frame


@pytest.fixture
def seeded(patches_on, isolate_agent_runtime_root):
    instances = PersonaInstanceStore()
    reviewer = mint_free_floating("profile:reviewer", store=instances)
    child = mint_free_floating("profile:child", store=instances)
    seed_workspace_record(WORKSPACE_A)
    seed_workspace_record(WORKSPACE_B)
    offices = OfficeStore()
    offices.ensure_surface(WORKSPACE_A, created_by="seed")
    offices.upsert_actor(WORKSPACE_A, _actor("qa", "personainst_qa_agent_0001", x=1.0))
    offices.upsert_actor(WORKSPACE_A, _actor("dev", "personainst_dev_agent_0001", x=4.0))
    WorkspaceStore().set_active(WORKSPACE_A)
    settle_task_activity()
    resident_core.drop("test_setup")
    yield instances, reviewer, child, offices
    resident_core.drop("test_teardown")


def _stream():
    return stream_frames(
        poll_interval_seconds=0.01, heartbeat_interval_seconds=60, delta_debounce_seconds=0,
        fold_entities=ETERNIA_FOLD_ENTITIES,
    )


def _run_batches(frames, writes) -> list[str]:
    kinds = []
    for write in writes:
        write()
        kinds.append(_next_content(frames)["type"])
    return kinds


def test_the_resident_core_equals_a_full_rebuild_after_mixed_patch_batches(seeded):
    instances, reviewer, child, offices = seeded
    frames = _stream()
    assert _next_content(frames)["type"] == "hydrate"
    assert resident_core.held() is not None, "the hydrate seeds the resident core"

    kinds = _run_batches(frames, [
        lambda: instances.update_profile(reviewer.id, model="claude-opus-4-8", provider="anthropic"),
        lambda: offices.upsert_actor(WORKSPACE_A, _actor("qa", "personainst_qa_agent_0001", x=9.0)),
        lambda: instances.update_profile(child.id, model="gpt-6.2", provider="openai"),
        lambda: offices.upsert_actor(WORKSPACE_A, _actor("ops", "personainst_ops_agent_0001", x=6.0)),
    ])
    # Positive control: every batch was FOLDED, not re-seeded from a core.
    assert kinds == ["patch"] * 4, kinds

    held = resident_core.held()
    assert held is not None, "no batch dropped the resident core"
    fresh = _build_snapshot_uncoalesced()
    assert core_event_offset(fresh) == held.offset, "compared at the same offset"
    assert _differing_sections(held.core, fresh) == []


def test_a_scope_switch_re_derives_every_active_flag_a_rebuild_carries(seeded):
    """The scope fold's own sections equal the rebuild. ``prompt_observability``
    (each instance's active workspace NAME) is the one section the patch lane leaves
    behind, in Eternia and here alike: UNCOVERED SEAM, row
    RT-FU-A-STEER-OR-SCOPE-PATCH-LEAVES-CHANNEL-THREADS-AND-PROMPT-VIEW-STALE-UNTIL-THE-NEXT-FULL-CORE."""

    frames = _stream()
    _next_content(frames)
    assert _run_batches(frames, [lambda: WorkspaceStore().set_active(WORKSPACE_B)]) == ["patch"]
    held = resident_core.held()
    fresh = _build_snapshot_uncoalesced()
    assert held is not None and core_event_offset(fresh) == held.offset
    assert [row["active"] for row in held.core["workspaces"]] == [row["active"] for row in fresh["workspaces"]]
    assert any(row["active"] for row in held.core["workspaces"]), "the control: some row IS active"
    assert _differing_sections(held.core, fresh) == ["prompt_observability"]


def test_a_frame_that_does_not_chain_from_the_held_offset_drops_the_core(seeded):
    frames = _stream()
    _next_content(frames)
    held = resident_core.held()
    assert held is not None
    resident_core.observe({"type": "patch", "base_offset": held.offset + 1,
                           "watermark": {"event_offset": held.offset + 9}, "patches": []})
    assert resident_core.held() is None


def test_a_patch_the_fold_refuses_drops_the_core_instead_of_guessing(seeded):
    frames = _stream()
    _next_content(frames)
    held = resident_core.held()
    resident_core.observe({"type": "patch", "base_offset": held.offset, "watermark": {"event_offset": held.offset + 9},
                           "patches": [{"entity": "persona_instance", "id": "x", "op": "refresh"}]})
    assert resident_core.held() is None


def test_a_stale_first_core_is_never_held(seeded):
    frames = _stream()
    hydrate = _next_content(frames)
    stale = {**hydrate, "core": {**hydrate["core"], "parity": {**hydrate["core"]["parity"], "freshness": {"state": "stale"}}}}
    resident_core.observe(stale)
    assert resident_core.held() is None
    resident_core.observe(hydrate)
    assert resident_core.held() is not None, "the control: the same frame, fresh, is held"
