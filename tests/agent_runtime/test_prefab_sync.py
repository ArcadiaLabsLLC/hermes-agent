"""USER PREFABS travel: the third whole-document family (design-sweep-d2 § D2.12).

``prefab_store.PREFAB_FAMILY`` on ``realm_sync/document_family.py``: published at
``store/prefabs/<profile>/<prefab>.json``, adopt / keep / HOLD per prefab, a
never-synced baseline, ``upstream_absent`` never a delete, and the status row.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.prefab_store import (
    PrefabStore,
    apply_prefab_pull,
    prefab_document_hash,
    prefab_token,
    read_prefab_baseline,
    update_prefab_baseline_after_publish,
)
from agent_runtime.realm_sync.publish_scans import _prefab_publish_scan
from agent_runtime.realm_sync.status import _prefab_status_row

REALM = "realm_pf"


def _doc(label: str, *, edit: int = 0) -> bytes:
    return json.dumps(
        {"v": 1, "id": "p1", "label": label, "savedAt": "2026-10-18T00:00:00Z",
         "document": {"version": 9, "nodes": [edit]}},
        indent=2,
    ).encode("utf-8")


def _publish(subtree, profile: str, prefab_id: str, raw: bytes) -> None:
    target = subtree / "store" / "prefabs" / profile / f"{prefab_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


@pytest.fixture
def subtree(isolate_agent_runtime_root, tmp_path):
    root = tmp_path / "subtree"
    (root / "store" / "prefabs").mkdir(parents=True)
    return root


def test_a_published_prefab_is_adopted_onto_its_profiles_shelf(subtree):
    raw = _doc("Desk cluster")
    _publish(subtree, "alice", "p1", raw)
    summary = apply_prefab_pull(REALM, subtree)
    assert summary.adopted == ["alice/p1"]
    assert PrefabStore("alice").read("p1") == raw  # verbatim bytes
    assert read_prefab_baseline(REALM) == {"prefab:alice/p1": prefab_document_hash(raw)}
    assert summary.as_dict()["source"] == "subtree"


def test_an_unchanged_prefab_converges(subtree):
    raw = _doc("Desk cluster")
    PrefabStore("alice").write("p1", raw)
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(raw)})
    _publish(subtree, "alice", "p1", raw)
    assert apply_prefab_pull(REALM, subtree).converged == ["alice/p1"]


def test_a_local_edit_the_realm_did_not_make_is_kept(subtree):
    base = _doc("Desk cluster")
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(base)})
    PrefabStore("alice").write("p1", _doc("Desk cluster", edit=1))
    _publish(subtree, "alice", "p1", base)
    summary = apply_prefab_pull(REALM, subtree)
    assert summary.kept_local == ["alice/p1"]
    assert PrefabStore("alice").read("p1") == _doc("Desk cluster", edit=1)


def test_both_sides_changed_is_a_hold_with_a_parked_copy(subtree):
    base = _doc("Desk cluster")
    mine, theirs = _doc("Desk cluster", edit=1), _doc("Desk cluster", edit=2)
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(base)})
    PrefabStore("alice").write("p1", mine)
    _publish(subtree, "alice", "p1", theirs)
    summary = apply_prefab_pull(REALM, subtree)
    assert summary.held == ["alice/p1"]
    assert PrefabStore("alice").read("p1") == mine  # a locally changed prefab is never overwritten
    parked = json.loads(paths.prefab_conflict_path(REALM, "alice", "p1").read_text(encoding="utf-8"))
    assert parked["prefab_token"] == "alice/p1"
    assert parked["remote_document"] == theirs.decode("utf-8")


def test_upstream_absent_never_deletes(subtree):
    raw = _doc("Desk cluster")
    PrefabStore("alice").write("p1", raw)
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(raw)})
    _publish(subtree, "alice", "other", _doc("Other"))
    summary = apply_prefab_pull(REALM, subtree)
    assert summary.upstream_absent == ["alice/p1"]
    assert PrefabStore("alice").read("p1") == raw


def test_an_unreadable_published_prefab_is_refused_by_name(subtree):
    _publish(subtree, "alice", "bad", b"{not json")
    _publish(subtree, "alice", "nolabel", json.dumps({"document": {}}).encode())
    summary = apply_prefab_pull(REALM, subtree)
    assert [row["key"] for row in summary.refused] == ["alice/bad", "alice/nolabel"]
    assert {row["code"] for row in summary.refused} == {"unreadable_remote_prefab"}
    assert PrefabStore("alice").read("bad") is None


def test_no_prefab_directory_is_no_source_and_no_removal(isolate_agent_runtime_root, tmp_path):
    raw = _doc("Desk cluster")
    PrefabStore("alice").write("p1", raw)
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(raw)})
    summary = apply_prefab_pull(REALM, tmp_path / "empty")
    assert summary.as_dict()["source"] is None
    assert summary.upstream_absent == []
    assert PrefabStore("alice").read("p1") == raw


def test_the_publish_scan_lists_every_shelf_and_refuses_a_broken_prefab(isolate_agent_runtime_root):
    PrefabStore("alice").write("p1", _doc("A"))
    PrefabStore("bob").write("p2", _doc("B"))
    broken = paths.prefab_path("bob", "broken")
    broken.write_bytes(b"{")
    scan = _prefab_publish_scan()
    assert sorted(a.relative_path for a in scan.artifacts) == [
        "store/prefabs/alice/p1.json", "store/prefabs/bob/p2.json"]
    assert {a.kind for a in scan.artifacts} == {"prefab"}
    assert sorted(scan.hashes) == ["alice/p1", "bob/p2"]
    assert scan.refused == [{"prefab_token": "bob/broken", "reason": "unreadable_document", "error": "PrefabDocumentError"}]


def test_the_status_row_counts_unpublished_and_held(isolate_agent_runtime_root):
    raw = _doc("A")
    PrefabStore("alice").write("p1", raw)
    PrefabStore("alice").write("p2", _doc("B"))
    update_prefab_baseline_after_publish(REALM, {"alice/p1": prefab_document_hash(raw)})
    held = paths.prefab_conflict_path(REALM, "bob", "p9")
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text("{}", encoding="utf-8")
    row = _prefab_status_row(REALM)
    assert row == {"publishable": 2, "unpublished": 1, "held": ["bob/p9"], "refused": []}


def test_prefab_token_is_the_profile_and_prefab_tokens():
    assert prefab_token("alice", "p 1") == "alice/p_1"


# --- the wiring: publish mints the artifact, records the baseline; pull acks it ---


def test_publish_carries_the_shelf_and_a_pull_after_it_is_not_a_hold(
    isolate_agent_runtime_root, persisted_persona_samples, tmp_path
):
    import subprocess

    from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
    from agent_runtime.store import RealmStore, WorkspaceStore

    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True, text=True)

    repo, bare = tmp_path / "repo", tmp_path / "origin.git"
    git("init", "--bare", str(bare))
    git("init", str(repo))
    git("-C", str(repo), "config", "user.email", "prefab-sync-test@localhost")
    git("-C", str(repo), "config", "user.name", "Prefab Sync Test")
    git("-C", str(repo), "commit", "--allow-empty", "-m", "init")
    git("-C", str(repo), "remote", "add", "origin", str(bare))
    git("-C", str(repo), "push", "-u", "origin", "HEAD")
    realm = RealmStore().create(name="Prefab Realm")
    realm.sync_manifest_ref = str(repo)
    realm = RealmStore().save(realm)
    WorkspaceStore().create(name="Shelf", realm_id=realm.id)
    raw = _doc("Desk cluster")
    PrefabStore("alice").write("p1", raw)

    published = publish_realm_sync(realm.id, dry_run=True)
    assert published["prefab_sync"]["refused"] == []
    subtree = tmp_path / "repo" / "realms" / paths.safe_path_token(realm.id)
    publish_realm_sync(realm.id)
    assert (subtree / "store" / "prefabs" / "alice" / "p1.json").read_bytes() == raw
    assert read_prefab_baseline(realm.id) == {"prefab:alice/p1": prefab_document_hash(raw)}

    result = pull_realm_sync(realm.id)
    assert result["prefab_sync"]["converged"] == ["alice/p1"]
    assert result["prefab_sync"]["held"] == []
