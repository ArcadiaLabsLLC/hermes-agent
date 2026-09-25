"""Positive controls for two realm-sync dispatch tables whose killing mutation no
existing test reached (lane R4's CHANGE, recorded in its commit body):

* ``drift._BASELINE_KEY_OF`` — which baseline-sidecar key a drift row realigns.
  Dropping the ``board`` entry fell through to the office-actor key and every
  test stayed green, so the revert lane could have realigned the wrong entry.
* ``publish.BASELINE_FAMILIES`` — dropping the ``board`` record left a publish
  that never baselined its boards, again with every test green; the next pull
  would then hold the publisher's own cards.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime import board_models
from agent_runtime.board_store import BoardStore
from agent_runtime.board_sync import _board_key, _card_key, read_board_baseline
from agent_runtime.flow_graph_sync import flow_graph_baseline_key
from agent_runtime.office_sync import _actor_key, _surface_key
from agent_runtime.persona_instance_sync import instance_baseline_key
from agent_runtime.realm_sync import StoreDriftItem, SyncFamily, publish_realm_sync
from agent_runtime.skill_sync import skill_baseline_key
from agent_runtime.store import RealmStore, WorkspaceStore

_OWNER_KEYS = [
    (SyncFamily.BOARD, _board_key("c1")),
    (SyncFamily.BOARD_CARD, _card_key("c1", "k1")),
    (SyncFamily.OFFICE_SURFACE, _surface_key("c1")),
    (SyncFamily.OFFICE_ACTOR, _actor_key("c1", "k1")),
    (SyncFamily.PERSONA_INSTANCE, instance_baseline_key("k1")),
    (SyncFamily.SKILL, skill_baseline_key("k1")),
    (SyncFamily.FLOW_GRAPH, flow_graph_baseline_key("k1")),
]


def _row(family: SyncFamily) -> StoreDriftItem:
    return StoreDriftItem(family=family, container="c1", item_key="k1", kind="changed")


@pytest.mark.parametrize("family, expected", _OWNER_KEYS)
def test_a_drift_row_realigns_its_owners_baseline_key(family, expected):
    assert _row(family).baseline_key() == expected


def test_no_two_families_share_a_baseline_key():
    """The control that makes the test above mean something: were two owners'
    keys equal, a row routed to the wrong owner would still pass it."""

    keys = [expected for _family, expected in _OWNER_KEYS]
    assert len(set(keys)) == len(keys)


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
    realm = RealmStore().create(name="Board Realm")
    realm.sync_manifest_ref = str(repo)
    return RealmStore().save(realm)


def test_a_publish_records_the_board_baseline(isolate_agent_runtime_root, tmp_path):
    realm = _realm_with_remote(tmp_path)
    workspace = WorkspaceStore().create(name="WS", realm_id=realm.id)
    card = BoardStore().add_card(workspace_id=workspace.id, title="Ship me")
    board_id = board_models.default_board_id(workspace.id)
    assert read_board_baseline(realm.id) == {}

    result = publish_realm_sync(realm.id)

    assert result["state"] == "published"
    baseline = read_board_baseline(realm.id)
    assert f"{board_id}:board" in baseline
    assert any(key.endswith(f":card:{card.card_id}") for key in baseline)
