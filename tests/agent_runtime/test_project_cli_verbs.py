"""An agent manages a Project's repo slots from its terminal (row RT-PROJECT-SLOTS-AGENT-VERBS).

``hermes harness project …`` calls the body each ``runtime.project.*`` RPC method registers
(``serve_rpc.project.PROJECT_VERBS``), so a CLI answer and an RPC answer for the same request are the
same payload; ``project list`` maps every Project to the workspaces it is connected to; and a migrated
workspace's ``workspace slots …`` names the Project and the verb to use instead.
"""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from agent_runtime import project_migration, serve_rpc
from agent_runtime.machine_roots import load_machine_roots, machine_roots_cache_clear
from agent_runtime.project_store import ProjectStore, list_projects, load_project
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import declare

T0 = "2026-10-31T10:00:00+00:00"
T1 = "2026-10-31T11:00:00+00:00"


def _slot(name):
    return {"name": name, "repo": {"clone_url": f"https://example.com/{name}.git"}}


def _rpc(method, params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _printed(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _args(**kw):
    return Namespace(json=True, issued_at=None, **kw)


def test_the_cli_declare_creates_the_project_and_show_answers_what_the_rpc_answers(tmp_path, capsys):
    from hermes_cli.harness_parts import project_commands

    slots_file = tmp_path / "slots.json"
    slots_file.write_text(json.dumps([_slot("backend"), _slot("hermes"), _slot("launcher")]), encoding="utf-8")
    rc = project_commands._cmd_project_declare(_args(project_id="live-qa", slots_file=str(slots_file),
                                                     name="live-qa project"))
    assert rc == 0, capsys.readouterr()
    declared = _printed(capsys)
    assert declared["declared"] == ["backend", "hermes", "launcher"]
    assert load_project("live-qa")["name"] == "live-qa project"

    project_commands._cmd_project_show(_args(project_id="live-qa"))
    shown = _printed(capsys)
    rpc = _rpc("runtime.project.show", {"project_id": "live-qa"})["result"]
    assert {k: v for k, v in shown.items() if k in rpc} == rpc


def test_the_cli_binds_and_fills_a_project_slot_on_this_machine(tmp_path, capsys):
    from hermes_cli.harness_parts import project_commands

    machine_roots_cache_clear()
    ProjectStore().declare("p1", [_slot("launcher")], issued_at=T0, machine="m")
    checkout = tmp_path / "launcher"
    checkout.mkdir()
    assert project_commands._cmd_project_slot_bind(_args(project_id="p1", slot="launcher", path=str(checkout))) == 0
    capsys.readouterr()
    assert load_machine_roots(refresh=True).project_root("p1", "launcher") == checkout

    rc = project_commands._cmd_project_slot_env_set(_args(
        project_id="p1", slot="launcher", env=["FLUTTER_ROOT=/opt/flutter"], tool_path=[], path_prepend=None,
        dotenv=None, venv=None, env_keep=None))
    assert rc == 0
    assert _printed(capsys)["env_keys"] == ["FLUTTER_ROOT"]


def test_an_undeclared_slot_is_a_typed_refusal_not_a_traceback(capsys):
    from hermes_cli.harness_parts import project_commands

    ProjectStore().declare("p2", [_slot("launcher")], issued_at=T0, machine="m")
    rc = project_commands._cmd_project_slot_env_set(_args(
        project_id="p2", slot="nope", env=[], tool_path=[], path_prepend=None, dotenv=None, venv=None, env_keep=None))
    assert rc != 0
    assert "slot_not_declared" in capsys.readouterr().out


def test_project_list_names_each_projects_slots_and_workspaces(capsys):
    from hermes_cli.harness_parts import project_commands

    ProjectStore().declare("p-conn", [_slot("backend"), _slot("hermes")], issued_at=T0, machine="m")
    ProjectStore().declare("p-loose", [_slot("docs")], issued_at=T0, machine="m")
    workspace = WorkspaceStore().create(name="Default")
    set_project_connection(workspace.id, "p-conn", connected=True, expected_revision=0)
    set_project_connection(workspace.id, "p-ref", connected=True, expected_revision=1)

    rows = {row["project_id"]: row for row in list_projects()}
    assert rows["p-conn"]["slots"] == ["backend", "hermes"]
    assert rows["p-conn"]["workspaces"] == [{"workspace_id": workspace.id, "name": "Default", "realm_id": workspace.realm_id}]
    assert rows["p-loose"]["workspaces"] == [] and rows["p-loose"]["exists"] is True
    assert rows["p-ref"]["exists"] is False and rows["p-ref"]["slots"] == []

    assert project_commands._cmd_project_list(_args()) == 0
    assert {row["project_id"] for row in _printed(capsys)["projects"]} >= {"p-conn", "p-loose", "p-ref"}


def test_a_migrated_workspace_names_the_project_and_the_verb_to_use(capsys):
    from hermes_cli.harness_parts.workspace_slots_commands import _cmd_workspace_slots_show

    workspace = WorkspaceStore().create(name="QA Fixture").id
    declare(workspace, [_slot("launcher")], issued_at=T0, machine="m")
    project_migration.migrate_namespace()
    project = project_migration.migrated_project_id(workspace)

    rc = _cmd_workspace_slots_show(_args(workspace_id=workspace))
    out = capsys.readouterr().out
    assert rc != 0
    assert "slot_migrated" in out and f"hermes harness project show {project}" in out
    assert load_project(project)["name"] in out
    # The RPC detail stays the bare Project id the launcher parses.
    reply = _rpc("runtime.workspace.slots.show", {"workspace_id": workspace})
    assert reply["error"]["data"]["detail"] == project


@pytest.mark.parametrize(("argv", "handler"), [
    (["project", "list"], "_cmd_project_list"),
    (["project", "show", "p1"], "_cmd_project_show"),
    (["project", "declare", "p1", "--slots-file", "s.json"], "_cmd_project_declare"),
    (["project", "slot", "bind", "p1", "launcher", "/x"], "_cmd_project_slot_bind"),
    (["project", "slot", "clone", "p1", "launcher", "/x"], "_cmd_project_slot_clone"),
    (["project", "slot", "env-set", "p1", "launcher", "--env", "A=1"], "_cmd_project_slot_env_set"),
    (["project", "recipe", "show", "p1"], "_cmd_project_recipe_show"),
    (["project", "recipe", "set", "p1", "launcher", "--steps-file", "s.json", "--revision", "1"],
     "_cmd_project_recipe_set"),
    (["project", "recipe", "run-step", "p1", "launcher", "pub_get"], "_cmd_project_recipe_run_step"),
])
def test_every_project_verb_parses_to_its_handler(argv, handler):
    import argparse

    from hermes_cli.harness_parts.parser import build_parser

    root = argparse.ArgumentParser()
    build_parser(root.add_subparsers(dest="root_command"))
    parsed = root.parse_args(["harness", *argv])
    assert getattr(parsed.func, "__name__", None) == handler or handler in repr(parsed.func)


def test_every_cli_verb_but_list_reaches_a_registered_rpc_body():
    from agent_runtime.serve_rpc.project import PROJECT_METHOD_PARAMS, PROJECT_VERBS

    serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.project.show", "params": {}})
    assert set(PROJECT_VERBS) == {name for name in PROJECT_METHOD_PARAMS if name.startswith("runtime.project.")}
