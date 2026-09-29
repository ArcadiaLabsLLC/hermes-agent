"""``hermes harness realm sync revert <realm> --to <sha>`` — restore the local
store to one published version (H3, owner ruling 2026-09-29).

Pinned here: the store is restored to X's subtree, rows created after X are
KEPT (never archived, never deleted), no baseline is written so the restore
reads as local edits, upstream HEAD does not move, and the verb routes ``--to``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

import pytest

from utils import atomic_json_write

from agent_runtime import office_models, paths
from agent_runtime.office_store import OfficeStore
from agent_runtime.office_sync import read_office_baseline, update_office_baseline_after_sync
from agent_runtime.realm_revert_version import (
    OUTCOME_ALREADY_AT_VERSION,
    OUTCOME_KEPT_CREATED_AFTER,
    classify_version_restore,
    revert_realm_sync_to_version,
)
from agent_runtime.realm_revert import OUTCOME_RESTORED, OUTCOME_REVERTED, RevertAction
from agent_runtime.realm_sync import (
    DRIFT_FAMILY_OFFICE_ACTOR,
    DRIFT_FAMILY_OFFICE_SURFACE,
    DRIFT_KIND_ADDED,
    DRIFT_KIND_CHANGED,
    DRIFT_KIND_REMOVED,
    RealmSyncError,
    _office_store_drift,
    _workspaces_for_realm,
)
from agent_runtime.serde import to_jsonable
from agent_runtime.store import RealmStore, WorkspaceStore


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _payload(persona_id: str, x: float) -> dict:
    return {
        "persona_id": persona_id,
        "items": [{"item_id": persona_id, "persona_id": persona_id, "kind": "agent",
                   "position": [x, 2.0], "folder": "Agents"}],
    }


def _publish(realm_id: str, ws: str, repo, message: str) -> str:
    """What a publish does, locally: subtree mirrors the store, baseline follows,
    one commit. Returns the version sha."""

    store = OfficeStore()
    office_dir = repo / "realms" / paths.safe_path_token(realm_id) / "store" / "office" / paths.safe_path_token(ws)
    if office_dir.exists():
        shutil.rmtree(office_dir)
    atomic_json_write(office_dir / "office.json", to_jsonable(store.get_surface(ws)), indent=2, sort_keys=True)
    for actor in store.scan_actors(ws).actors:
        atomic_json_write(office_dir / "actors" / f"{office_models.actor_file_token(actor.actor_key)}.json",
                          to_jsonable(actor), indent=2, sort_keys=True)
    update_office_baseline_after_sync(realm_id, [ws])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def two_versions(tmp_path):
    """Version X: desk ``dev`` at x=1. HEAD: ``dev`` moved to x=5 and a desk
    ``late`` created. The store matches HEAD — no store drift at all."""

    realm = RealmStore().create(name="Realm")
    ws = WorkspaceStore().create(name="WS", realm_id=realm.id)
    realm = RealmStore().get(realm.id)
    realm.workspace_ids.append(ws.id)
    repo = tmp_path / "sync_repo"
    realm.sync_manifest_ref = str(repo)
    RealmStore().save(realm)
    WorkspaceStore().set_active(ws.id)
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")

    store = OfficeStore()
    store.upsert_actor(ws.id, _payload("dev", 1.0))
    version_x = _publish(realm.id, ws.id, repo, "X")
    store.upsert_actor(ws.id, _payload("dev", 5.0))
    store.upsert_actor(ws.id, _payload("late", 3.0))
    _publish(realm.id, ws.id, repo, "HEAD")
    return realm.id, ws.id, repo, version_x


def _office_drift(realm_id):
    return _office_store_drift(realm_id, _workspaces_for_realm(RealmStore().get(realm_id)))


def test_restores_version_x_keeps_later_rows_and_writes_no_baseline(two_versions):
    realm_id, ws, repo, version_x = two_versions
    head_before = _git(repo, "rev-parse", "HEAD")
    baseline_before = read_office_baseline(realm_id)
    assert _office_drift(realm_id)["actors_changed"] == 0  # nothing drifted: plain revert has no rows

    result = revert_realm_sync_to_version(realm_id, to=version_x, revert_all=True)

    by_key = {(row["family"], row["item_key"]): row["outcome"] for row in result["items"]}
    assert by_key[(DRIFT_FAMILY_OFFICE_ACTOR, "dev")] == OUTCOME_REVERTED
    assert by_key[(DRIFT_FAMILY_OFFICE_ACTOR, "late")] == OUTCOME_KEPT_CREATED_AFTER
    store = OfficeStore()
    assert store.get_actor(ws, "dev").items[0].position[0] == 1.0
    # Created after X: kept exactly where it was — never archived, never deleted.
    assert store.actor_exists(ws, "late")
    assert store.get_actor(ws, "late").items[0].position[0] == 3.0
    # No baseline written: the restore reads as a local edit to publish or revert.
    assert read_office_baseline(realm_id) == baseline_before
    assert _office_drift(realm_id)["actors_changed"] == 1
    assert result["to"] == version_x and result["kept"] == 1 and result["refused"] == 0
    # Upstream HEAD unchanged.
    assert _git(repo, "rev-parse", "HEAD") == head_before


def test_a_row_archived_locally_after_x_is_restored(two_versions):
    realm_id, ws, repo, version_x = two_versions
    OfficeStore().remove_actor(ws, "dev")

    result = revert_realm_sync_to_version(realm_id, to=version_x, item_specs=[f"office_actor:{ws}:dev"])

    assert [row["outcome"] for row in result["items"]] == [OUTCOME_RESTORED]
    assert OfficeStore().get_actor(ws, "dev").items[0].position[0] == 1.0


def test_dry_run_writes_nothing(two_versions):
    realm_id, ws, repo, version_x = two_versions

    result = revert_realm_sync_to_version(realm_id, to=version_x, revert_all=True, dry_run=True)

    assert result["reverted"] >= 1
    assert OfficeStore().get_actor(ws, "dev").items[0].position[0] == 5.0


@pytest.mark.parametrize("to", ["deadbeef" * 5, "--all", ""])
def test_an_unknown_or_hostile_version_is_refused_typed(two_versions, to):
    realm_id, _ws, _repo, _x = two_versions
    with pytest.raises(RealmSyncError) as exc:
        revert_realm_sync_to_version(realm_id, to=to, revert_all=True)
    assert exc.value.code in {"version_not_found", "invalid_request"}


@pytest.mark.parametrize(
    "family,kind,present,action,outcome",
    [
        (DRIFT_FAMILY_OFFICE_ACTOR, DRIFT_KIND_CHANGED, True, RevertAction.ADOPT, OUTCOME_REVERTED),
        (DRIFT_FAMILY_OFFICE_ACTOR, DRIFT_KIND_REMOVED, True, RevertAction.RESTORE, OUTCOME_RESTORED),
        (DRIFT_FAMILY_OFFICE_SURFACE, DRIFT_KIND_REMOVED, True, RevertAction.ADOPT, OUTCOME_REVERTED),
        (DRIFT_FAMILY_OFFICE_ACTOR, DRIFT_KIND_ADDED, False, None, OUTCOME_KEPT_CREATED_AFTER),
        (DRIFT_FAMILY_OFFICE_ACTOR, DRIFT_KIND_CHANGED, False, None, OUTCOME_KEPT_CREATED_AFTER),
        (DRIFT_FAMILY_OFFICE_ACTOR, DRIFT_KIND_REMOVED, False, None, OUTCOME_ALREADY_AT_VERSION),
    ],
)
def test_version_restore_table(family, kind, present, action, outcome):
    assert classify_version_restore(family=family, kind=kind, version_present=present) == (action, outcome)


def test_the_verb_routes_to(two_versions, capsys):
    from hermes_cli import harness

    realm_id, ws, _repo, version_x = two_versions
    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "realm", "sync", "revert", realm_id, "--to", version_x,
                            "--all", "--yes", "--json"])

    code = args.func(args)

    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["kind"] == "realm_sync_revert" and payload["to"] == version_x
    assert OfficeStore().get_actor(ws, "dev").items[0].position[0] == 1.0
