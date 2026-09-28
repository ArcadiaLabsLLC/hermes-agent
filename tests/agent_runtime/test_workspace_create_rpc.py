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
    created = create_workspace("Temporary", "old-request")
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
    created = create_workspace("Old workspace", "archived")
    store.archive(created.id)
    with pytest.raises(WorkspaceCreationRefused, match="workspace_archived"):
        create_workspace("Old workspace", "archived")
    assert store.get(created.id).archived
