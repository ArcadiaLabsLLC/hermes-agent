"""Real native persistence and dispatcher controls; no provider or persona run."""
from contextlib import closing
import time

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.mission_chat_turns import persist_mission_chat_turn, transition_mission_chat_turn
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.persona_chat_history.suggestion_context import suggestion_context
from agent_runtime.console_suggestions.service import ConsoleSuggestions
from agent_runtime.states import WorkerSessionState
from hermes_state import SessionDB


@pytest.fixture
def native(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "runtime"))
    install = ensure_install_identity(paths.store_root()).install_id
    instance = "personainst_builder"
    session = f"persona_chat_{instance}_123456abcdef"
    PersonaInstanceStore()._write(PersonaInstance(id=instance, persona_id="builder", role="builder",
        display_name="Persona", profile_id=None, runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE, workspace_id="ws", default_chat_session_id=session))
    scope = "a" * 64
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.create_session(session, source="mission_chat", model_config={"client_scope": scope})
        db.append_message(session, "user", "Explain [foo].", platform_message_id="message")
        db.append_message(session, "assistant", "Here is the explanation.", platform_message_id="message:assistant:0")
    persist_mission_chat_turn(session_id=session, client_message_id="message", turn_id="turn", state="pending",
        write_ahead=True, elements=[], metadata={"pending_user_message": "Explain [foo].\n[Image attached: /private/image.png]"})
    for state, metadata in [("executing", {}), ("native_committed", {"stored_reply": "Here is the explanation.", "native_committed": True}),
                            ("projected", {"projection_committed": True})]:
        transition_mission_chat_turn(session_id=session, client_message_id="message", turn_id="turn", state=state, elements=[], metadata=metadata)
    target = dict(install_id=install, workspace_id="ws", persona_id="builder", persona_instance_id=instance,
        session_id=session, client_scope=scope)
    return home, target


def test_native_context_is_curated_and_owner_checked(native):
    home, target = native
    result = suggestion_context(target, 4)
    assert "reason" not in result, result
    assert result["messages"] == [{"role": "user", "content": "Explain [foo]."},
                                  {"role": "assistant", "content": "Here is the explanation."}]
    assert "image.png" not in str(result)
    with pytest.raises(Exception, match="conversation_owner_changed"):
        suggestion_context({**target, "client_scope": "b" * 64}, 4)
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.append_message(target["session_id"], "user", "New uncommitted input", platform_message_id="new")
    assert suggestion_context(target, 4)["reason"] == "source_ineligible"


def test_pending_manual_control_and_expired_turn_are_ineligible(native):
    _, target = native
    assert suggestion_context(target, 4, now=time.time() + 90000)["reason"] == "expired"
    PersonaChatClarifyTicketStore().mint(chat_session_id=target["session_id"],
        persona_instance_id=target["persona_instance_id"], persona_id=target["persona_id"])
    assert suggestion_context(target, 4)["reason"] == "manual_confirmation_required"


def test_rpc_manifest_off_gate_identity_and_settings_cas(native):
    home, target = native
    service = ConsoleSuggestions(home)
    context = serve_rpc.RpcContext(emit=lambda frame: None, console_suggestions=lambda: service)
    def call(method, params):
        return serve_rpc.handle_request(dict(jsonrpc="2.0", id="test", method=method, params=params), context)
    try:
        prefix = "runtime.console_suggestions.settings"
        result = call(prefix + ".get", target)
        assert "result" in result, result
        settings = result["result"]
        invalid = call(prefix + ".set", {**target, "expected_revision": settings["settings_revision"], "cooldown_seconds": -1})
        assert invalid["error"]["code"] == -32602
        assert settings["enabled"] is False and settings["install_id"] == target["install_id"]
        disabled = call("runtime.operator.conversation.suggestions.read", target)
        assert disabled["result"]["state"] == "disabled"
        assert not service.store.path.exists()
        changed = call(prefix + ".set", {**target, "expected_revision": settings["settings_revision"], "enabled": True})
        assert changed["result"]["enabled"] is True, changed
        assert call(prefix + ".set", {**target, "expected_revision": settings["settings_revision"], "enabled": False})["error"]["data"]["reason"] == "stale_revision"
        assert call(prefix + ".get", {**target, "install_id": "other"})["error"]["data"]["reason"] == "installation_changed"
        denied = call("runtime.operator.conversation.suggestions.read", {**target, "client_scope": "b" * 64})
        assert denied["error"]["data"]["reason"] == "conversation_owner_changed", denied
    finally:
        service.close()
