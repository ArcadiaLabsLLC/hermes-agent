"""The account's default realm (RT-ACCOUNT-DEFAULT-REALM): the pointer, its resolver, the two doors,
the snapshot field and where a no-realm create lands. Killing mutations are named per test."""
from types import SimpleNamespace

from agent_runtime import serve_rpc
from agent_runtime.default_realm import default_realm_id
from agent_runtime.default_scope import DEFAULT_REALM_ID, ensure_default_scope
from agent_runtime.store import RealmStore, WorkspaceStore
from agent_runtime.workspace_create import conversations_workspace


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "r", "method": method, "params": params})


def test_the_default_is_realm_default_until_set_then_the_chosen_realm_and_falls_back_when_it_is_archived():
    """Mutations: drop the pointer from the resolver's candidates -> the chosen realm is never the default,
    red; drop the live-realm filter -> an archived choice stays the default, red; drop the active-realm
    fallback -> a store without ``realm_default`` answers None, red."""
    realms = RealmStore()
    assert default_realm_id() is None
    lone = realms.create(name="Lone")
    realms.set_active(lone.id)
    assert default_realm_id() == lone.id
    ensure_default_scope(seed_active_pointers=False)
    assert default_realm_id() == DEFAULT_REALM_ID
    team = realms.create(name="Team")
    first = _rpc("runtime.realm.set_default", realm_id=team.id)["result"]
    assert (first["id"], first["default_realm_id"], first["changed"]) == (team.id, team.id, True)
    assert default_realm_id() == team.id
    assert realms.active_id() == lone.id
    again = _rpc("runtime.realm.set_default", realm_id=team.id)["result"]
    assert again["changed"] is False
    realms.archive(team.id)
    assert default_realm_id() == DEFAULT_REALM_ID


def test_set_default_refuses_an_unknown_an_archived_and_a_malformed_realm_and_writes_nothing():
    """Mutations: drop the archived refusal -> the archived realm is accepted (KeyError 'error'), red;
    widen the params check -> the extra key is accepted, red."""
    realms = RealmStore()
    gone = realms.create(name="Gone")
    realms.archive(gone.id)
    for params, reason, code in (({"realm_id": "realm_nowhere"}, "realm_not_found", 4001),
                                 ({"realm_id": gone.id}, "realm_archived", 4090),
                                 ({"realm_id": 7}, "invalid_request", -32602),
                                 ({}, "invalid_request", -32602),
                                 ({"realm_id": gone.id, "extra": 1}, "invalid_request", -32602)):
        error = _rpc("runtime.realm.set_default", **params)["error"]
        assert (error["data"], error["code"]) == ({"reason": reason}, code)
    assert realms.default_pointer_id() is None


def test_a_create_with_no_realm_lands_in_the_default_realm_on_both_doors_and_conversations_stays_realmless(monkeypatch):
    """Mutations: drop ``land_in_default`` at the method door / the argv door -> that door's workspace has
    ``realm_id`` None, red; make the landing unconditional in the plan -> Conversations joins a realm, red."""
    from hermes_cli.harness_parts import workspace_commands

    realms, workspaces = RealmStore(), WorkspaceStore()
    ensure_default_scope()
    team = realms.create(name="Team")
    _rpc("runtime.realm.set_default", realm_id=team.id)
    method = _rpc("runtime.workspace.create", name="Method", idempotency_key="default-1")["result"]
    assert method["realm_id"] == team.id and method["id"] in realms.get(team.id).workspace_ids
    rows = []
    monkeypatch.setattr(workspace_commands, "_print_stage42", lambda envelope, **_: rows.append(envelope))
    args = SimpleNamespace(name="Argv", realm=None, agent=[], blueprint=None, isolation=None, max_lanes=None,
                           from_workspace=None, copy=None, dry_run=False)
    assert workspace_commands._cmd_workspace_create(args) == 0
    argv = next(item for item in workspaces.list_all() if item.name == "Argv")
    assert argv.realm_id == team.id and argv.id in realms.get(team.id).workspace_ids
    explicit = _rpc("runtime.workspace.create", name="Explicit", idempotency_key="default-2",
                    realm_id=DEFAULT_REALM_ID)["result"]
    assert explicit["realm_id"] == DEFAULT_REALM_ID
    assert conversations_workspace().realm_id is None


def test_the_argv_verb_and_the_method_answer_one_row(monkeypatch):
    """Mutation: point the argv verb at a different realm row -> the two rows differ, red."""
    from hermes_cli.harness_parts import realm_commands

    team = RealmStore().create(name="Team")
    rows = []
    monkeypatch.setattr(realm_commands, "_print_stage42", lambda envelope, **_: rows.append(envelope))
    assert realm_commands._cmd_realm_default(SimpleNamespace(realm_id=team.id)) == 0
    method = _rpc("runtime.realm.set_default", realm_id=team.id)["result"]
    argv = rows[0]["data"] if "data" in rows[0] else rows[0]
    assert argv["id"] == method["id"] == team.id and argv["default_realm_id"] == method["default_realm_id"] == team.id
    assert (argv["changed"], method["changed"]) == (True, False)


def test_the_snapshot_carries_the_resolved_default_realm():
    """Mutation: emit the raw pointer instead of the resolved id -> None before a default is set, red."""
    from agent_runtime.snapshot import build_snapshot

    ensure_default_scope()
    assert build_snapshot()["default_realm_id"] == DEFAULT_REALM_ID
    team = RealmStore().create(name="Team")
    _rpc("runtime.realm.set_default", realm_id=team.id)
    assert build_snapshot()["default_realm_id"] == team.id
