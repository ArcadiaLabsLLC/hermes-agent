"""Project references reuse WorkspaceStore; no roster, slot or content ownership moves."""
import pytest

from agent_runtime import serve_rpc
from agent_runtime.store import WorkspaceStore, RealmStore
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import SlotRefused, load_document


def connect(workspace, project="project-a", connected=True, revision=0):
    return set_project_connection(workspace, project, connected=connected, expected_revision=revision)


def test_many_to_many_references_persist_without_changing_existing_owners():
    store = WorkspaceStore()
    one = store.create(name="Same name", agent_ids=["builder"])
    two = store.create(name="Same name", agent_ids=["writer"])
    slots = load_document(one.id)
    connect(one.id)
    connect(one.id, "project-b", revision=1)
    connect(two.id)
    assert WorkspaceStore().get(one.id).project_ids == ["project-a", "project-b"]
    assert store.get(two.id).project_ids == ["project-a"]
    assert store.get(one.id).agent_ids == ["builder"]
    assert load_document(one.id) == slots
    connect(one.id, connected=False, revision=2)
    assert store.get(one.id).project_ids == ["project-b"]
    assert store.get(two.id).project_ids == ["project-a"]


def test_revision_conflicts_and_noop_retry_preserve_the_current_connection():
    workspace = WorkspaceStore().create(name="Revision").id
    first = connect(workspace)
    with pytest.raises(SlotRefused, match="stale_revision"):
        connect(workspace, "other")
    assert connect(workspace, revision=1) == first
    assert WorkspaceStore().get(workspace).project_ids == ["project-a"]


def test_an_older_workspace_edit_cannot_erase_a_new_connection():
    store = WorkspaceStore()
    held = store.create(name="Before")
    connect(held.id)
    held.name = "After"
    store.save(held)
    current = store.get(held.id)
    assert current.name == "After"
    assert current.project_ids == ["project-a"]
    assert current.project_assignment_revision == 1


def test_archived_workspace_refuses_connect_but_allows_disconnect():
    store = WorkspaceStore()
    workspace = store.create(name="Archived").id
    connect(workspace)
    store.archive(workspace)
    with pytest.raises(SlotRefused, match="workspace_archived"):
        connect(workspace, "other", revision=1)
    assert connect(workspace, connected=False, revision=1)["project_ids"] == []


def test_existing_realm_permission_denies_the_write_without_a_credential():
    realm = RealmStore().create(name="Shared")
    realm.server_id = "server"
    realm.sync_manifest_ref = "https://github.com/example/realm.git"
    RealmStore().save(realm)
    workspace = WorkspaceStore().create(name="Restricted", realm_id=realm.id).id
    with pytest.raises(SlotRefused):
        connect(workspace)
    assert WorkspaceStore().get(workspace).project_ids == []


@pytest.mark.parametrize("patch", [{"project_id": "../escape"}, {"connected": "true"}, {"expected_revision": True}, {"expected_revision": -1}])
def test_rpc_rejects_invalid_input_without_mutating(patch):
    workspace = WorkspaceStore().create(name="Validation").id
    params = {"workspace_id": workspace, "project_id": "project-a", "connected": True, "expected_revision": 0, **patch}
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "test", "method": "runtime.workspace.project.set", "params": params})
    assert "error" in reply
    assert WorkspaceStore().get(workspace).project_ids == []


def test_rpc_and_snapshot_use_the_same_workspace_record():
    from agent_runtime.snapshot.summaries import workspace_summary
    workspace = WorkspaceStore().create(name="Snapshot").id
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "test", "method": "runtime.workspace.project.set", "params": {
        "workspace_id": workspace, "project_id": "project-a", "connected": True, "expected_revision": 0,
    }})
    assert reply["result"]["revision"] == 1
    summary = workspace_summary(WorkspaceStore().get(workspace))
    assert summary["project_ids"] == ["project-a"]
    assert summary["project_assignment_revision"] == 1
