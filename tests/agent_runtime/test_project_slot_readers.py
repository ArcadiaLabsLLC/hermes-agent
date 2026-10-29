"""After the migration, the slot READERS read the workspace's Projects (row RT-PROJECT-SLOT-READERS-REKEY).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §3–§4: a
migrated workspace document is frozen at ``migrated_to``; every edit lands through
``runtime.project.*``, so a reader that still opened the document would answer the pre-migration
declaration. Each test edits the Project AFTER the migration and asserts the reader sees the edit.
"""

from __future__ import annotations

import subprocess
import types
from argparse import Namespace

import pytest

from agent_runtime import project_migration, serve_rpc
from agent_runtime.batch.dispatcher import _slot_gates, _slot_roles
from agent_runtime.machine_roots import load_machine_roots, machine_roots_cache_clear
from agent_runtime.project_store import ProjectStore, load_project
from agent_runtime.store import WorkspaceStore
from agent_runtime.work_store.default_brain import _declared_brain
from agent_runtime.workspace_slot_env import set_slot_fill
from agent_runtime.workspace_slot_overlay import SlotBinding, overlay_for
from agent_runtime.workspace_slot_setup import clone_slot, run_step, settle_runs
from agent_runtime.workspace_slots import declare, load_document, resolve_slot

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
ISSUED = "2026-10-29T10:00:00+00:00"
EDITED = "2026-10-29T11:00:00+00:00"
LATER = "2026-10-29T12:00:00+00:00"


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _decl(name, role, gate, url=CLONE_URL):
    return {"name": name, "repo": {"clone_url": url, "default_branch": "main"},
            "toolchain": {"tools": [{"name": "flutter"}], "env_keys": [{"key": "FLUTTER_ROOT", "required": True}]},
            "context": {"role": role, "gate": gate}}


class _Registry:
    def __init__(self):
        self.spawned, self.sessions = [], {}

    def spawn_local(self, command, **kwargs):
        sid = f"proc_{len(self.spawned) + 1:04d}"
        self.spawned.append((command, kwargs))
        self.sessions[sid] = types.SimpleNamespace(id=sid, exited=False, exit_code=None, output_buffer="",
                                                   completion_reason="exited")
        return self.sessions[sid]

    def get(self, sid):
        return self.sessions.get(sid)

    def finish(self, sid, code):
        self.sessions[sid].exited, self.sessions[sid].exit_code = True, code


@pytest.fixture
def migrated():
    """A workspace declaring ``launcher`` + ``brain``, migrated, then edited through the Project."""

    machine_roots_cache_clear()
    workspace = WorkspaceStore().create(name="Alpha").id
    declare(workspace, [_decl("launcher", "app", ["old gate"]), _decl("brain", "brain", [])],
            issued_at=ISSUED, machine="m")
    project_migration.migrate_namespace()
    project = f"ws-{workspace}"
    ProjectStore().declare(project, [_decl("launcher", "edited-role", ["edited gate"]),
                                     _decl("brain", "brain", [], url="https://example.com/edited-brain.git")],
                           issued_at=EDITED, machine="m")
    assert load_document(workspace)["migrated_to"] == project
    return workspace, project


def test_resolve_slot_reads_the_project_and_never_the_frozen_document(migrated):
    workspace, project = migrated
    resolved = resolve_slot(workspace, "launcher")
    assert resolved.project_id == project and resolved.declaration["context"]["role"] == "edited-role"
    assert resolve_slot(workspace, f"{project}/launcher").declaration["context"]["role"] == "edited-role"
    # Positive control: the frozen document still says the old thing, so the read above is the Project's.
    assert load_document(workspace)["slots"]["launcher"]["context"]["role"] == "app"


def test_the_dispatcher_reads_roles_and_gates_from_the_project(migrated):
    workspace, _ = migrated
    assert _slot_roles(workspace)["launcher"] == "edited-role"
    gates = _slot_gates(workspace)
    assert gates.get("launcher") in (None, ("edited gate",))  # a board exists only when bound here


def test_the_default_brain_reads_the_projects_brain_declaration(migrated):
    workspace, _ = migrated
    assert _declared_brain(workspace)["repo"]["clone_url"] == "https://example.com/edited-brain.git"


def test_the_overlay_reads_the_projects_fill_for_a_workspace_binding(migrated, tmp_path):
    workspace, project = migrated
    set_slot_fill(None, "launcher", env={"FLUTTER_ROOT": "/project/flutter"}, issued_at=LATER, project_id=project)
    overlay = overlay_for(SlotBinding(workspace, "launcher", str(tmp_path)))
    assert overlay.apply({})["FLUTTER_ROOT"] == "/project/flutter"


def test_the_workspace_recipe_verbs_read_and_edit_the_project(migrated):
    workspace, project = migrated
    shown = call("runtime.workspace.recipe.show", {"workspace_id": workspace})["result"]["slots"]
    assert set(shown) == {f"{project}/launcher", f"{project}/brain"}
    base = shown[f"{project}/launcher"]["revision"]
    reply = call("runtime.workspace.recipe.set", {"workspace_id": workspace, "slot": "launcher", "revision": base,
                                                   "steps": [{"id": "pub_get", "kind": "command", "argv": ["flutter", "pub", "get"]}],
                                                   "issued_at": LATER})
    assert "result" in reply, reply
    assert reply["result"]["project_id"] == project and reply["result"]["revision"] == base + 1
    assert load_project(project)["slots"]["launcher"]["recipe"]["steps"]
    assert not (load_document(workspace)["slots"]["launcher"].get("recipe") or {}).get("steps")  # frozen doc untouched
    twin = call("runtime.project.recipe.show", {"project_id": project})["result"]["slots"]
    assert twin["launcher"]["revision"] == base + 1


def test_the_project_clone_twin_binds_the_projects_fill(migrated, tmp_path):
    _, project = migrated
    registry = _Registry()
    dest = tmp_path / "clone" / "launcher"
    run = clone_slot(None, "launcher", str(dest), issued_at=LATER, registry=registry, watch=False,
                     project_id=project)["run"]
    assert run["project_id"] == project
    dest.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", CLONE_URL], check=True)
    registry.finish(run["run_id"], 0)
    settled, = settle_runs(None, registry, project_id=project)
    assert settled["status"] == "succeeded"
    assert load_machine_roots(refresh=True).project_root(project, "launcher") == dest
    # The twin's run step resolves the same Project's checkout.
    ProjectStore().set_recipe(project, "launcher", [{"id": "pub_get", "kind": "command", "argv": ["flutter", "pub", "get"]}],
                              base_revision=load_project(project)["slots"]["launcher"]["recipe"]["revision"],
                              issued_at="2026-10-29T13:00:00+00:00", machine="m")
    stepped = run_step(None, "launcher", "pub_get", issued_at="2026-10-29T14:00:00+00:00", registry=registry,
                       watch=False, project_id=project)
    assert stepped["run"]["project_id"] == project and registry.spawned[-1][1]["cwd"] == str(dest)


def test_the_cli_and_rpc_slot_verbs_answer_slot_migrated(migrated, capsys):
    from hermes_cli.harness_parts.workspace_slots_commands import _cmd_workspace_slots_env_set

    workspace, project = migrated
    reply = call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher", "env": {},
                                                     "issued_at": LATER})
    assert reply["error"]["data"]["reason"] == "slot_migrated"
    _cmd_workspace_slots_env_set(Namespace(workspace_id=workspace, slot="launcher", env=[], tool_path=[],
                                           path_prepend=None, dotenv=None, venv=None, env_keep=None,
                                           issued_at=LATER, json=True))
    assert "slot_migrated" in capsys.readouterr().out
