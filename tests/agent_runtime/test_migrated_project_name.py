"""A migrated Project is named for what it holds and remembers its workspace (row RT-MIGRATED-PROJECT-NAME).

The slot migration's Project read "<workspace> slots" in the launcher's Connect menu with no hint of where
it came from. It is "<workspace> repos" now and carries ``migrated_from: {workspace_id, workspace_name}``;
one already migrated under the old name is renamed on the next boot's migration pass (a name someone
changed stays theirs), and realm sync carries ``migrated_from`` through both the merge and the peer read.
"""

from __future__ import annotations

from agent_runtime import project_migration
from agent_runtime.project_store import ProjectStore, list_projects, load_project, show, write_project
from agent_runtime.project_sync import held_project, merge_projects
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import declare

STAMP = "2026-10-31T10:00:00+00:00"
LAUNCHER = {"name": "launcher", "repo": {"clone_url": "https://example.com/launcher.git"}}


def _migrated(name="QA Fixture"):
    workspace = WorkspaceStore().create(name=name).id
    declare(workspace, [LAUNCHER], issued_at=STAMP, machine="m")
    project_migration.migrate_namespace()
    return workspace, project_migration.migrated_project_id(workspace)


def _as_legacy(project, *, name):
    record = load_project(project)
    record.pop("migrated_from", None)
    record["name"] = name
    write_project(project, record)


def test_a_new_migration_names_the_project_for_its_repos_and_records_the_workspace():
    workspace, project = _migrated()
    record = load_project(project)
    assert record["name"] == "QA Fixture repos"
    assert record["migrated_from"] == {"workspace_id": workspace, "workspace_name": "QA Fixture"}
    assert show(project)["document"]["migrated_from"]["workspace_name"] == "QA Fixture"
    listed, = [row for row in list_projects() if row["project_id"] == project]
    assert listed["migrated_from"] == record["migrated_from"]


def test_a_project_migrated_under_the_old_name_is_renamed_once():
    workspace, project = _migrated()
    _as_legacy(project, name="QA Fixture slots")

    receipt = project_migration.migrate_namespace()
    assert receipt["renamed"] == 1
    record = load_project(project)
    assert record["name"] == "QA Fixture repos"
    assert record["migrated_from"] == {"workspace_id": workspace, "workspace_name": "QA Fixture"}
    assert project_migration.migrate_namespace()["renamed"] == 0


def test_a_name_someone_chose_stays_and_only_the_origin_is_added():
    workspace, project = _migrated()
    _as_legacy(project, name="Team repos")

    assert project_migration.migrate_namespace()["renamed"] == 1
    record = load_project(project)
    assert record["name"] == "Team repos"
    assert record["migrated_from"]["workspace_id"] == workspace


def test_a_project_the_migration_did_not_make_is_never_renamed():
    ProjectStore().declare("hand-made", [LAUNCHER], issued_at=STAMP, machine="m", name="Alpha slots")
    workspace = WorkspaceStore().create(name="Alpha").id
    declare(workspace, [LAUNCHER], issued_at=STAMP, machine="m")
    project_migration.migrate_namespace()
    assert load_project("hand-made")["name"] == "Alpha slots"
    assert "migrated_from" not in load_project("hand-made")


def test_sync_keeps_the_origin_through_the_merge_and_the_peer_read():
    _, project = _migrated()
    local = load_project(project)
    remote = {key: value for key, value in local.items() if key != "migrated_from"}
    assert merge_projects(remote, local)["migrated_from"] == local["migrated_from"]
    assert merge_projects(local, remote)["migrated_from"] == local["migrated_from"]

    held, refused = held_project(local, now=4_000_000_000)
    assert held["migrated_from"] == local["migrated_from"] and refused == []
    bad = {**local, "migrated_from": {"workspace_id": "../escape", "workspace_name": "x"}}
    held, refused = held_project(bad, now=4_000_000_000)
    assert "migrated_from" not in held
    assert {"field": "migrated_from", "reason": "invalid_migrated_from"} in refused
