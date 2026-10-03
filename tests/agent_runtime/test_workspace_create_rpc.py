from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_runtime import serve_rpc
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_create import create_workspace, WorkspaceCreationRefused


def test_concurrent_replay_uses_existing_store_and_never_changes_selection():
    store = WorkspaceStore()
    original = store.create(name="Operator workspace")
    store.set_active(original.id)
    def create(_):
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "create", "method": "runtime.workspace.create",
          "params": {"name": "Discussion workspace", "idempotency_key": "one-gesture"}})["result"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(create, range(4)))
    assert rows == [rows[0]] * 4
    assert store.get(rows[0]["id"]).name == "Discussion workspace"
    assert len(store.list_all()) == 2
    assert store.active_id() == original.id
    with pytest.raises(WorkspaceCreationRefused, match="idempotency_conflict"):
        create_workspace("Another name", "one-gesture")


def test_deleted_workspace_is_never_recreated_by_a_late_retry():
    store = WorkspaceStore()
    created, _row, _warnings = create_workspace("Temporary", "old-request")
    store.delete(created.id)
    with pytest.raises(WorkspaceCreationRefused, match="workspace_creation_unresolved"):
        create_workspace("Temporary", "old-request")
    assert store.list_all() == []


def test_interrupted_creation_does_not_guess_whether_creation_was_admitted(monkeypatch):
    def interrupted(*args, **kwargs):
        raise OSError("Interrupted before workspace write")
    with monkeypatch.context() as patch:
        patch.setattr(WorkspaceStore, "create", interrupted)
        with pytest.raises(OSError):
            create_workspace("Preserve uncertainty", "interrupted")
    with pytest.raises(WorkspaceCreationRefused, match="workspace_creation_unresolved"):
        create_workspace("Preserve uncertainty", "interrupted")
    assert not WorkspaceStore().list_all()


def test_archived_creation_is_not_presented_as_an_available_workspace():
    store = WorkspaceStore()
    created, _row, _warnings = create_workspace("Old workspace", "archived")
    store.archive(created.id)
    with pytest.raises(WorkspaceCreationRefused, match="workspace_archived"):
        create_workspace("Old workspace", "archived")
    assert store.get(created.id).archived


# ── the argv verb's contract (row: widen runtime.workspace.create) ─────────

from types import SimpleNamespace

from agent_runtime import workspace_create as wc
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS
from agent_runtime.store import RealmStore


def _rpc(params, rid="create"):
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": rid, "method": "runtime.workspace.create", "params": params})


def test_create_inside_the_active_realm_joins_it_and_activates():
    realm = RealmStore().create(name="Active realm")
    RealmStore().set_active(realm.id)
    result = _rpc({"name": "Joined", "idempotency_key": "join-1", "realm_id": realm.id})["result"]
    assert result["realm_id"] == realm.id
    assert result["id"] in RealmStore().get(realm.id).workspace_ids
    assert WorkspaceStore().active_id() == result["id"]
    assert result["warnings"] == []


def test_create_inside_an_inactive_realm_joins_but_never_moves_the_selection():
    active = RealmStore().create(name="Active realm")
    RealmStore().set_active(active.id)
    other = RealmStore().create(name="Other realm")
    before = WorkspaceStore().active_id()
    result = _rpc({"name": "Elsewhere", "idempotency_key": "join-2", "realm_id": other.id})["result"]
    assert result["id"] in RealmStore().get(other.id).workspace_ids
    assert WorkspaceStore().active_id() == before


def test_template_scopes_feed_the_create_and_ride_the_row():
    template = WorkspaceStore().create(name="Golden", agent_ids=["dev"], isolation="hard", max_concurrent_lanes=3)
    result = _rpc({"name": "Copied", "idempotency_key": "tpl-1", "template_workspace_id": template.id,
                   "copy_scopes": ["agents", "settings"]})["result"]
    created = WorkspaceStore().get(result["id"])
    assert created.agent_ids == ["dev"]
    assert (created.isolation, created.max_concurrent_lanes) == ("hard", 3)
    assert result["template_workspace_id"] == template.id
    assert result["copy_scopes"] == ["agents", "settings"]


def test_a_refused_template_does_not_burn_the_key():
    refused = _rpc({"name": "Late", "idempotency_key": "tpl-2", "template_workspace_id": "ws_missing"})
    assert refused["error"]["data"]["reason"] == "template_workspace_not_found"
    WorkspaceStore().create(name="Now here", workspace_id="ws_missing")
    result = _rpc({"name": "Late", "idempotency_key": "tpl-2", "template_workspace_id": "ws_missing"})["result"]
    assert result["template_workspace_id"] == "ws_missing"


def test_an_unknown_realm_is_refused_by_name():
    refused = _rpc({"name": "Nowhere", "idempotency_key": "realm-x", "realm_id": "realm_missing"})
    assert refused["error"]["data"]["reason"] == "realm_not_found"
    assert WorkspaceStore().list_all() == []


@pytest.mark.parametrize("params", [
    {"copy_scopes": ["office"]},
    {"template_workspace_id": "ws_t", "copy_scopes": ["office", "nonsense"]},
    {"template_workspace_id": "ws_t", "copy_scopes": "office"},
    {"surprise": 1},
])
def test_malformed_widened_params_are_invalid(params):
    WorkspaceStore().create(name="T", workspace_id="ws_t")
    refused = _rpc({"name": "Bad", "idempotency_key": "bad", **params})
    assert refused["error"]["code"] == ERR_INVALID_PARAMS
    assert len(WorkspaceStore().list_all()) == 1


def test_replaying_a_widened_request_answers_the_same_row_and_a_changed_one_conflicts():
    realm = RealmStore().create(name="R")
    first = _rpc({"name": "Once", "idempotency_key": "replay", "realm_id": realm.id})["result"]
    again = _rpc({"name": "Once", "idempotency_key": "replay", "realm_id": realm.id})["result"]
    assert again["id"] == first["id"]
    changed = _rpc({"name": "Once", "idempotency_key": "replay"})
    assert changed["error"]["data"]["reason"] == "idempotency_conflict"


def test_the_argv_verb_and_the_method_reach_one_implementation(monkeypatch):
    from hermes_cli.harness_parts import workspace_commands

    realm = RealmStore().create(name="Shared")
    seen = []
    real_apply = wc.apply_workspace_create

    def spy(plan, **kwargs):
        seen.append((plan.name, plan.realm_id))
        return real_apply(plan, **kwargs)

    monkeypatch.setattr(wc, "apply_workspace_create", spy)
    monkeypatch.setattr(workspace_commands, "_print_stage42", lambda *a, **k: None)
    args = SimpleNamespace(name="Argv", realm=realm.id, agent=[], blueprint=None, isolation=None,
                           max_lanes=None, from_workspace=None, copy=None, dry_run=False)
    assert workspace_commands._cmd_workspace_create(args) == 0
    _rpc({"name": "Method", "idempotency_key": "shared", "realm_id": realm.id})
    assert seen == [("Argv", realm.id), ("Method", realm.id)]
