"""The workspace and realm actions Eternia sent as a command line have typed calls on the running Hermes.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``, family "workspace and realm":
``runtime.workspace.rename`` / ``.archive`` / ``.delete`` and ``runtime.realm.create``, each a translation
shim over the one implementation its argv verb calls (``agent_runtime.workspace_manage``, ``RealmStore.create``).
Witnesses are the stores, never the reply alone. Killing mutations are named per test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.store import RealmStore, WorkspaceStore


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def test_rename_answers_the_renamed_row():
    """Mutation: pass the workspace id as the name -> the stored name, red."""
    workspace = WorkspaceStore().create(name="Roadmap")
    reply = _rpc("runtime.workspace.rename", workspace_id=workspace.id, name="  Launch plan ")
    assert reply["result"]["id"] == workspace.id
    assert reply["result"]["name"] == "Launch plan"
    assert WorkspaceStore().get(workspace.id).name == "Launch plan"


@pytest.mark.parametrize("params", [{"name": "x"}, {"workspace_id": "w"}, {"workspace_id": "w", "name": "  "},
                                    {"workspace_id": "w", "name": "x", "extra": 1}])
def test_rename_refuses_a_malformed_call_and_writes_nothing(params):
    """Mutation: drop ``rename_workspace``'s blank-name refusal -> the blank case renames, red."""
    workspace = WorkspaceStore().create(name="Roadmap")
    params = {**params, **({"workspace_id": workspace.id} if "workspace_id" in params else {})}
    reply = _rpc("runtime.workspace.rename", **params)
    assert reply["error"]["data"]["reason"] == "invalid_request"
    assert WorkspaceStore().get(workspace.id).name == "Roadmap"


def test_an_unknown_workspace_is_not_found_on_every_verb():
    for method, params in (("runtime.workspace.rename", {"name": "x"}), ("runtime.workspace.archive", {}),
                           ("runtime.workspace.delete", {})):
        reply = _rpc(method, workspace_id="ws_nobody", **params)
        assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND, method
        assert reply["error"]["data"]["reason"] == "workspace_not_found", method


def test_archive_puts_it_away_and_unarchive_brings_it_back():
    """Mutation: point ``runtime.workspace.archive`` at ``unarchive_workspace`` -> ``archived`` stays false, red."""
    workspace = WorkspaceStore().create(name="Roadmap")
    reply = _rpc("runtime.workspace.archive", workspace_id=workspace.id)
    assert reply["result"]["archived"] is True
    assert WorkspaceStore().get(workspace.id).archived is True
    assert _rpc("runtime.workspace.unarchive", workspace_id=workspace.id)["result"]["restored"] is True


def test_delete_removes_it_and_moves_the_active_pointer_to_the_realms_default():
    """Mutation: drop ``delete_workspace``'s reconcile -> the pointer is left cleared, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    realm = realms.create(name="Home")
    default = workspaces.create(name="Default", realm_id=realm.id)
    realm = realms.get(realm.id)
    realm.default_workspace_id = default.id
    realms.save(realm)
    doomed = workspaces.create(name="Scratch", realm_id=realm.id)
    realms.set_active(realm.id)
    workspaces.set_active(doomed.id)

    reply = _rpc("runtime.workspace.delete", workspace_id=doomed.id)
    assert "result" in reply, reply
    assert reply["result"]["deleted"] is True
    assert doomed.id not in {item.id for item in workspaces.list_all(include_archived=True)}
    assert workspaces.active_id() == default.id


def test_a_delete_guard_answers_its_own_reason():
    """Mutation: drop the ``WorkspaceDeleteBlocked`` arm in ``_manage`` -> the method raises, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    realm = realms.create(name="Team", server_id="srv_1")
    default = workspaces.create(name="Default", realm_id=realm.id)
    realm = realms.get(realm.id)
    realm.default_workspace_id = default.id
    realms.save(realm)

    reply = _rpc("runtime.workspace.delete", workspace_id=default.id)
    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"] == {"reason": "realm_default_workspace", "realm_id": realm.id}
    assert workspaces.get(default.id).id == default.id


def test_the_argv_delete_reaches_the_same_implementation(monkeypatch):
    """Mutation: put the argv handler's own ``store.delete`` back -> the spy is never asked, red."""
    from agent_runtime import workspace_manage
    from hermes_cli.harness_parts import workspace_commands

    workspace = WorkspaceStore().create(name="Scratch")
    asked = []
    real = workspace_manage.delete_workspace
    monkeypatch.setattr(workspace_manage, "delete_workspace", lambda wid: (asked.append(wid), real(wid))[1])
    monkeypatch.setattr(workspace_commands, "_print_stage42", lambda envelope, **_: None)
    args = SimpleNamespace(workspace_id=workspace.id, yes=True, dry_run=False, json=True)
    assert workspace_commands._cmd_workspace_delete(args) == 0
    assert asked == [workspace.id]


def test_realm_create_answers_a_local_realm():
    """Mutation: pass ``server_id=name`` -> the realm is server-bound, red."""
    before = {realm.id for realm in RealmStore().list_all(include_archived=True)}
    reply = _rpc("runtime.realm.create", name=" Side projects ")
    row = reply["result"]
    assert row["name"] == "Side projects"
    assert row["server_id"] is None
    created = {realm.id for realm in RealmStore().list_all(include_archived=True)} - before
    assert created == {row["id"]}


@pytest.mark.parametrize("params", [{}, {"name": ""}, {"name": 3}, {"name": "x", "server_id": "srv"}])
def test_realm_create_refuses_a_malformed_call_and_writes_nothing(params):
    before = {realm.id for realm in RealmStore().list_all(include_archived=True)}
    reply = _rpc("runtime.realm.create", **params)
    assert reply["error"]["data"]["reason"] == "invalid_request"
    assert {realm.id for realm in RealmStore().list_all(include_archived=True)} == before


def test_archive_and_delete_answer_only_this_installs_console():
    """Mutation: drop either name from ``LOCAL_CONSOLE_METHODS`` -> a console-paired device may remove a
    workspace the desktop operator is standing in, red."""
    from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS

    assert {"runtime.workspace.archive", "runtime.workspace.delete"} <= LOCAL_CONSOLE_METHODS


def test_the_four_methods_are_on_the_manifest():
    from agent_runtime.serve_rpc.registry import manifest

    names = set(manifest()["methods"])
    assert {"runtime.workspace.rename", "runtime.workspace.archive", "runtime.workspace.delete",
            "runtime.realm.create"} <= names
