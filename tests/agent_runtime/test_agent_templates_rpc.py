"""Intelligence discovers and creates through the same native persona authority."""
from agent_runtime import serve_rpc
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_serve_rpc_agent_create import qa_persona, _seed_workspace, _instances, _actors, WORKSPACE


def call(method, params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "setup", "method": method, "params": params})


def test_template_catalog_drives_existing_creation_without_switching_workspace(qa_persona):
    _seed_workspace()
    before = WorkspaceStore().active_id()
    listed = call("runtime.agent.templates", {})["result"]["templates"]
    template = next(t for t in listed if t["id"] == qa_persona.id)
    assert template["name"] == "QA Agent"
    assert not _instances() and not _actors()
    params = {"persona_id": template["id"], "workspace_id": WORKSPACE, "idempotency_key": "intelligence-create"}
    created = call("runtime.agent.create", params)["result"]
    instance_id = created["persona_instance_id"]
    assert instance_id in _instances()
    assert created["actor_key"] in _actors()
    revision = _actors()[created["actor_key"]].revision
    replay = call("runtime.agent.create", params)["result"]
    assert replay["persona_instance_id"] == instance_id
    assert _actors()[created["actor_key"]].revision == revision
    assert WorkspaceStore().active_id() == before


def test_template_catalog_refuses_injected_scope():
    assert call("runtime.agent.templates", {"workspace_id": "foreign"})["error"]["code"] == -32602


def test_new_workspace_accepts_shared_agent_creation_without_an_office_visit(qa_persona):
    workspace = call("runtime.workspace.create", {"name": "New team", "idempotency_key": "setup"})["result"]
    reply = call("runtime.agent.create", {
        "workspace_id": workspace["id"], "persona_id": qa_persona.id, "idempotency_key": "new-team-agent"})
    assert "error" not in reply, reply
    assert reply["result"]["persona_instance_id"] in _instances()
    assert reply["result"]["actor_key"] in _actors(workspace["id"])
