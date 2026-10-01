"""Real directory preparation preserves native identity, configuration and work."""
from dataclasses import replace

from agent_runtime import paths, serve_rpc
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore, WorkspaceStore
from agent_runtime.states import WorkerSessionState
from hermes_cli import profiles
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, PERSONA


def call(method):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "directory", "method": method, "params": {}})


def test_native_directory_keeps_authored_canonical_and_placed_identity(placed_agent):
    ensure_install_identity(paths.store_root())
    profile = profiles._get_profiles_root() / "alice"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("{}\n", encoding="utf-8")
    personas = AgentStore()
    authored = personas.get(PERSONA)
    authored.hermes_profile = "alice"
    personas.save(authored)
    store = PersonaInstanceStore()
    canonical = store.ensure_for_persona(authored)
    store.update(replace(canonical, state=WorkerSessionState.RUNNING, token_budget_used=42))
    before = {row.id: row for row in store.list_all()}
    first = call("runtime.agent.directory")["result"]
    second = call("runtime.agent.directory")["result"]
    assert first == second
    assert {row["instance_id"] for row in first["agents"]} == set(before)
    assert {row["persona_id"] for row in first["agents"]} == {PERSONA}
    assert {row["profile"] for row in first["agents"]} == {"alice"}
    assert {row["profile_home"] for row in first["agents"]} == {str(profile)}
    assert {row["canonical"] for row in first["agents"]} == {False, True}
    assert {row.id: row for row in store.list_all()} == before
    assert {row.id for row in personas.list_all()} == {PERSONA}


def test_conversations_home_is_shared_and_never_changes_operator_selection(placed_agent):
    store = WorkspaceStore()
    workspace = store.create(name="Working here")
    store.set_active(workspace.id)
    instance_store = PersonaInstanceStore()
    before = instance_store.get(placed_agent["persona_instance_id"])
    first = call("runtime.workspace.conversations")["result"]
    assert first == call("runtime.workspace.conversations")["result"]
    assert first["name"] == "Conversations"
    assert store.active_id() == workspace.id
    assert instance_store.get(before.id) == before
    store.archive(first["id"])
    assert call("runtime.workspace.conversations")["error"]["data"]["reason"] == "workspace_archived"
