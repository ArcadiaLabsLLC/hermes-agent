"""The WORKSPACE_SLOTS realm-sync family (plan ``build-running-work-2026-10-04.md`` §3.1, row H5a).

Key-wise at three depths: slot names union, a slot's record by newest recipe revision then
``issued_at`` (a tombstone is a record), machines disjoint by id.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_runtime import paths
from agent_runtime.realm_sync.families import SyncFamily, _destination_for_sync_path, _kind_for_sync_path
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import SlotRefused, declare, load_document, machine_id, write_document
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


# ── a peer's document runs the local validators, entry by entry (row h-peerval) ──

SECRET = "not-a-real-token-value-0123456789"


def _publish(tmp_path, workspace: str, slots: dict, *, workspace_id: str | None = None) -> None:
    published = tmp_path / "subtree" / "store" / "workspace_slots"
    published.mkdir(parents=True, exist_ok=True)
    remote = {**_doc(slots, issued_at=NEW), "workspace_id": workspace_id or workspace}
    (published / paths.workspace_slots_path(workspace).name).write_text(json.dumps(remote), encoding="utf-8")


def _pull_into(tmp_path, slots: dict, *, local: dict | None = None) -> tuple[str, dict, dict]:
    workspace = WorkspaceStore().create(name="Peer").id
    if local is not None:
        write_document(workspace, {**_doc(local), "workspace_id": workspace})
    _publish(tmp_path, workspace, slots)
    summary = apply_workspace_slots_pull("realm", tmp_path / "subtree").as_dict()
    return workspace, load_document(workspace), summary


def _command(step_id: str, argv: list[str], **extra) -> dict:
    return {"id": step_id, "kind": "command", "label": " ".join(argv), "argv": argv, "cwd_slot": "launcher",
            "run": "on_setup_click", **extra}


def _with_steps(steps: list[dict], *, revision: int = 1) -> dict:
    return {**_slot(NEW, revision=revision), "recipe": {"revision": revision, "steps": steps}}


def _local_bytes(workspace: str) -> str:
    [artifact] = publish_artifacts([WorkspaceStore().get(workspace)])
    return artifact.source.read_text(encoding="utf-8")


def test_a_peer_slot_whose_name_is_not_a_root_name_is_dropped_and_named_by_digest(tmp_path):
    bad = f"../{SECRET}"
    workspace, local, summary = _pull_into(tmp_path, {bad: _slot(NEW), "launcher": _slot(NEW)})
    assert sorted(local["slots"]) == ["launcher"]
    [row] = summary["refused"]
    assert row["reason"] == "invalid_slot_name" and row["slot"].startswith("sha256:")
    assert SECRET not in json.dumps(summary) and SECRET not in _local_bytes(workspace)


def test_a_peer_clone_url_carrying_userinfo_never_replaces_the_local_slot(tmp_path):
    poisoned = _slot(NEW, revision=5, url=f"https://{SECRET}@github.com/x/launcher.git")
    workspace, local, summary = _pull_into(tmp_path, {"launcher": poisoned}, local={"launcher": _slot(OLD)})
    assert local["slots"]["launcher"]["repo"]["clone_url"] == "https://x/launcher.git"  # the local record stands
    assert summary["refused"] == [{"document": paths.workspace_slots_path(workspace).name, "slot": "launcher",
                                   "reason": "clone_url_carries_credential"}]
    assert SECRET not in json.dumps(summary) and SECRET not in _local_bytes(workspace)  # nothing to re-publish
    # Positive control: the same record with a credential-free URL wins on its higher revision.
    _publish(tmp_path, workspace, {"launcher": _slot(NEW, revision=5, url="https://github.com/x/launcher.git")})
    apply_workspace_slots_pull("realm", tmp_path / "subtree")
    assert load_document(workspace)["slots"]["launcher"]["repo"]["clone_url"] == "https://github.com/x/launcher.git"


@pytest.mark.parametrize("step", [
    _command("argv", ["git", "fetch", f"https://{SECRET}@github.com/x/y.git"], label="Fetch"),
    _command("label", ["flutter", "pub", "get"], label=f"token={SECRET}"),
    _command("env", ["flutter", "pub", "get"], env={"GITHUB_TOKEN": SECRET}),
    {"id": "tool:flutter", "hint": f"Authorization: Bearer {SECRET}"},
])
def test_a_credential_shaped_peer_recipe_step_is_dropped_alone(tmp_path, step):
    clean = _command("pub_get", ["flutter", "pub", "get"])
    workspace, local, summary = _pull_into(tmp_path, {"launcher": _with_steps([step, clean])})
    assert [s["id"] for s in local["slots"]["launcher"]["recipe"]["steps"]] == ["pub_get"]
    assert [(r["slot"], r["step"], r["reason"]) for r in summary["refused"]] == \
        [("launcher", step["id"], "credential_in_step")]
    assert SECRET not in json.dumps(summary) and SECRET not in _local_bytes(workspace)


def test_a_valid_peer_slot_and_step_survive_beside_bad_ones(tmp_path):
    backend = _with_steps([_command("bad", ["git", f"https://u:{SECRET}@h/r.git"]),
                           _command("migrate", ["python", "manage.py", "migrate"]),
                           {"id": "env_key:GONE", "hint": "orphaned by a re-declaration"}])
    workspace, local, summary = _pull_into(tmp_path, {
        "launcher": _slot(NEW, url=f"https://{SECRET}@x/launcher.git"), "backend": backend,
    })
    assert sorted(local["slots"]) == ["backend"]
    assert [s["id"] for s in local["slots"]["backend"]["recipe"]["steps"]] == ["migrate", "env_key:GONE"]
    assert sorted((r["slot"], r.get("step"), r["reason"]) for r in summary["refused"]) == [
        ("backend", "bad", "credential_in_step"), ("launcher", None, "clone_url_carries_credential")]
    assert summary["merged"] and SECRET not in _local_bytes(workspace)


def test_a_peer_document_filed_under_another_workspace_is_refused_whole(tmp_path):
    store = WorkspaceStore()
    victim, carrier = store.create(name="Victim").id, store.create(name="Carrier").id
    write_document(victim, {**_doc({"launcher": _slot(OLD)}), "workspace_id": victim})
    _publish(tmp_path, carrier, {"hijack": _slot(NEW)}, workspace_id=victim)
    summary = apply_workspace_slots_pull("realm", tmp_path / "subtree").as_dict()
    assert summary["refused"] == [{"document": paths.workspace_slots_path(carrier).name, "reason": "slot_document_misfiled"}]
    assert sorted(load_document(victim)["slots"]) == ["launcher"]


# ── a peer's machines block and stamps are not taken on trust (row h-trust) ──

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
FAR_FUTURE = "2999-01-01T00:00:00+00:00"


def _at(seconds: float) -> str:
    return (NOW + timedelta(seconds=seconds)).isoformat()


def _full_row() -> dict:
    """Every part ``workspace_slots_probe.report`` writes, in its own vocabularies."""

    return {"status": "needs_setup", "bound": True, "checkout": "matches",
            "tools": {"flutter": {"status": "set", "version": "3.41.2"}, "dart": {"status": "missing", "version": None}},
            "env_keys": {"FLUTTER_ROOT": "set", "PUB_CACHE": "missing"},
            "dotenv": {"present": True, "keys": {"ETERNIA_API_BASE": "unknown"}},
            "unknowns": [{"kind": "slot_probe_unknown", "evidence": "launcher: dart --version: TimeoutExpired",
                          "seen_at": NOW.timestamp() - 60}],
            "adopted_existing_root": False}


def _pull_doc(tmp_path, remote: dict, *, local: dict | None = None) -> tuple[str, dict, dict]:
    workspace = WorkspaceStore().create(name="Peer").id
    if local is not None:
        write_document(workspace, {**local, "workspace_id": workspace})
    published = tmp_path / "subtree" / "store" / "workspace_slots"
    published.mkdir(parents=True, exist_ok=True)
    (published / paths.workspace_slots_path(workspace).name).write_text(
        json.dumps({**remote, "workspace_id": workspace}), encoding="utf-8")
    summary = apply_workspace_slots_pull("realm", tmp_path / "subtree", now=NOW.timestamp()).as_dict()
    return workspace, load_document(workspace), summary


def _refusals(summary: dict) -> list[tuple]:
    return sorted(tuple(v for k, v in sorted(row.items()) if k != "document") for row in summary["refused"])


def _declare_now(workspace: str) -> dict:
    return declare(workspace, [{"name": "launcher", "repo": {"clone_url": "https://x/launcher.git"}}],
                   issued_at=datetime.now(timezone.utc).isoformat(), machine="mach_local")


def test_a_peer_copy_of_this_machines_report_never_replaces_it(tmp_path):
    me = machine_id()
    mine = {"reported_at": _at(-3600), "slots": {"launcher": {"status": "needs_setup", "bound": True, "unknowns": []}}}
    forged = {"reported_at": _at(-60), "slots": {"launcher": {"status": "ready", "bound": True, "unknowns": []}}}
    other = {"reported_at": _at(-60), "slots": {"launcher": _full_row()}}
    _, local, summary = _pull_doc(tmp_path, _doc({}, {me: forged, "mach_b": other}),
                                  local=_doc({}, {me: mine, "mach_b": {"reported_at": _at(-7200), "slots": {}}}))
    assert local["machines"][me] == mine  # authored here only: the newer peer copy is ignored
    # Positive control: another machine's newer report, every part valid, is carried as that machine's.
    assert local["machines"]["mach_b"] == other
    assert summary["refused"] == []


@pytest.mark.parametrize("bad", [
    {"token": SECRET},                                                  # a part report never writes
    {"status": SECRET},                                                 # a status outside the vocabulary
    {"tools": {"flutter": {"status": "set", "version": SECRET}}},       # a version that is not a version
    {"tools": {"flutter": {"status": "set", "version": None, "path": SECRET}}},
    {"env_keys": {f"GITHUB_TOKEN={SECRET}": "set"}},                    # a key that is an assignment
    {"dotenv": {"present": True, "keys": {"API_BASE": SECRET}}},
    {"unknowns": [{"kind": SECRET, "evidence": "x", "seen_at": 0}]},    # a kind outside UNKNOWN_KINDS
    {"checkout": SECRET},
])
def test_a_malformed_peer_report_row_is_dropped_alone(tmp_path, bad):
    entry = {"reported_at": _at(-60), "slots": {"launcher": {**_full_row(), **bad}, "backend": _full_row()}}
    workspace, local, summary = _pull_doc(tmp_path, _doc({}, {"mach_b": entry}))
    assert sorted(local["machines"]["mach_b"]["slots"]) == ["backend"]  # the sibling row is carried
    assert _refusals(summary) == [("mach_b", "invalid_machine_report", "launcher")]
    assert SECRET not in json.dumps(summary) and SECRET not in _local_bytes(workspace)


def test_a_malformed_peer_machine_entry_is_dropped_whole_and_its_id_digested(tmp_path):
    entries = {"mach_b": {"reported_at": _at(-60), "slots": {}, "extra": SECRET},
               f"mach={SECRET}": {"reported_at": _at(-60), "slots": {}},
               "mach_c": {"reported_at": "not-a-stamp", "slots": {}}}
    workspace, local, summary = _pull_doc(tmp_path, _doc({}, entries))
    assert local["machines"] == {}
    rows = _refusals(summary)
    assert [r for r in rows if not r[0].startswith("sha256:")] == [("mach_b", "invalid_machine_report"),
                                                                     ("mach_c", "invalid_machine_report")]
    assert len(rows) == 3 and SECRET not in json.dumps(summary) and SECRET not in _local_bytes(workspace)


def test_a_peer_unknowns_evidence_is_re_redacted_before_it_is_carried(tmp_path):
    row = {**_full_row(), "unknowns": [{"kind": "slot_probe_unknown", "evidence": f"api_key={SECRET}",
                                        "seen_at": NOW.timestamp() - 60}]}
    workspace, local, _ = _pull_doc(tmp_path, _doc({}, {"mach_b": {"reported_at": _at(-60),
                                                                    "slots": {"launcher": row}}}))
    [carried] = local["machines"]["mach_b"]["slots"]["launcher"]["unknowns"]
    assert carried["kind"] == "slot_probe_unknown" and "[redacted]" in carried["evidence"]
    assert SECRET not in _local_bytes(workspace)


def test_a_far_future_peer_stamp_is_refused_and_never_wedges_a_local_declare(tmp_path):
    late_unknown = {**_full_row(), "unknowns": [{"kind": "slot_probe_unknown", "evidence": "x",
                                                 "seen_at": NOW.timestamp() + 10 ** 9}]}
    remote = _doc({"launcher": _slot(FAR_FUTURE, revision=1, url="https://x/forged.git"),
                   "backend": {**_slot(_at(-60)), "recipe": {"revision": 0, "steps": [], "edited_at": FAR_FUTURE}}},
                  {"mach_b": {"reported_at": FAR_FUTURE, "slots": {}},
                   "mach_c": {"reported_at": _at(-60), "slots": {"launcher": late_unknown}}},
                  issued_at=FAR_FUTURE)
    workspace, local, summary = _pull_doc(tmp_path, remote, local=_doc({"launcher": _slot(OLD)}))
    assert local["issued_at"] == OLD and local["slots"]["launcher"]["repo"]["clone_url"] == "https://x/launcher.git"
    assert "backend" not in local["slots"] and "mach_b" not in local["machines"]
    assert local["machines"]["mach_c"]["slots"] == {}
    assert _refusals(summary) == [("issued_at", "stamp_in_future"), ("mach_b", "stamp_in_future"),
                                  ("mach_c", "stamp_in_future", "launcher"), ("stamp_in_future", "backend"),
                                  ("stamp_in_future", "launcher")]
    assert "2999" not in json.dumps(summary) and "2999" not in _local_bytes(workspace)
    # And the local clock still writes: a declare stamped now lands.
    assert _declare_now(workspace)["declared"] == ["launcher"]


def test_a_legitimate_newer_peer_edit_still_wins_including_within_the_skew(tmp_path):
    # A peer clock running four minutes fast is believed. A literal, never STAMP_SKEW_SECONDS: an
    # arm that reads the tolerance it pins moves with it and cannot go red.
    within = _at(240)
    remote = _doc({"launcher": _slot(within, url="https://x/theirs.git"), "hermes": _slot(_at(-60))},
                  {"mach_b": {"reported_at": within, "slots": {"launcher": _full_row()}}}, issued_at=within)
    local = _doc({"launcher": _slot(OLD)}, {"mach_b": {"reported_at": _at(-7200), "slots": {}}})
    _, held, summary = _pull_doc(tmp_path, remote, local=local)
    assert summary["refused"] == [] and held["issued_at"] == within
    assert held["slots"]["launcher"]["repo"]["clone_url"] == "https://x/theirs.git"
    assert sorted(held["slots"]) == ["hermes", "launcher"]
    assert held["machines"]["mach_b"]["slots"]["launcher"] == _full_row()


def test_a_document_already_holding_a_future_stamp_does_not_wedge_declare():
    workspace = WorkspaceStore().create(name="Poisoned").id
    write_document(workspace, {**_doc({"launcher": _slot(OLD)}, issued_at=FAR_FUTURE), "workspace_id": workspace})
    assert _declare_now(workspace)["declared"] == ["launcher"]
    # Positive control: a stamp older than an HONEST last declare is still refused stale_revision.
    with pytest.raises(SlotRefused) as stale:
        declare(workspace, [], issued_at=OLD, machine="mach_local")
    assert stale.value.reason == "stale_revision"
