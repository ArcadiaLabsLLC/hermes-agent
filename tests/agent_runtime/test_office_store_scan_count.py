"""One actor scan per office upsert, threaded to the fence, the unaimed placement
and the patch lane (RT-OFFICE-PATCH-LANE-SCANS-EVERY-UPSERT, stage S2).

KILLING MUTATIONS:
(a) ``_emit_actor_patch`` ignores ``scan`` and rescans -> the "once" counts red at 2.
(b) ``upsert_actor`` hands the patch lane the pre-write scan without
    ``with_written`` -> a 200-actor floor plus one new actor reads 200 and emits a
    patch instead of ``refresh`` -> the 201 test reds.
"""

from __future__ import annotations

import pytest

from agent_runtime.state_patches import office as office_patches
from agent_runtime.models import OfficeActor, OfficeItem
from agent_runtime.office_models import MAX_OFFICE_ACTORS_PROJECTED
from agent_runtime.office_store import OfficeStore
from agent_runtime.office_store.files import _write_actor
from agent_runtime.store import WorkspaceStore


def _make_workspace() -> str:
    ws = WorkspaceStore().create(name="Default")
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _seed_floor(ws: str, count: int) -> None:
    """``count`` furniture desks written straight to disk (no upsert, no scans)."""
    OfficeStore().ensure_surface(ws, created_by="seed")
    for i in range(count):
        key = f"desk_{i:08x}"
        _write_actor(
            OfficeActor(
                actor_key=key,
                workspace_id=ws,
                persona_id=key,
                items=[OfficeItem(item_id=key, persona_id=key, kind="desk", position=[float(i), 0.0], folder="Desks")],
            )
        )


def _counting_scans(monkeypatch) -> list[str]:
    calls: list[str] = []
    real = OfficeStore.scan_actors

    def counting(self, workspace_id, *a, **k):
        calls.append(workspace_id)
        return real(self, workspace_id, *a, **k)

    monkeypatch.setattr(OfficeStore, "scan_actors", counting)
    return calls


def _recording_patch_kinds(monkeypatch) -> list[str]:
    kinds: list[str] = []
    monkeypatch.setattr(
        office_patches, "emit_office_actor_patch", lambda *a, **k: kinds.append("office_actor")
    )
    monkeypatch.setattr(
        office_patches, "emit_office_actor_refresh", lambda *a, **k: kinds.append("refresh")
    )
    return kinds


def _unaimed_persona(persona_id: str, instance: str) -> dict:
    return {
        "persona_id": persona_id,
        "persona_instance_id": instance,
        "items": [{"item_id": instance, "persona_id": persona_id, "kind": "agent", "folder": "Agents"}],
    }


def _class_keyed_persona(persona_id: str) -> dict:
    return {
        "persona_id": persona_id,
        "items": [
            {"item_id": persona_id, "persona_id": persona_id, "kind": "agent", "position": [1.5, 2.0], "folder": "Agents"}
        ],
    }


def _furniture(desk_id: str) -> dict:
    return {
        "persona_id": desk_id,
        "actor_kind": "furniture",
        "items": [{"item_id": desk_id, "persona_id": desk_id, "kind": "desk", "position": [0.0, 9.0], "folder": "Desks"}],
    }


def test_a_persona_upsert_on_the_unaimed_lane_scans_once(monkeypatch):
    ws = _make_workspace()
    _seed_floor(ws, 5)
    scans = _counting_scans(monkeypatch)
    kinds = _recording_patch_kinds(monkeypatch)

    store = OfficeStore()
    store.upsert_actor(ws, _unaimed_persona("qa", "personainst_scan_a"), position_policy=lambda scan: (3.0, 4.0))

    assert scans == [ws]
    assert kinds == ["office_actor"]


def test_a_class_keyed_persona_upsert_scans_once(monkeypatch):
    ws = _make_workspace()
    _seed_floor(ws, 5)
    scans = _counting_scans(monkeypatch)

    OfficeStore().upsert_actor(ws, _class_keyed_persona("dev"))

    assert scans == [ws]


def test_a_furniture_upsert_scans_once_and_patches_a_small_floor(monkeypatch):
    ws = _make_workspace()
    _seed_floor(ws, 5)
    scans = _counting_scans(monkeypatch)
    kinds = _recording_patch_kinds(monkeypatch)

    OfficeStore().upsert_actor(ws, _furniture("desk_ffffffff"))

    assert scans == [ws]
    assert kinds == ["office_actor"]


@pytest.mark.parametrize(
    "payload, policy",
    [
        (_class_keyed_persona("dev"), None),
        (_unaimed_persona("qa", "personainst_scan_b"), lambda scan: (3.0, 4.0)),
    ],
    ids=["class_keyed", "unaimed"],
)
def test_a_new_actor_on_a_full_floor_refreshes_through_the_threaded_scan(monkeypatch, payload, policy):
    """200 on disk + the one written = 201 > the projection cap -> ``refresh``."""
    ws = _make_workspace()
    _seed_floor(ws, MAX_OFFICE_ACTORS_PROJECTED)
    scans = _counting_scans(monkeypatch)
    kinds = _recording_patch_kinds(monkeypatch)

    OfficeStore().upsert_actor(ws, payload, position_policy=policy)

    assert scans == [ws]
    assert kinds == ["refresh"]
