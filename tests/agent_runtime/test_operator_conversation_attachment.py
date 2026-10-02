"""Real profile stores and the RPC dispatcher; no serve or provider process."""
from contextlib import closing

from agent_runtime import paths, serve_rpc
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.states import WorkerSessionState
from hermes_state import SessionDB


def fixture(home, monkeypatch, name):
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "runtime"))
    install = ensure_install_identity(paths.store_root()).install_id
    instance = "personainst_builder"
    session = f"persona_chat_{instance}_123456abcdef"
    store = PersonaInstanceStore()
    store._write(PersonaInstance(id=instance, persona_id="builder", role="builder",
        display_name=name, profile_id=None, runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE, workspace_id="ws", default_chat_session_id=session))
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.create_session(session, source="mission_chat")
        for i in range(44):
            db.append_message(session, "user" if i % 2 == 0 else "assistant", f"{name} message {i}")
    return dict(install_id=install, workspace_id="ws", persona_id="builder",
        persona_instance_id=instance, session_id=session)


def call(operation, params, *, spawn=None):
    return serve_rpc.handle_request(dict(jsonrpc="2.0", id="read",
        method=f"runtime.operator.conversation.{operation}", params=params),
        serve_rpc.RpcContext(spawn_chat_turn=spawn))


def test_attach_reuses_history_questions_and_send_owner_across_profiles(tmp_path, monkeypatch):
    a = fixture(tmp_path / "a", monkeypatch, "Amelia")
    ticket = PersonaChatClarifyTicketStore().mint(chat_session_id=a["session_id"],
        persona_instance_id=a["persona_instance_id"], persona_id="builder",
        question={"question": "Which project?", "choices": ["Launcher", "Harness"]})
    persist_mission_chat_turn(session_id=a["session_id"], client_message_id="old-turn",
        turn_id="old-turn", state="running", elements=[{"kind": "segment", "text": "Partial"}])
    attached = call("read", a)
    assert "result" in attached, attached
    read = attached["result"]
    assert read["clarify_token"] == ticket
    assert read["question"] == {"question": "Which project?", "choices": ["Launcher", "Harness"]}
    assert read["active_turns"][0]["client_message_id"] == "old-turn"
    assert len(read["messages"]) == 40 and read["next_before"]
    earlier = call("read", {**a, "before": read["next_before"]})["result"]
    assert len(earlier["messages"]) == 4
    assert not ({row["id"] for row in earlier["messages"]} & {row["id"] for row in read["messages"]})
    spawned = []
    params = {**a, "turn_request_id": "reply-one", "message": "My answer", "clarify_token": ticket}
    first = serve_rpc.handle_request(dict(jsonrpc="2.0", id="mc",
        method="runtime.chat.message", params=params),
        serve_rpc.RpcContext(spawn_chat_turn=lambda *args: spawned.append(args)))
    second = call("message", params, spawn=lambda *args: spawned.append(args))
    assert first["result"]["accepted"] and second["result"]["idempotent_replay"]
    assert len(spawned) == 1
    assert a["session_id"] in spawned[0][1] and ticket in spawned[0][1]
    assert call("read", params)["result"]["delivery_pending"]
    b = fixture(tmp_path / "b", monkeypatch, "Other")
    assert call("read", a)["error"]["data"]["reason"] == "installation_changed"
    assert call("read", b)["result"]["messages"][0]["text"].startswith("Other")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "a"))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(tmp_path / "a"))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "a" / "runtime"))
    assert call("read", a)["result"]["clarify_token"] == ticket
    assert call("read", a)["result"]["question"] == read["question"]
    assert call("read", a)["result"]["messages"][0]["text"].startswith("Amelia")


def test_attachment_refuses_retargeting_or_missing_sessions_without_mint(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    spawned = []
    send = {**target, "turn_request_id": "send", "message": "Test"}
    for mutation, reason in [
        ({"workspace_id": "other"}, "workspace_changed"),
        ({"persona_id": "other"}, "agent_changed"),
        ({"session_id": "persona_chat_personainst_other_123456abcdef"}, "foreign_session"),
        ({"session_id": "persona_chat_personainst_builder_abcdef123456"}, "session_not_found"),
        ({"new_session": True}, "replace_not_allowed"),
        ({"persona_instance_id": "../../outside"}, "conversation_identity_invalid"),
    ]:
        result = call("message", {**send, **mutation}, spawn=lambda *args: spawned.append(args))
        assert result["error"]["data"]["reason"] == reason, result
    assert spawned == []
    assert PersonaInstanceStore().get(target["persona_instance_id"]).default_chat_session_id == target["session_id"]
