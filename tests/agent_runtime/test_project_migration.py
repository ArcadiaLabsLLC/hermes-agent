"""Slots re-keyed to ``<project>/<slot>`` and the workspace-document migration (plan §3, §4, row RT-PROJECT-SLOT-REKEY)."""

from __future__ import annotations

import json

import pytest

from agent_runtime import address, paths, project_migration, serve_rpc
from agent_runtime.machine_roots import load_machine_roots, write_machine_roots
from agent_runtime.project_store import ProjectStore, load_project
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_env import set_slot_fill, slot_fill
from agent_runtime.workspace_slots import bind, bound_path, declare, load_document, scoped_roots, slot_census

STAMP = "2026-10-29T10:00:00+00:00"
LAUNCHER = {"name": "launcher", "repo": {"clone_url": "https://example.com/launcher.git"}}
BACKEND = {"name": "backend", "repo": {"clone_url": "https://example.com/backend.git"}}
BRAIN = {"name": "brain", "repo": {"local": True}}


@pytest.fixture
def namespace(tmp_path):
    """2 workspaces, 3 slots, 2 fills, 1 env fill, 1 worktree record."""

    a = WorkspaceStore().create(name="Alpha").id
    b = WorkspaceStore().create(name="Beta").id
    declare(a, [LAUNCHER, BACKEND], issued_at=STAMP, machine="mach_a")
    declare(b, [BRAIN], issued_at=STAMP, machine="mach_a")
    folders = {name: tmp_path / name for name in ("launcher", "brain")}
    for folder in folders.values():
        folder.mkdir()
    bind(a, "launcher", str(folders["launcher"]), issued_at=STAMP)
    bind(b, "brain", str(folders["brain"]), issued_at=STAMP)
    set_slot_fill(a, "launcher", env={"FLUTTER_ROOT": "/opt/flutter"}, issued_at=STAMP)
    record = paths.slot_worktrees_path(a, "launcher")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"schema": 1, "workspace_id": a, "slot": "launcher", "worktrees": {}}), encoding="utf-8")
    return {"a": a, "b": b, "folders": folders}


def test_the_migration_moves_every_slot_fill_and_record_with_equal_counts(namespace):
    a, b = namespace["a"], namespace["b"]
    receipt = project_migration.migrate_namespace()
    assert receipt["equal"] is True and [row["workspace_id"] for row in receipt["migrated"]] == sorted([a, b])
    by_ws = {row["workspace_id"]: row for row in receipt["migrated"]}
    assert by_ws[a]["before"] == by_ws[a]["after"] == {"slots": 2, "fills": 1}
    assert by_ws[b]["after"] == {"slots": 1, "fills": 1}
    assert by_ws[a]["env_fills"] == 1 and by_ws[a]["worktree_records"] == 1
    # The Project holds the slots VERBATIM and the workspace is connected to it.
    assert load_project(f"ws-{a}")["slots"] == load_document(a)["slots"]
    assert load_project(f"ws-{a}")["name"] == "Alpha repos"
    assert load_project(f"ws-{a}")["migrated_from"] == {"workspace_id": a, "workspace_name": "Alpha"}
    assert WorkspaceStore().get(a).project_ids == [f"ws-{a}"]
    # The fills are the Project's now, and a workspace-keyed reader still finds them.
    roots = scoped_roots()
    assert roots.project_root(f"ws-{a}", "launcher") == namespace["folders"]["launcher"]
    assert roots.workspace_root(a, "launcher") == namespace["folders"]["launcher"]  # kept for an older edition
    assert bound_path("launcher", workspace_id=a) == namespace["folders"]["launcher"]
    assert slot_fill(a, "launcher").env == {"FLUTTER_ROOT": "/opt/flutter"}
    assert paths.slot_worktrees_path(f"ws-{a}", "launcher").is_file()
    assert load_document(a)["migrated_to"] == f"ws-{a}"
    # The census counts each slot once, through its Project.
    census = slot_census()
    assert census.declared == 3
    assert sorted((s.project_id, s.slot) for s in census.bound) == sorted([(f"ws-{a}", "launcher"), (f"ws-{b}", "brain")])


def test_a_second_run_is_a_no_op(namespace):
    project_migration.migrate_namespace()
    before = sorted(p.name for p in paths.projects_dir().iterdir())
    again = project_migration.migrate_namespace()
    assert again["migrated"] == [] and again["already_migrated"] == 2
    assert sorted(p.name for p in paths.projects_dir().iterdir()) == before


def test_a_crash_after_step_one_completes_on_retry_without_a_duplicate(namespace, monkeypatch):
    a = namespace["a"]
    real = project_migration._copy_path_fills
    monkeypatch.setattr(project_migration, "_copy_path_fills", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        project_migration.migrate_namespace()
    assert paths.project_path(f"ws-{a}").is_file() and "migrated_to" not in load_document(a)
    monkeypatch.setattr(project_migration, "_copy_path_fills", real)
    receipt = project_migration.migrate_namespace()
    assert receipt["equal"] is True
    assert WorkspaceStore().get(a).project_ids == [f"ws-{a}"]
    assert sorted(p.stem for p in paths.projects_dir().glob("*.json")) == sorted([f"ws-{a}", f"ws-{namespace['b']}"])
    assert scoped_roots().project_root(f"ws-{a}", "launcher") == namespace["folders"]["launcher"]


def test_a_config_or_workspace_write_never_drops_a_project_fill(tmp_path):
    folder = tmp_path / "x"
    folder.mkdir()
    write_machine_roots({}, workspace_roots={}, project_roots={"p1": {"launcher": str(folder)}}, dry_run=False)
    write_machine_roots({"tool": str(folder)}, workspace_roots={"ws": {"brain": str(folder)}}, dry_run=False)
    roots = load_machine_roots(refresh=True)
    assert roots.project_root("p1", "launcher") == folder and roots.schema_version == 4
    # Positive control: an explicit empty map does clear it.
    write_machine_roots({}, workspace_roots={}, project_roots={}, dry_run=False)
    assert load_machine_roots(refresh=True).project_root("p1", "launcher") is None


def test_one_project_in_two_workspaces_is_one_fill(tmp_path):
    folder = tmp_path / "launcher"
    folder.mkdir()
    ProjectStore().declare("p1", [LAUNCHER], issued_at=STAMP, machine="mach_a")
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.project.slot.bind", "params": {
        "project_id": "p1", "slot": "launcher", "path": str(folder), "issued_at": STAMP}})
    assert reply["result"]["bound_here"] is True
    from agent_runtime.workspace_projects import set_project_connection

    for name in ("one", "two"):
        workspace = WorkspaceStore().create(name=name).id
        set_project_connection(workspace, "p1", connected=True, expected_revision=0)
        assert bound_path("launcher", workspace_id=workspace) == folder
    assert scoped_roots().project_roots == {"p1": {"launcher": str(folder)}}
    show = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.project.show",
                                     "params": {"project_id": "p1"}})["result"]
    assert show["here"]["launcher"]["bound_here"] is True


def test_the_project_address_prints_and_parses():
    shared = address.Address.of((address.Kind.PROJECT, "p1"), (address.Kind.REPO_SLOT, "launcher"))
    assert str(shared) == "project:p1/repo-slot:launcher" and address.parse(str(shared)) == shared
    join = address.parse("machine:m/namespace:base/slot-folder:p1/launcher")
    assert join.get(address.Kind.SLOT_FOLDER) == "p1/launcher"
    assert address.parse("realm:r/realm-workspace:w/repo-slot:launcher").get(address.Kind.REPO_SLOT) == "launcher"
    with pytest.raises(address.AddressError):
        address.parse("project:p1/slot-folder:p1/launcher")
