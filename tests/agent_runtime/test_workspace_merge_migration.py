"""Every Project folds into its home workspace on the first boot (row RT-WS-ABSORB-MIGRATION).

Plan ``EterniaLauncher/docs/mission_control/planned/WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md`` §4 step 1.
The fixture is a Project-edition namespace written as raw files: a ``ws-`` Project with its frozen
origin document, one Project in two workspaces (with a slot-name clash), one Project in none, and a
reference with no record.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from hermes_time import now

from agent_runtime import paths, project_migration
from agent_runtime.machine_roots import load_machine_roots, write_machine_roots
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_env import _read as read_env_fills, slot_fill
from agent_runtime.workspace_slot_env import _write as write_env_fills
from agent_runtime.workspace_slots import live_slots, load_document

T0 = "2026-10-29T10:00:00+00:00"
T1 = "2026-10-30T10:00:00+00:00"


def _slot(url, issued_at=T1):
    return {"repo": {"clone_url": url, "default_branch": "main"}, "toolchain": {"kind": "", "tools": [], "env_keys": [],
                                                                               "dotenv": None},
            "context": {"role": "", "files": None}, "recipe": {"revision": 1, "steps": []},
            "declared_at": issued_at, "declared_by_machine": "mach_a", "issued_at": issued_at, "removed_at": None}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _project(project_id, name, slots, **extra):
    _write(paths.store_root() / "projects" / f"{project_id}.json",
           {"schema_version": 1, "project_id": project_id, "name": name, "issued_at": T1, "slots": slots,
            "categories": {}, "machines": {}, **extra})


def _list(workspace_id, *project_ids):
    path = paths.workspace_path(workspace_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**raw, "project_ids": list(project_ids), "project_assignment_revision": 2}),
                    encoding="utf-8")


def _instance(instance_id, workspace_id, slots, primary=None):
    PersonaInstanceStore()._write(PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=instance_id, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace_id,
        updated_at=now(), assigned_slots=list(slots), primary_slot=primary,
        slot_context_files={key: ["CLAUDE.md"] for key in slots}))


@pytest.fixture
def edition(tmp_path):
    a = WorkspaceStore().create(name="Alpha").id
    b = WorkspaceStore().create(name="Beta").id
    assert a < b
    own, shared = f"ws-{a}", "p_shared"
    # A's document, frozen by the Project edition's slot migration; its Project is newer.
    _write(paths.workspace_slots_path(a), {"schema_version": 1, "workspace_id": a, "issued_at": T0,
                                           "slots": {"launcher": _slot("https://example.com/old.git", T0)},
                                           "machines": {}, "migrated_to": own})
    _write(paths.workspace_slots_path(b), {"schema_version": 1, "workspace_id": b, "issued_at": T0,
                                           "slots": {"brain": _slot("https://example.com/brain.git", T0)},
                                           "machines": {}})
    _project(own, "Alpha repos", {"launcher": _slot("https://example.com/launcher.git"),
                                  "backend": _slot("https://example.com/backend.git")},
             categories={"chats": {"slot": "launcher", "subpath": ".eternia/chats", "shared": True, "issued_at": T1,
                                   "revision": 1}},
             machines={"mach_a": {"reported_at": T1, "slots": {"launcher": {"status": "ready", "bound": True}}}})
    _project(shared, "Shared Tools", {"launcher": _slot("https://example.com/tools-launcher.git"),
                                      "tools": _slot("https://example.com/tools.git")},
             categories={"documents": {"slot": "launcher", "subpath": "docs", "shared": True, "issued_at": T1,
                                       "revision": 2, "context_files": ["a.md"]},
                         "chats": {"slot": "tools", "subpath": ".eternia/chats", "shared": False, "issued_at": T1,
                                   "revision": 1},
                         "guidance": {"slot": None, "subpath": None, "shared": True, "issued_at": T1, "revision": 1}},
             guidance={"description": "d", "instructions": "i", "issued_at": T1, "revision": 1},
             machines={"mach_a": {"reported_at": T1, "slots": {"launcher": {"status": "ready", "bound": True}}}})
    _project("p_loose", "Loose Notes", {"notes": _slot("https://example.com/notes.git")})
    _list(a, own, shared)
    _list(b, shared, "p_ghost")
    folders = {name: tmp_path / name for name in ("own", "shared_launcher", "tools")}
    for folder in folders.values():
        folder.mkdir()
    current = load_machine_roots(refresh=True)
    write_machine_roots(dict(current.roots), workspace_roots={a: {"launcher": str(tmp_path)}},
                        project_roots={own: {"launcher": str(folders["own"])},
                                       shared: {"launcher": str(folders["shared_launcher"]),
                                                "tools": str(folders["tools"])},
                                       "p_ghost": {"x": str(tmp_path)}}, dry_run=False)
    env = read_env_fills()
    env["projects"] = {shared: {"tools": {"env": {"TOOLS_HOME": "/opt/tools"}, "tool_paths": {}, "path_prepend": [],
                                          "dotenv": None, "venv": None, "bound_at": T1}}}
    write_env_fills(env)
    _write(paths.slot_worktrees_path(shared, "launcher"), {"schema": 1, "slot": "launcher", "worktrees": {}})
    _write(paths.store_root() / "project_chats" / f"{own}.db", {"stand-in": "sqlite"})
    _write(paths.store_root() / "project_chat_fold" / f"{own}.json", {"project_id": own, "files": {"s/a.jsonl": 9}})
    _write(paths.store_root() / "project_chat_exports" / own / "chat_1.json",
           {"project_id": own, "session_id": "chat_1", "shared": True, "last_id": 3})
    _instance("personainst_a", a, [f"{own}/launcher", f"{shared}/launcher"], primary=f"{shared}/launcher")
    _instance("personainst_b", b, [f"{shared}/tools", "brain"])
    _write(paths.work_runs_dir(a) / "run_1.json", {"request_id": "run_1", "ref": {"slot": "launcher", "note": "q.md",
                                                                                 "id": "ROW-1", "project_id": shared}})
    _write(paths.schedules_dir() / "every_hour.json",
           {"key": "every_hour", "action": {"rows": [["launcher", "q.md", "ROW-2", shared], ["brain", "q.md", "ROW-3"]]}})
    worktree = paths.work_worktrees_dir(a) / f"{paths.safe_path_token(shared + '/launcher')}-0123456789ab"
    worktree.mkdir(parents=True)
    chats_writer = paths.work_worktrees_dir(f"project_{shared}") / "tools-0123456789ab"
    chats_writer.mkdir(parents=True)
    return {"a": a, "b": b, "own": own, "shared": shared, "folders": folders, "worktree": worktree,
            "chats_writer": chats_writer}


def test_every_project_lands_in_its_home_and_every_keyed_store_follows(edition):
    a, b, own, shared, folders = (edition[k] for k in ("a", "b", "own", "shared", "folders"))
    receipt = project_migration.migrate_namespace()
    homes = {row["project_id"]: (row["workspace_id"], row["created"]) for row in receipt["merged"]}
    assert homes[own] == (a, False) and homes[shared] == (a, False) and homes["p_ghost"] == (b, False)
    created, made = homes["p_loose"]
    assert made is True and WorkspaceStore().get(created).name == "Loose Notes"
    assert sorted(live_slots(load_document(created))) == ["notes"]
    assert {row["project_id"]: row["renamed"] for row in receipt["merged"]}[shared] == {"launcher": "shared_tools_launcher"}

    document = load_document(a)
    assert "migrated_to" not in document
    assert sorted(live_slots(document)) == ["backend", "launcher", "shared_tools_launcher", "tools"]
    assert document["slots"]["launcher"]["repo"]["clone_url"] == "https://example.com/launcher.git"  # the newer
    assert document["slots"]["shared_tools_launcher"]["repo"]["clone_url"] == "https://example.com/tools-launcher.git"
    # A category the workspace already holds keeps its own; a new one moves with the renamed slot.
    assert document["categories"]["chats"]["slot"] == "launcher" and document["categories"]["chats"]["shared"] is True
    assert document["categories"]["documents"]["slot"] == "shared_tools_launcher"
    assert document["guidance"]["instructions"] == "i"
    assert sorted(document["machines"]["mach_a"]["slots"]) == ["launcher", "shared_tools_launcher"]
    assert sorted(live_slots(load_document(b))) == ["brain"]

    roots = load_machine_roots(refresh=True)
    assert roots.project_roots == {}
    assert roots.workspace_roots[a] == {"launcher": str(folders["own"]), "shared_tools_launcher":
                                        str(folders["shared_launcher"]), "tools": str(folders["tools"])}
    assert slot_fill(a, "tools").env == {"TOOLS_HOME": "/opt/tools"} and "projects" not in read_env_fills()
    assert paths.slot_worktrees_path(a, "shared_tools_launcher").is_file()
    assert not (paths.store_root() / "slot_worktrees" / shared).exists()
    assert paths.workspace_chat_store_path(a).is_file()
    assert json.loads(paths.workspace_chat_fold_path(a).read_text(encoding="utf-8")) == {
        "workspace_id": a, "files": {"s/a.jsonl": 9}}
    cursor = json.loads(paths.workspace_chat_export_path(a, "chat_1").read_text(encoding="utf-8"))
    assert cursor["workspace_id"] == a and "project_id" not in cursor and cursor["last_id"] == 3

    first, second = PersonaInstanceStore().get("personainst_a"), PersonaInstanceStore().get("personainst_b")
    assert first.assigned_slots == ["launcher", "shared_tools_launcher"]
    assert first.primary_slot == "shared_tools_launcher"
    assert sorted(first.slot_context_files) == ["launcher", "shared_tools_launcher"]
    assert second.assigned_slots == ["brain"]  # a Project slot outside its home goes
    run = json.loads((paths.work_runs_dir(a) / "run_1.json").read_text(encoding="utf-8"))
    assert run["ref"] == {"slot": "shared_tools_launcher", "note": "q.md", "id": "ROW-1"}
    schedule = json.loads((paths.schedules_dir() / "every_hour.json").read_text(encoding="utf-8"))
    assert schedule["action"]["rows"] == [["shared_tools_launcher", "q.md", "ROW-2"], ["brain", "q.md", "ROW-3"]]
    assert not edition["worktree"].exists() and not paths.work_workspace_dir(f"project_{shared}").exists()

    for gone in ("projects", "project_chats", "project_chat_fold", "project_chat_exports"):
        assert not (paths.store_root() / gone).exists(), gone
    for workspace_id in (a, b, created):
        raw = json.loads(paths.workspace_path(workspace_id).read_text(encoding="utf-8"))
        assert "project_ids" not in raw and "project_assignment_revision" not in raw


def _tree_digest():
    digest = hashlib.sha256()
    for path in sorted(p for p in paths.store_root().rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(paths.store_root())).encode() + path.read_bytes())
    return digest.hexdigest()


def test_a_second_boot_is_a_no_op(edition):
    project_migration.migrate_namespace()
    before = _tree_digest()
    assert project_migration.migrate_namespace() == {"merged": [], "dropped": [], "stamps_removed": 0}
    assert _tree_digest() == before


def test_a_namespace_that_never_held_a_project_is_untouched():
    workspace = WorkspaceStore().create(name="Plain").id
    _write(paths.workspace_slots_path(workspace), {"schema_version": 1, "workspace_id": workspace, "issued_at": T0,
                                                   "slots": {"brain": _slot("https://example.com/b.git", T0)},
                                                   "machines": {}})
    before = _tree_digest()
    assert project_migration.migrate_namespace() == {"merged": [], "dropped": [], "stamps_removed": 0}
    assert _tree_digest() == before


def test_a_reference_with_no_record_and_no_workspace_is_dropped_with_its_fills(tmp_path):
    current = load_machine_roots(refresh=True)
    write_machine_roots(dict(current.roots), workspace_roots={}, project_roots={"p_orphan": {"x": str(tmp_path)}},
                        dry_run=False)
    workspace = WorkspaceStore().create(name="Holder").id
    _instance("personainst_c", workspace, ["p_orphan/x"])
    _write(paths.store_root() / "projects" / "p_orphan.json", {"not": "a record"})
    receipt = project_migration.migrate_namespace()
    assert receipt["dropped"] == ["p_orphan"] and receipt["merged"] == []
    assert load_machine_roots(refresh=True).project_roots == {}
    assert PersonaInstanceStore().get("personainst_c").assigned_slots == []
    assert not (paths.store_root() / "projects").exists()
