"""Agent creation resolves a workspace without requiring a scene consumer."""

from __future__ import annotations

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.office_store import OfficeStore
from tests.agent_runtime.office_seed import seed_workspace_record, unlink_workspace_record
from tests.agent_runtime.test_agent_create_service import qa_persona as qa_persona


def _create_in_workspace(workspace_id: str) -> dict:
    return serve_rpc.handle_request({
        "jsonrpc": "2.0",
        "id": "cold-workspace",
        "method": "runtime.agent.create",
        "params": {
            "persona_id": "qa",
            "workspace_id": workspace_id,
            "idempotency_key": "cold-create",
        },
    })


def test_cold_workspace_creates_through_rpc_without_a_scene(qa_persona):
    workspace_id = "ws_cold_creation"
    seed_workspace_record(workspace_id)
    office = OfficeStore()
    assert not office.surface_exists(workspace_id)

    reply = _create_in_workspace(workspace_id)

    assert "error" not in reply, reply
    created = reply["result"]
    instance_path = paths.persona_instance_path(created["persona_instance_id"])
    assert instance_path.exists()
    actor = office.get_actor(workspace_id, created["actor_key"])
    assert actor.persona_instance_id == created["persona_instance_id"]
    assert actor.revision == 1
    assert office.surface_exists(workspace_id)
    replay = _create_in_workspace(workspace_id)["result"]
    assert replay["idempotent_replay"] is True
    assert replay["persona_instance_id"] == created["persona_instance_id"]
    assert office.get_actor(workspace_id, created["actor_key"]).revision == 1


@pytest.mark.parametrize("orphaned_scene", [False, True])
def test_missing_workspace_refuses_without_writes_even_with_a_scene(qa_persona, orphaned_scene):
    workspace_id = "ws_missing_creation"
    if orphaned_scene:
        seed_workspace_record(workspace_id)
        OfficeStore().ensure_surface(workspace_id)
        unlink_workspace_record(workspace_id)
    before = {str(path): path.read_bytes() for path in paths.store_root().rglob("*") if path.is_file()}

    reply = _create_in_workspace(workspace_id)

    assert reply["error"]["data"]["reason"] == "workspace_not_found"
    assert reply["error"]["data"]["rolled_back"] is True
    assert {str(path): path.read_bytes() for path in paths.store_root().rglob("*") if path.is_file()} == before
