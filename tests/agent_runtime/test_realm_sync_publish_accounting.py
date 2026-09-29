"""H2: the publish envelope says WHICH paths moved and what drift the baselines left.

Contract: `EterniaLauncher/docs/mission_control/planned/realm-history-and-publish-policy-design-sheet.md`
§3 H2 — ``changed_paths`` / ``changed_count`` from the publish's own diff, and
``residual_drift`` rows (a store-drift row plus ``reason``: ``baseline_refused``,
``baseline_write_failed`` or ``not_in_publish_set``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runtime.board_store import BoardStore
from agent_runtime.realm_sync import SyncFamily, publish_realm_sync
from agent_runtime.realm_sync import publish as publish_module
from agent_runtime.store import RealmStore, WorkspaceStore


def _realm_with_remote(tmp_path: Path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True, text=True)
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    for args in (
        ("config", "user.email", "realm-sync-test@localhost"),
        ("config", "user.name", "Realm Sync Test"),
        ("commit", "--allow-empty", "-m", "init"),
        ("remote", "add", "origin", str(bare)),
        ("push", "-u", "origin", "HEAD"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    realm = RealmStore().create(name="Accounting Realm")
    realm.sync_manifest_ref = str(repo)
    return RealmStore().save(realm)


def test_a_publish_names_the_paths_it_changed_and_a_no_op_names_none(isolate_agent_runtime_root, tmp_path):
    realm = _realm_with_remote(tmp_path)
    workspace = WorkspaceStore().create(name="WS", realm_id=realm.id)
    card = BoardStore().add_card(workspace_id=workspace.id, title="Ship me")

    first = publish_realm_sync(realm.id)

    assert first["changed"] is True
    assert first["changed_count"] == len(first["changed_paths"]) > 0
    assert "manifest.json" not in first["changed_paths"]
    assert any(p.startswith("store/boards/") and p.endswith(f"{card.card_id}.json") for p in first["changed_paths"]), \
        first["changed_paths"]
    assert any(p.startswith("store/boards/") and p.endswith("/board.json") for p in first["changed_paths"])
    assert first["residual_drift"] == []  # every drifted row shipped and its baseline was recorded

    again = publish_realm_sync(realm.id)
    assert (again["changed"], again["changed_paths"], again["changed_count"]) == (False, [], 0)


def test_residual_drift_names_the_rows_a_failed_baseline_left(isolate_agent_runtime_root, tmp_path, monkeypatch):
    realm = _realm_with_remote(tmp_path)
    workspace = WorkspaceStore().create(name="WS", realm_id=realm.id)
    card = BoardStore().add_card(workspace_id=workspace.id, title="Ship me")

    def _boom(_realm, _resolved):
        raise OSError("baseline sidecar is read-only")

    monkeypatch.setattr(
        publish_module,
        "BASELINE_FAMILIES",
        tuple((family, _boom if family == SyncFamily.BOARD else record)
              for family, record in publish_module.BASELINE_FAMILIES),
    )

    result = publish_realm_sync(realm.id)

    residual = {(row["family"], row["item_key"]): row["reason"] for row in result["residual_drift"]}
    assert residual[(SyncFamily.BOARD_CARD, card.card_id)] == "baseline_write_failed", result["residual_drift"]
    assert all(row["family"] in (SyncFamily.BOARD, SyncFamily.BOARD_CARD) for row in result["residual_drift"])
