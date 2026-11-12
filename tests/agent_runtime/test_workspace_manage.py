"""Managing an existing workspace (``agent_runtime.workspace_manage``): unarchive. Killing mutations are named
per test."""
from types import SimpleNamespace

from agent_runtime import serve_rpc
from agent_runtime.store import RealmStore, WorkspaceStore


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "m", "method": method, "params": params})


# ── runtime.workspace.unarchive (RT-WORKSPACE-UNARCHIVE) ────────────────────

def test_unarchive_brings_an_archived_workspace_back_and_is_a_no_op_on_a_live_one():
    """Mutations: drop the ``archived = False`` write -> the workspace stays archived, red; report ``restored``
    true on a live workspace -> the second call's flag, red; move the active pointer -> red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    realm = realms.create(name="Home")
    kept = workspaces.create(name="Kept", realm_id=realm.id)
    workspaces.set_active(kept.id)
    gone = workspaces.create(name="Gone", realm_id=realm.id)
    workspaces.archive(gone.id)
    assert [item.id for item in workspaces.list_all()] == [kept.id]
    first = _rpc("runtime.workspace.unarchive", workspace_id=gone.id)["result"]
    assert (first["id"], first["archived"], first["restored"], first["realm_id"]) == (gone.id, False, True, realm.id)
    assert workspaces.get(gone.id).archived is False
    assert sorted(item.id for item in workspaces.list_all()) == sorted([kept.id, gone.id])
    assert workspaces.active_id() == kept.id
    again = _rpc("runtime.workspace.unarchive", workspace_id=gone.id)["result"]
    assert (again["archived"], again["restored"]) == (False, False)


def test_unarchive_lifts_the_realms_delete_ledger_and_heals_the_membership():
    """Mutation: drop the lift -> the id stays on ``deleted_workspace_ids`` (the next pull archives it again), red;
    drop the membership heal -> the realm never lists it, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    realm = realms.create(name="Shared")
    item = workspaces.create(name="Tombstoned", realm_id=realm.id)
    workspaces.archive(item.id)
    stored = realms.get(realm.id)
    stored.deleted_workspace_ids = [item.id]
    stored.workspace_ids = []
    realms.save(stored)
    assert _rpc("runtime.workspace.unarchive", workspace_id=item.id)["result"]["restored"] is True
    after = realms.get(realm.id)
    assert item.id not in after.deleted_workspace_ids and item.id in after.workspace_ids
    assert [lift.workspace_id for lift in after.workspace_lifts] == [item.id]


def test_unarchive_refuses_an_unknown_workspace_a_malformed_request_and_an_archived_realm():
    """Mutation: drop the archived-realm refusal -> the workspace comes back inside a realm nothing lists
    (KeyError 'error'), red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    realm = realms.create(name="Closed")
    item = workspaces.create(name="Inside", realm_id=realm.id)
    workspaces.archive(item.id)
    realms.archive(realm.id)
    for params, data, code in (({"workspace_id": "ws_nowhere"}, {"reason": "workspace_not_found"}, 4001),
                               ({"workspace_id": 7}, {"reason": "invalid_request"}, -32602),
                               ({}, {"reason": "invalid_request"}, -32602),
                               ({"workspace_id": item.id, "yes": True}, {"reason": "invalid_request"}, -32602),
                               ({"workspace_id": item.id}, {"reason": "realm_archived", "realm_id": realm.id}, 4090)):
        error = _rpc("runtime.workspace.unarchive", **params)["error"]
        assert (error["data"], error["code"]) == (data, code)
    assert workspaces.get(item.id).archived is True


def test_the_unarchive_argv_verb_reaches_the_same_implementation(monkeypatch):
    """Mutation: make the argv verb's dry run write -> the workspace is restored by ``--dry-run``, red."""
    from hermes_cli.harness_parts import workspace_commands

    workspaces = WorkspaceStore()
    item = workspaces.create(name="Argv")
    workspaces.archive(item.id)
    rows = []
    monkeypatch.setattr(workspace_commands, "_print_stage42", lambda envelope, **_: rows.append(envelope))
    assert workspace_commands._cmd_workspace_unarchive(SimpleNamespace(workspace_id=item.id, dry_run=True)) == 0
    assert workspaces.get(item.id).archived is True
    assert workspace_commands._cmd_workspace_unarchive(SimpleNamespace(workspace_id=item.id, dry_run=False)) == 0
    assert workspaces.get(item.id).archived is False
    assert [row["restored"] for row in rows] == [False, True]
