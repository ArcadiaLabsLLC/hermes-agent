"""The persona-DEFINITION family has ONE authority: the resolved record.

Publish builds each ``store/personas.yaml`` body from the resolved persona record
(store over config, store wins). Until this change the PULL compared and wrote
only ``config.yaml agent_runtime.personas.<id>``, so a pulled model landed in a
config key the store record shadowed, a local store edit (the launcher's model
switcher writes the store) was invisible to pull and to status, and nothing
offered a revert. Owner ruling 2026-09-28: one authority — the resolved record;
a mismatch with the last-synced baseline is a LOCAL CHANGE, and revert is
offered.

Each test below was run red against the pre-change tree; the failing line is
recorded in the commit message.
"""

from __future__ import annotations

import pytest

from agent_runtime import paths, yaml_io
from agent_runtime.models import AgentPersona
from agent_runtime.persona_config_sync import (
    PROJECTION_KIND,
    PROJECTION_RELATIVE_PATH,
    apply_persona_config_pull,
    load_raw_config,
    persona_def_hash,
    project_persona_definitions,
    read_persona_config_baseline,
    write_persona_config_baseline,
)
from agent_runtime.store import AgentStore, RealmStore, WorkspaceStore
from hermes_constants import get_config_path

FAMILY = "persona_definition"


# ── fixture ────────────────────────────────────────────────────────────────


def _member_config(personas: dict | None = None) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml_io.dump(
            {
                "model": {"default": "member-model", "provider": "member-provider"},
                "agent_runtime": {"personas": personas or {}},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _store_dev(model: str = "sol") -> AgentPersona:
    return AgentStore().save(
        AgentPersona(
            id="dev",
            display_name="Dev",
            role="developer",
            model=model,
            provider="openai",
            api_mode="chat_completions",
            toolsets=[],
        )
    )


def _local_body(persona_id: str = "dev") -> dict:
    """What publish would ship for ``persona_id`` right now."""

    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config

    records = {p.id: p for p in ensure_persisted_personas(load_agent_runtime_config())}
    return project_persona_definitions(
        [persona_id], raw_config=load_raw_config(), records=records
    ).personas[persona_id]


def _realm(tmp_path) -> str:
    realm = RealmStore().create(name="Realm")
    ws = WorkspaceStore().create(name="WS", realm_id=realm.id)
    ws.agent_ids = ["dev"]
    WorkspaceStore().save(ws)
    realm = RealmStore().get(realm.id)
    realm.workspace_ids.append(ws.id)
    realm.sync_manifest_ref = str(tmp_path / "sync_repo")
    RealmStore().save(realm)
    WorkspaceStore().set_active(ws.id)
    return realm.id


def _subtree(realm_id: str, tmp_path):
    path = tmp_path / "sync_repo" / "realms" / paths.safe_path_token(realm_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _publish_to_subtree(subtree, personas: dict) -> None:
    target = subtree.joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml_io.dump({"kind": PROJECTION_KIND, "schema_version": 1, "personas": personas}, sort_keys=True),
        encoding="utf-8",
    )


def _persona_rows(realm_id: str):
    from agent_runtime.realm_sync import _workspaces_for_realm, store_drift_items

    workspaces = _workspaces_for_realm(RealmStore().get(realm_id))
    return [item for item in store_drift_items(realm_id, workspaces) if item.family == FAMILY]


def _record_publish(realm_id: str) -> None:
    """The publish's own baseline receipt, over the publish's own resolution."""

    from agent_runtime.realm_sync import _resolve_artifacts_with_projection
    from agent_runtime.realm_sync.publish import _record_persona_config_baseline

    _record_persona_config_baseline(RealmStore().get(realm_id), _resolve_artifacts_with_projection(realm_id))


# ── 1. pull adopts into the record ──────────────────────────────────────────


def test_a_pulled_model_lands_in_the_store_record_not_a_shadowed_config_key(tmp_path):
    _member_config()
    _store_dev("sol")
    synced = _local_body()
    write_persona_config_baseline("r", {"dev": persona_def_hash(synced)})
    remote = {**synced, "model": "gpt-5.6-luna", "chat_lane_restore_toolsets": ["web"]}
    subtree = tmp_path / "sub"
    _publish_to_subtree(subtree, {"dev": remote})

    summary = apply_persona_config_pull("r", subtree)

    assert summary.adopted == ["dev"]
    assert AgentStore().get("dev").model == "gpt-5.6-luna"
    # A key the record cannot carry still goes to config — its only home.
    personas = (yaml_io.load(get_config_path().read_text(encoding="utf-8")) or {})["agent_runtime"]["personas"]
    assert personas["dev"]["chat_lane_restore_toolsets"] == ["web"]
    assert "model" not in personas["dev"]
    assert _local_body() == remote
    assert read_persona_config_baseline("r")["dev"] == persona_def_hash(remote)


def test_a_local_store_edit_is_a_local_change_to_the_pull(tmp_path):
    _member_config()
    _store_dev("sol")
    synced = _local_body()
    write_persona_config_baseline("r", {"dev": persona_def_hash(synced)})
    subtree = tmp_path / "sub"
    _publish_to_subtree(subtree, {"dev": synced})
    _store_dev("my-edit")

    summary = apply_persona_config_pull("r", subtree)

    assert summary.kept_local == ["dev"]
    assert AgentStore().get("dev").model == "my-edit"


# ── 2. a local edit is drift, and an unchanged record is not ────────────────


def test_a_local_record_edit_is_a_persona_definition_drift_row(tmp_path):
    _member_config()
    _store_dev("sol")
    realm_id = _realm(tmp_path)
    _record_publish(realm_id)
    # Positive control: the record as published is no drift at all.
    assert _persona_rows(realm_id) == []

    _store_dev("my-edit")

    rows = _persona_rows(realm_id)
    assert [(r.container, r.item_key, r.kind) for r in rows] == [("", "dev", "changed")]
    assert rows[0].spec == "persona_definition::dev"


def test_status_counts_the_persona_family_and_lights_unpublished(tmp_path, monkeypatch):
    from agent_runtime.realm_sync import status as realm_sync

    _member_config()
    _store_dev("sol")
    realm_id = _realm(tmp_path)
    _record_publish(realm_id)
    _store_dev("my-edit")
    monkeypatch.setattr(realm_sync, "_ensure_sync_repo", lambda realm, credential=None: tmp_path / "sync_repo")
    monkeypatch.setattr(realm_sync, "_refresh_remote_tracking", lambda repo, credential=None: {"checked": False, "error": None})
    monkeypatch.setattr(realm_sync, "_git_state", lambda repo: {"ahead": 0, "behind": 0, "conflicts": [], "dirty": False})

    status = realm_sync.realm_sync_status(realm_id)

    assert status["store_drift"]["personas"] == {"personas_changed": 1, "personas_added": 0}
    assert {"family": FAMILY, "container": "", "item_key": "dev", "kind": "changed"} in status["store_drift"]["items"]
    assert status["unpublished_changes"] is True


# ── 3. revert restores the last-pulled body into the record ─────────────────


def test_revert_restores_the_record_from_the_last_pulled_body(tmp_path):
    from agent_runtime.realm_revert import revert_realm_sync

    _member_config()
    _store_dev("sol")
    realm_id = _realm(tmp_path)
    _publish_to_subtree(_subtree(realm_id, tmp_path), {"dev": _local_body()})
    _record_publish(realm_id)
    _store_dev("my-edit")

    result = revert_realm_sync(realm_id, item_specs=["persona_definition::dev"])

    assert [row["outcome"] for row in result["items"]] == ["reverted_to_upstream"]
    assert AgentStore().get("dev").model == "sol"
    assert _persona_rows(realm_id) == []


def test_revert_never_deletes_a_persona_the_realm_does_not_have(tmp_path):
    from agent_runtime.realm_revert import revert_realm_sync

    _member_config()
    _store_dev("sol")
    realm_id = _realm(tmp_path)
    _subtree(realm_id, tmp_path)  # pulled, but carries no persona definitions

    result = revert_realm_sync(realm_id, item_specs=["persona_definition::dev"])

    assert [row["outcome"] for row in result["items"]] == ["refused_no_upstream"]
    assert AgentStore().get("dev").model == "sol"


# ── 4. publish clears the drift ─────────────────────────────────────────────


def test_publish_advances_the_baseline_so_the_drift_clears(tmp_path):
    _member_config()
    _store_dev("sol")
    realm_id = _realm(tmp_path)
    _record_publish(realm_id)
    _store_dev("my-edit")
    assert len(_persona_rows(realm_id)) == 1

    _record_publish(realm_id)

    assert _persona_rows(realm_id) == []
