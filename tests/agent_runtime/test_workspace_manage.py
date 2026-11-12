"""Managing an existing workspace (``agent_runtime.workspace_manage``): unarchive and the realm move. Killing
mutations are named per test."""
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


# ── runtime.workspace.move_realm (RT-WORKSPACE-MOVE-REALM) ──────────────────

def _move(**params):
    return _rpc("runtime.workspace.move_realm", **params)


def test_move_takes_a_workspace_out_of_one_realm_and_into_another():
    """Mutations: drop the back-reference write -> ``realm_id`` stays the source's, red; drop the source removal
    -> two realms list it, red; drop the target append -> the target never lists it, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    home, team = realms.create(name="Home"), realms.create(name="Team")
    item = wc_create("Roadmap", home.id)
    assert item.id in realms.get(home.id).workspace_ids
    result = _move(workspace_id=item.id, realm_id=team.id)["result"]
    assert (result["id"], result["realm_id"], result["moved"], result["from_realm_id"]) == (item.id, team.id, True, home.id)
    assert workspaces.get(item.id).realm_id == team.id
    assert item.id not in realms.get(home.id).workspace_ids and realms.get(team.id).workspace_ids == [item.id]
    again = _move(workspace_id=item.id, realm_id=team.id)["result"]
    assert (again["moved"], again["from_realm_id"]) == (False, None)
    loose = workspaces.create(name="Loose")
    homed = _move(workspace_id=loose.id, realm_id=team.id)["result"]
    assert (homed["realm_id"], homed["moved"], homed["from_realm_id"]) == (team.id, True, None)


def wc_create(name, realm_id):
    from agent_runtime.workspace_create import apply_workspace_create, plan_workspace_create

    return apply_workspace_create(plan_workspace_create(name, realm_id=realm_id))[0]


def test_moving_the_active_workspace_keeps_the_realm_and_falls_to_its_next_workspace():
    """Mutations: drop the reconcile -> the active workspace sits in the target while the active realm is the
    source (a straddle), red; reconcile to the TARGET realm instead of the active one -> the moved workspace
    stays active across realms, red. Moving a workspace INTO the active realm leaves the pointer alone."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    home, team = realms.create(name="Home"), realms.create(name="Team")
    stays, moves = wc_create("Stays", home.id), wc_create("Moves", home.id)
    realms.set_active(home.id)
    workspaces.set_active(moves.id)
    result = _move(workspace_id=moves.id, realm_id=team.id)["result"]
    assert result["active_workspace_id"] == stays.id == workspaces.active_id()
    assert realms.active_id() == home.id
    back = _move(workspace_id=moves.id, realm_id=home.id)["result"]
    assert back["active_workspace_id"] == stays.id == workspaces.active_id()


def test_move_refuses_a_default_workspace_a_server_bound_source_and_dead_ends_and_writes_nothing():
    """Mutations: drop the server-bound refusal -> the shared workspace leaves its realm (KeyError 'error'), red;
    drop the realm-default refusal -> the default workspace leaves, red; drop the archived-target refusal -> red."""
    from agent_runtime.default_scope import DEFAULT_REALM_ID, DEFAULT_WORKSPACE_ID, ensure_default_scope

    realms, workspaces = RealmStore(), WorkspaceStore()
    ensure_default_scope()
    team = realms.create(name="Team")
    shared_realm = realms.create(name="Shared", server_id="srv_1")
    shared = wc_create("Shared work", shared_realm.id)
    local_default = wc_create("Team default", team.id)
    stored = realms.get(team.id)
    stored.default_workspace_id = local_default.id
    realms.save(stored)
    closed = realms.create(name="Closed")
    realms.archive(closed.id)
    parked = wc_create("Parked", team.id)
    workspaces.archive(parked.id)
    free = wc_create("Free", team.id)
    for params, data, code in (
            ({"workspace_id": shared.id, "realm_id": team.id},
             {"reason": "workspace_realm_server_bound", "owner_realm_id": shared_realm.id}, 4090),
            ({"workspace_id": DEFAULT_WORKSPACE_ID, "realm_id": team.id},
             {"reason": "realm_default_workspace", "realm_id": DEFAULT_REALM_ID}, 4090),
            ({"workspace_id": local_default.id, "realm_id": DEFAULT_REALM_ID},
             {"reason": "realm_default_workspace", "realm_id": team.id}, 4090),
            ({"workspace_id": free.id, "realm_id": closed.id}, {"reason": "realm_archived", "realm_id": closed.id}, 4090),
            ({"workspace_id": parked.id, "realm_id": DEFAULT_REALM_ID}, {"reason": "workspace_archived"}, 4090),
            ({"workspace_id": free.id, "realm_id": "realm_nowhere"}, {"reason": "realm_not_found"}, 4001),
            ({"workspace_id": "ws_nowhere", "realm_id": team.id}, {"reason": "workspace_not_found"}, 4001),
            ({"workspace_id": free.id}, {"reason": "invalid_request"}, -32602),
            ({"workspace_id": free.id, "realm_id": 7}, {"reason": "invalid_request"}, -32602)):
        error = _move(**params)["error"]
        assert (error["data"], error["code"]) == (data, code), params
    assert workspaces.get(shared.id).realm_id == shared_realm.id and shared.id in realms.get(shared_realm.id).workspace_ids
    assert workspaces.get(DEFAULT_WORKSPACE_ID).realm_id == DEFAULT_REALM_ID
    assert workspaces.get(local_default.id).realm_id == team.id
    # INTO a server-bound realm is allowed, and lifts that realm's delete ledger for the id.
    ledgered = realms.get(shared_realm.id)
    ledgered.deleted_workspace_ids = [free.id]
    realms.save(ledgered)
    assert _move(workspace_id=free.id, realm_id=shared_realm.id)["result"]["realm_id"] == shared_realm.id
    assert free.id not in realms.get(shared_realm.id).deleted_workspace_ids


def test_the_move_argv_verb_reaches_the_same_implementation(monkeypatch):
    """Mutation: swap the argv verb's two positionals -> ``realm_not_found`` (exit non-zero), red."""
    from hermes_cli.harness_parts import workspace_commands

    realms = RealmStore()
    home, team = realms.create(name="Home"), realms.create(name="Team")
    item = wc_create("Argv", home.id)
    rows = []
    monkeypatch.setattr(workspace_commands, "_print_stage42", lambda envelope, **_: rows.append(envelope))
    assert workspace_commands._cmd_workspace_move_realm(SimpleNamespace(workspace_id=item.id, realm_id=team.id)) == 0
    assert (rows[0]["realm_id"], rows[0]["moved"], rows[0]["from_realm_id"]) == (team.id, True, home.id)


def test_move_never_homes_a_realmless_reserved_default_workspace_in_another_realm():
    """Mutation: drop the reserved-id refusal -> ``ws_default`` is homed in Team and the next boot's
    ``ensure_default_scope`` raises StoreCorrupt, red (KeyError 'error')."""
    from agent_runtime.default_scope import DEFAULT_REALM_ID, DEFAULT_WORKSPACE_ID

    team = RealmStore().create(name="Team")
    WorkspaceStore().create(name="Default", workspace_id=DEFAULT_WORKSPACE_ID)
    error = _move(workspace_id=DEFAULT_WORKSPACE_ID, realm_id=team.id)["error"]
    assert error["data"] == {"reason": "realm_default_workspace", "realm_id": DEFAULT_REALM_ID}
    assert WorkspaceStore().get(DEFAULT_WORKSPACE_ID).realm_id is None
