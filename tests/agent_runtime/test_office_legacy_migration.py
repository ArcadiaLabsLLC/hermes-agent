"""The one-shot office old-schema cleanups (``agent_runtime.office_legacy_migration``).

Owner rule 2026-09-18: old schema is deleted and the count reported. Autouse
conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import json

from agent_runtime import office_models, paths
from agent_runtime.office_legacy_migration import run_office_legacy_migrations_once
from agent_runtime.office_store import OfficeStore
from agent_runtime.store import WorkspaceStore


def _workspace() -> str:
    ws = WorkspaceStore().create(name="Default")
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _agent_payload(persona_id: str = "dev") -> dict:
    return {
        "persona_id": persona_id,
        "items": [
            {"item_id": persona_id, "persona_id": persona_id, "kind": "agent", "position": [1.0, 2.0], "folder": "Agents"},
        ],
    }


def _inject_item_key(path, key: str, value) -> None:
    row = json.loads(path.read_text(encoding="utf-8"))
    for item in row["items"]:
        item[key] = value
    path.write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")


# ── RT-OFFICEITEM-MINTED-KIND ────────────────────────────────────────────────


def test_the_retired_minted_kind_is_stripped_from_disk_once_and_counted():
    """Live and archived files both lose the key; the hash does not move; the
    marker makes the second start a no-op."""

    ws = _workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _agent_payload("dev"))
    store.upsert_actor(ws, _agent_payload("ops"))
    store.remove_actor(ws, "ops")
    live = paths.office_actor_path(ws, "dev")
    archived = paths.office_archived_actor_path(ws, "ops")
    _inject_item_key(live, "minted_kind", "agent")
    _inject_item_key(archived, "minted_kind", "agent")
    hash_before = office_models.office_content_hash(store.get_actor(ws, "dev"))

    ran = run_office_legacy_migrations_once()

    report = ran["office_item_minted_kind.json"]
    assert report["stripped_items"] == 2
    assert report["errors"] == []
    for path in (live, archived):
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        assert all("minted_kind" not in item for item in items), path
    assert office_models.office_content_hash(store.get_actor(ws, "dev")) == hash_before
    assert (paths.store_root() / "migrations" / "office_item_minted_kind.json").exists()
    assert "office_item_minted_kind.json" not in run_office_legacy_migrations_once()


def test_the_store_no_longer_writes_the_retired_key():
    ws = _workspace()
    OfficeStore().upsert_actor(ws, _agent_payload("dev"))
    items = json.loads(paths.office_actor_path(ws, "dev").read_text(encoding="utf-8"))["items"]
    assert all("minted_kind" not in item for item in items)


# ── RT-DROPPED-LEGACY-DESK-LEAVES ────────────────────────────────────────────


def test_legacy_persona_addressed_desks_are_swept_once_and_counted():
    """A desk filed under a persona is dropped from a shared actor, an actor left
    with nothing is archived, and a generic (self-addressed) desk is untouched."""

    ws = _workspace()
    store = OfficeStore()
    store.upsert_actor(
        ws,
        {
            "persona_id": "dev",
            "items": [
                {"item_id": "dev", "persona_id": "dev", "kind": "agent", "position": [1.0, 2.0], "folder": "Agents"},
                {"item_id": "desk-dev", "persona_id": "dev", "kind": "desk", "position": [1.0, 3.0], "folder": "Desks"},
            ],
        },
    )
    store.upsert_actor(
        ws,
        {
            "persona_id": "ops",
            "items": [
                {"item_id": "ops_desk", "persona_id": "ops", "kind": "desk", "position": [4.0, 3.0], "folder": "Desks"},
            ],
        },
        allow_class_key=True,
    )
    store.upsert_actor(
        ws,
        {
            "persona_id": "desk_aaaaaaaa",
            "items": [
                {"item_id": "desk_aaaaaaaa", "persona_id": "desk_aaaaaaaa", "kind": "desk", "position": [6.0, 3.0], "folder": "Desks"},
            ],
        },
        allow_class_key=True,
    )

    ran = run_office_legacy_migrations_once()

    report = ran["office_legacy_desks.json"]
    assert report["dropped_desks"] == 2
    assert report["errors"] == []
    assert [item.item_id for item in store.get_actor(ws, "dev").items] == ["dev"]
    assert not store.actor_exists(ws, "ops")
    assert paths.office_archived_actor_path(ws, "ops").exists()
    assert [item.item_id for item in store.get_actor(ws, "desk_aaaaaaaa").items] == ["desk_aaaaaaaa"]
    assert "office_legacy_desks.json" not in run_office_legacy_migrations_once()
