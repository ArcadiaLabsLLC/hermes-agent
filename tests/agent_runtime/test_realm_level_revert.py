"""A realm-synced LEVEL has a revert arm, and one count (plan ``realm-level-revert-arm-2026-10-15`` S2).

The arm's three transitions over the last-pulled subtree, each through the
``LevelStore`` door: a level the realm also carries is ADOPTED back, a level the
realm never carried is ARCHIVED (recoverable, never a bare delete), and a held
level offers no row at all. Every case ends on the next status, because a revert
that leaves the row standing is an exit that goes nowhere.
"""

from __future__ import annotations

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime.level_sync import LevelStore, level_baseline_key, level_document_hash, write_level_baseline
from agent_runtime.realm_revert import revert_realm_sync
from agent_runtime.realm_sync import realm_sync_status
from tests.agent_runtime.test_realm_sync_level_artifact import (
    _document,
    _realm_with_workspace_and_level,
    _subtree,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _level_rows(realm_id):
    return [row for row in realm_sync_status(realm_id)["store_drift"]["items"] if row["family"] == "level"]


def _publish_by_hand(repo, realm_id, token, raw):
    subtree = _subtree(repo, realm_id)
    subtree.mkdir(parents=True, exist_ok=True)
    (subtree / f"{token}.json").write_bytes(raw)


def test_an_edited_level_is_one_row_and_one_count(isolate_agent_runtime_root, tmp_path):
    realm, _repo, workspace = _realm_with_workspace_and_level(tmp_path)
    token = runtime_paths.safe_path_token(workspace.id)
    write_level_baseline(realm.id, {level_baseline_key(token): level_document_hash(_document(prop_x=9.0))})

    status = realm_sync_status(realm.id)

    assert [row for row in status["store_drift"]["items"] if row["family"] == "level"] == [
        {"family": "level", "container": token, "item_key": token, "kind": "changed"}
    ]
    assert status["store_drift"]["levels"]["levels_changed"] == 1
    assert status["levels"]["unpublished"] == 1  # the old key, still emitted for one release
    assert status["unpublished_changes"] is True


def test_revert_all_adopts_the_published_level_and_the_row_clears(isolate_agent_runtime_root, tmp_path):
    """An unbaselined local level the realm DOES carry: revert adopts the realm's
    bytes verbatim and records the baseline, so the next status has no row."""

    realm, repo, workspace = _realm_with_workspace_and_level(tmp_path)
    token = runtime_paths.safe_path_token(workspace.id)
    published = _document(prop_x=42.0)
    _publish_by_hand(repo, realm.id, token, published)
    assert [row["kind"] for row in _level_rows(realm.id)] == ["added"]

    result = revert_realm_sync(realm.id, revert_all=True)

    assert [(row["family"], row["outcome"]) for row in result["items"]] == [("level", "reverted_to_upstream")]
    assert LevelStore().read(workspace.id) == published
    assert _level_rows(realm.id) == []


def test_a_local_only_level_is_archived_never_deleted(isolate_agent_runtime_root, tmp_path):
    realm, repo, workspace = _realm_with_workspace_and_level(tmp_path)
    token = runtime_paths.safe_path_token(workspace.id)
    mine = LevelStore().read(workspace.id)
    _subtree(repo, realm.id).mkdir(parents=True, exist_ok=True)  # pulled, and carries no level

    result = revert_realm_sync(realm.id, item_specs=[f"level:{token}:{token}"])

    assert [row["outcome"] for row in result["items"]] == ["archived_local_only"]
    assert LevelStore().read(workspace.id) is None
    archive = runtime_paths.realm_sync_root() / runtime_paths.safe_path_token(realm.id) / "level_conflicts" / "archive"
    assert [path.read_bytes() for path in archive.glob(f"{token}.*.json")] == [mine]
    status = realm_sync_status(realm.id)
    assert status["levels"]["held"] == []  # an archive is not a hold
    assert _level_rows(realm.id) == []


def test_a_held_level_offers_no_revert_row(isolate_agent_runtime_root, tmp_path):
    """Control for the hold guard: the same edited level, plus a parked conflict."""

    realm, _repo, workspace = _realm_with_workspace_and_level(tmp_path)
    token = runtime_paths.safe_path_token(workspace.id)
    write_level_baseline(realm.id, {level_baseline_key(token): level_document_hash(_document(prop_x=9.0))})
    assert len(_level_rows(realm.id)) == 1

    conflict = runtime_paths.level_conflict_path(realm.id, token)
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_text("{}", encoding="utf-8")

    assert _level_rows(realm.id) == []
    assert realm_sync_status(realm.id)["levels"]["held"] == [token]
