"""Permission inspection belongs to the exact native chat, without consuming grants."""
from contextlib import closing

from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.tool_permissions import ChatToolPermissionStore
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, _call, _device, qa_persona, placed_agent
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OTHER


def test_permissions_read_exact_chat_and_preserve_grant_and_default(placed_agent):
    first = target(placed_agent["persona_instance_id"])
    second = _call(dict(persona_id=PERSONA, persona_instance_id=first["persona_instance_id"],
        new_session=True, idempotency_key="second-permission-chat", client_scope=first["client_scope"]))["result"]
    other = {**first, "session_id": second["session_id"]}
    store = ChatToolPermissionStore()
    store.set(persona_id=PERSONA, session_id=first["session_id"], mode="read_only", reason="first")
    store.set(persona_id=PERSONA, session_id=other["session_id"], mode="unbounded", reason="second", turns_remaining=1)
    before = store.path.read_bytes()
    instance = PersonaInstanceStore().get(first["persona_instance_id"])
    with closing(default_persona_session_db()) as db:
        session_before = db.get_session(other["session_id"])
    for params, mode, terminal in ((first, "read_only", False), (other, "unbounded", True)):
        reply = inspect("permissions", params)
        assert "result" in reply, reply
        result = reply["result"]
        assert all(result[key] == value for key, value in params.items())
        facts = result["permission_state"]
        assert facts["session_id"] == params["session_id"]
        assert facts["persona_id"] == PERSONA
        assert facts["mode"] == mode and facts["can_run_terminal"] is terminal
    assert inspect("permissions", other)["result"]["permission_state"]["turns_remaining"] == 1
    for extra, reason in (({"client_scope": OTHER}, "conversation_owner_changed"),
                          ({"install_id": "other-install"}, "installation_changed")):
        assert inspect("permissions", {**other, **extra})["error"]["data"]["reason"] == reason
    assert "error" in inspect("permissions", other, _device("read"))
    assert store.path.read_bytes() == before
    assert PersonaInstanceStore().get(first["persona_instance_id"]) == instance
    with closing(default_persona_session_db()) as db:
        assert db.get_session(other["session_id"]) == session_before
