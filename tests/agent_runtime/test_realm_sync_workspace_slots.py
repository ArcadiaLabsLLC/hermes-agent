"""The WORKSPACE_SLOTS realm-sync family (plan ``build-running-work-2026-10-04.md`` §3.1, row H5a).

Key-wise at three depths: slot names union, a slot's record by newest recipe revision then
``issued_at`` (a tombstone is a record), machines disjoint by id.
"""

from __future__ import annotations

import json

from agent_runtime import paths
from agent_runtime.realm_sync.families import SyncFamily, _destination_for_sync_path, _kind_for_sync_path
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import load_document, write_document
from agent_runtime.workspace_slots_sync import apply_workspace_slots_pull, merge_documents, publish_artifacts

OLD = "2026-10-04T10:00:00+00:00"
NEW = "2026-10-04T12:00:00+00:00"


def _slot(issued_at: str, *, removed: bool = False, revision: int = 0, url: str = "https://x/launcher.git") -> dict:
    return {"repo": {"clone_url": url, "default_branch": "main"}, "toolchain": {}, "context": {"files": ["AGENTS.md"]},
            "recipe": {"revision": revision, "steps": []}, "issued_at": issued_at,
            "removed_at": issued_at if removed else None}


def _doc(slots: dict, machines: dict | None = None, issued_at: str = OLD) -> dict:
    return {"schema_version": 1, "workspace_id": "ws_a", "issued_at": issued_at, "slots": slots, "machines": machines or {}}


def test_two_machines_reporting_one_slot_merge_to_the_union():
    mine = _doc({"launcher": _slot(OLD)}, {"mach_a": {"reported_at": OLD, "slots": {"launcher": {"bound": True}}}})
    theirs = _doc({"launcher": _slot(OLD)}, {"mach_b": {"reported_at": OLD, "slots": {"launcher": {"bound": False}}}})
    merged = merge_documents(mine, theirs)
    assert sorted(merged["machines"]) == ["mach_a", "mach_b"]
    assert merged["machines"]["mach_a"]["slots"]["launcher"]["bound"] is True


def test_a_stale_peer_loses_to_the_newer_tombstone():
    mine = _doc({"launcher": _slot(NEW, removed=True), "backend": _slot(OLD)}, issued_at=NEW)
    stale = _doc({"launcher": _slot(OLD), "hermes": _slot(OLD)})
    merged = merge_documents(mine, stale)
    assert merged["slots"]["launcher"]["removed_at"] == NEW
    assert sorted(merged["slots"]) == ["backend", "hermes", "launcher"]  # names union
    # Positive control: a re-declaration NEWER than the tombstone brings the slot back.
    redeclared = merge_documents(mine, _doc({"launcher": _slot("2026-10-04T13:00:00+00:00")}))
    assert redeclared["slots"]["launcher"]["removed_at"] is None


def test_a_higher_recipe_revision_wins_before_issued_at():
    mine = _doc({"launcher": _slot(NEW, revision=1, url="https://x/mine.git")})
    theirs = _doc({"launcher": _slot(OLD, revision=2, url="https://x/theirs.git")})
    assert merge_documents(mine, theirs)["slots"]["launcher"]["repo"]["clone_url"] == "https://x/theirs.git"


def test_the_same_machine_keeps_its_newest_report():
    mine = _doc({}, {"mach_a": {"reported_at": NEW, "slots": {"launcher": {"status": "ready"}}}})
    echoed = _doc({}, {"mach_a": {"reported_at": OLD, "slots": {"launcher": {"status": "not_cloned"}}}})
    assert merge_documents(mine, echoed)["machines"]["mach_a"]["reported_at"] == NEW


def test_the_pull_applier_merges_into_the_local_document(tmp_path):
    workspace = WorkspaceStore().create(name="Synced").id
    write_document(workspace, {**_doc({"launcher": _slot(OLD)}), "workspace_id": workspace})
    published = tmp_path / "subtree" / "store" / "workspace_slots"
    published.mkdir(parents=True)
    remote = {**_doc({"backend": _slot(OLD)}, {"mach_b": {"reported_at": OLD, "slots": {}}}), "workspace_id": workspace}
    (published / paths.workspace_slots_path(workspace).name).write_text(json.dumps(remote), encoding="utf-8")
    summary = apply_workspace_slots_pull("realm", tmp_path / "subtree")
    assert summary.as_dict()["source"] == 1 and summary.changed
    local = load_document(workspace)
    assert sorted(local["slots"]) == ["backend", "launcher"] and "mach_b" in local["machines"]
    # A second pull of the same bytes changes nothing.
    assert apply_workspace_slots_pull("realm", tmp_path / "subtree").changed is False


def test_the_family_owns_its_paths_and_publishes_one_document_per_workspace():
    rel = "store/workspace_slots/ws_a.json"
    assert _kind_for_sync_path(rel) == SyncFamily.WORKSPACE_SLOTS
    assert _destination_for_sync_path(rel) is None  # the applier owns it, never the generic loop
    store = WorkspaceStore()
    with_doc, without_doc = store.create(name="Has slots"), store.create(name="No slots")
    write_document(with_doc.id, {**_doc({"launcher": _slot(OLD)}), "workspace_id": with_doc.id})
    [artifact] = publish_artifacts([with_doc, without_doc])
    assert artifact.kind == SyncFamily.WORKSPACE_SLOTS
    assert artifact.relative_path == f"store/workspace_slots/{paths.workspace_slots_path(with_doc.id).name}"
