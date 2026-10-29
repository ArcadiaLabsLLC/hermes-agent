"""Agents read their workspace's assigned Projects' slots (plan project-slots-and-shared-chats §3, row RT-PROJECT-SLOTS-FOR-AGENTS)."""

from __future__ import annotations

from hermes_time import now

from agent_runtime import paths, project_migration, serve_rpc
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_slots import load_slot_context, set_instance_slots
from agent_runtime.project_store import ProjectStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import bind_project, declare

T0 = "2026-10-29T10:00:00+00:00"
T1 = "2026-10-29T11:00:00+00:00"


def _slot(name):
    return {"name": name, "repo": {"clone_url": f"https://example.com/{name}.git"}, "context": {"files": ["CLAUDE.md"]}}


def _instance(instance_id, workspace_id):
    PersonaInstanceStore()._write(PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=instance_id, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace_id, updated_at=now()))
    return instance_id


def _connect(workspace, project, revision):
    return set_project_connection(workspace, project, connected=True, expected_revision=revision)


def _project(project_id, tmp_path, *names):
    ProjectStore().declare(project_id, [_slot(name) for name in names], issued_at=T0, machine="mach")
    for name in names:
        folder = tmp_path / project_id / name
        folder.mkdir(parents=True)
        (folder / "CLAUDE.md").write_text(f"{project_id} {name} rules", encoding="utf-8")
        bind_project(project_id, name, str(folder), issued_at=T0)


def test_an_instance_assigned_a_project_slot_loads_that_slots_files(tmp_path):
    _project("p1", tmp_path, "launcher", "backend")
    workspace = WorkspaceStore().create(name="Team").id
    _connect(workspace, "p1", 0)
    agent = _instance("personainst_a", workspace)
    set_instance_slots(agent, ["p1/launcher"], issued_at=T1)
    context = load_slot_context(PersonaInstanceStore().get(agent))
    assert [(s.slot, s.content) for s in context.sections] == [("p1/launcher", "p1 launcher rules")]
    assert context.primary_slot == "p1/launcher" and context.primary_path == str(tmp_path / "p1" / "launcher")
    assert [(b.slot, b.project_id) for b in context.bindings] == [("launcher", "p1")]
    show = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.persona.instance.slots.show",
                                     "params": {"persona_instance_id": agent}})["result"]
    assert show["projects"] == [{"project_id": "p1", "slots": ["p1/launcher"]}]
    assert show["slots"][0]["status"] == "bound" and show["slots"][0]["slot"] == "launcher"


def test_an_empty_assignment_loads_nothing_and_an_unheld_project_is_not_assignable(tmp_path):
    _project("p1", tmp_path, "launcher")
    workspace = WorkspaceStore().create(name="Team").id
    agent = _instance("personainst_a", workspace)
    assert load_slot_context(PersonaInstanceStore().get(agent)) is None
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.persona.instance.slots.set",
                                      "params": {"persona_instance_id": agent, "slots": ["p1/launcher"],
                                                 "issued_at": T1}})
    assert reply["error"]["data"]["reason"] == "slot_not_in_workspace"


def test_disconnecting_a_project_drops_only_its_slots_from_only_that_workspace(tmp_path):
    _project("p1", tmp_path, "launcher")
    _project("p2", tmp_path, "backend")
    team, other = WorkspaceStore().create(name="Team").id, WorkspaceStore().create(name="Other").id
    _connect(team, "p1", 0)
    _connect(team, "p2", 1)
    _connect(other, "p1", 0)
    here, there = _instance("personainst_here", team), _instance("personainst_there", other)
    set_instance_slots(here, ["p1/launcher", "p2/backend"], "p1/launcher", issued_at=T1)
    set_instance_slots(there, ["p1/launcher"], issued_at=T1)
    result = set_project_connection(team, "p1", connected=False, expected_revision=2)
    assert result["assignments_dropped"] == [here]
    assert PersonaInstanceStore().get(here).assigned_slots == ["p2/backend"]
    assert PersonaInstanceStore().get(here).primary_slot is None
    assert PersonaInstanceStore().get(there).assigned_slots == ["p1/launcher"]


def test_the_migration_rekeys_assignments_and_the_workspace_verbs_answer_slot_migrated(tmp_path):
    workspace = WorkspaceStore().create(name="Team").id
    declare(workspace, [_slot("launcher"), _slot("backend")], issued_at=T0, machine="mach")
    one, two = _instance("personainst_one", workspace), _instance("personainst_two", workspace)
    set_instance_slots(one, ["launcher", "backend"], "backend", issued_at=T0)
    set_instance_slots(two, ["launcher"], issued_at=T0)
    receipt = project_migration.migrate_namespace()
    assert receipt["migrated"][0]["instances"] == 2
    project = f"ws-{workspace}"
    assert PersonaInstanceStore().get(one).assigned_slots == [f"{project}/launcher", f"{project}/backend"]
    assert PersonaInstanceStore().get(one).primary_slot == f"{project}/backend"
    assert project_migration.migrate_namespace()["migrated"] == []
    assert PersonaInstanceStore().get(two).assigned_slots == [f"{project}/launcher"]
    for verb in ("runtime.workspace.slots.show", "runtime.workspace.slots.declare", "runtime.workspace.slot.bind"):
        reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": verb, "params": {
            "workspace_id": workspace, "slots": [], "slot": "launcher", "path": str(tmp_path), "issued_at": T1}})
        assert reply["error"]["data"] == {"reason": "slot_migrated", "detail": project, "project_id": project}, verb
