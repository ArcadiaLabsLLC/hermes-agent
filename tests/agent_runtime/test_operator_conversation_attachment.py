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


def fixture(home, monkeypatch, name, *, persona_id="builder"):
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "runtime"))
    install = ensure_install_identity(paths.store_root()).install_id
    instance = f"personainst_{persona_id}"
    session = f"persona_chat_{instance}_123456abcdef"
    store = PersonaInstanceStore()
    store._write(PersonaInstance(id=instance, persona_id=persona_id, role="builder",
        display_name=name, profile_id=None, runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE, workspace_id="ws", default_chat_session_id=session))
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.create_session(session, source="mission_chat")
        for i in range(44):
            db.append_message(session, "user" if i % 2 == 0 else "assistant", f"{name} message {i}")
    # The row stands in "ws": nothing decodes a hidden copy global any more
    # (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT), so its identity names its workspace.
    return dict(install_id=install, workspace_id="ws", persona_id=persona_id,
        persona_instance_id=instance, session_id=session)


def call(operation, params, *, spawn=None):
    return serve_rpc.handle_request(dict(jsonrpc="2.0", id="read",
        method=f"runtime.operator.conversation.{operation}", params=params),
        serve_rpc.RpcContext(spawn_chat_turn=spawn))


def test_attach_reuses_history_questions_and_send_owner_across_profiles(tmp_path, monkeypatch):
    a = fixture(tmp_path / "a", monkeypatch, "Amelia")
    ticket = PersonaChatClarifyTicketStore().mint(chat_session_id=a["session_id"],
        persona_instance_id=a["persona_instance_id"], persona_id="builder")
    persist_mission_chat_turn(session_id=a["session_id"], client_message_id="old-turn",
        turn_id="old-turn", state="running", elements=[{"kind": "segment", "text": "Partial"}])
    attached = call("read", a)
    assert "result" in attached, attached
    read = attached["result"]
    assert read["clarify_token"] == ticket
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


def test_a_run_chats_computer_opens_only_the_chat_its_own_scope_started(tmp_path, monkeypatch):
    """Hermes rows RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT
    (review w1122b.5) and RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE (review w1122d.2): a
    computer at Run chats reads under its grant's own client_scope, stamped at dispatch over whatever it
    names (none, its account key, the phone owner's); through it the attach read opens the chat that
    scope owns, and the phone owner's chat answers conversation_owner_changed. The account grant and
    the desktop operator keep the unscoped path.

    MUTATION (``serve_rpc.dispatch.bind_computer_scope``): return the params unstamped, and the
    scope-less read below opens the phone owner's chat.
    """

    from agent_runtime.call_authorization import CALLER_COMPUTER, TRANSPORT_GATEWAY, RpcCaller
    from agent_runtime.reverse_lane.grants import computer_client_scope

    owners = fixture(tmp_path / "phone", monkeypatch, "Owner")
    mine = computer_client_scope("cmp_far")
    computers = f"persona_chat_{owners['persona_instance_id']}_c0ffee000001"
    with closing(SessionDB(db_path=tmp_path / "phone" / "state.db")) as db:
        db.create_session(computers, source="mission_chat", model_config={"client_scope": mine})
        db.append_message(computers, "user", "from the computer")

    def as_computer(grant, params):
        caller = RpcCaller(kind=CALLER_COMPUTER, connection_key="c1", transport=TRANSPORT_GATEWAY,
                           computer_id="cmp_far", computer_grant=grant)
        return serve_rpc.handle_request(dict(jsonrpc="2.0", id="read",
            method="runtime.operator.conversation.read", params=params), serve_rpc.RpcContext(caller=caller))

    for named in ({}, {"client_scope": None}, {"client_scope": "a" * 64}, {"client_scope": mine}):
        other = as_computer("chat", {**owners, **named})
        assert other["error"]["data"]["reason"] == "conversation_owner_changed", (named, other)
        started = as_computer("chat", {**owners, **named, "session_id": computers})
        assert started["result"]["messages"][0]["text"] == "from the computer", (named, started)
    # Look never reaches it; the account grant reads like a paired console device.
    assert as_computer("look", {**owners, "client_scope": mine})["error"]["data"]["reason"] == "scope_denied"
    assert as_computer("account", owners)["result"]["messages"][0]["text"].startswith("Owner")
    assert call("read", owners)["result"]["messages"][0]["text"].startswith("Owner")


def test_read_names_a_question_asked_in_a_turn_no_client_waited_on(tmp_path, monkeypatch):
    """RT-FU-A-QUESTION-ASKED-IN-A-BACKGROUND-TURN-IS-NAMED-BY-THE-CHAT-READ: a helper's reply the
    runtime delivered asked the operator something; opening the chat must name the question.

    MUTATION: drop the read's ``"clarify": waiting_clarify_question(ticket)`` and both reads redden
    (KeyError); drop the mint's ``**_ticket_question(...)`` and the new ticket's read is None (the
    asking turn below it holds no question); drop ``_asking_turn_question``'s fallback and the
    old ticket's read is None."""
    a = fixture(tmp_path / "a", monkeypatch, "Amelia")
    store = PersonaChatClarifyTicketStore()
    question = "How should I unblock the sixth pass?"
    choices = ["Switch to smart approvals", "Keep manual approvals"]
    turn = "dispatch-delivery-dispatch-f979c7c6c48f"
    # A ticket minted before the question was stored on it: only its asking turn holds the text.
    old = store.mint(chat_session_id=a["session_id"], persona_instance_id=a["persona_instance_id"],
        persona_id="builder", asked_by_client_message_id=turn, asked_turn_id=turn)
    persist_mission_chat_turn(session_id=a["session_id"], client_message_id=turn, turn_id=turn,
        state="completed", elements=[{"kind": "segment", "text": "Pass 5 stalled."}],
        metadata={"auxiliary_result": {"clarify": {"question": question, "choices": choices}}})
    read = call("read", a)["result"]
    assert read["clarify_token"] == old
    assert read["clarify"] == {"clarify_token": old, "question": question, "choices": choices}
    store.settle(old, client_message_id="answered")
    # A ticket minted now carries its own question; its asking turn recorded none.
    new = store.mint(chat_session_id=a["session_id"], persona_instance_id=a["persona_instance_id"],
        persona_id="builder", asked_by_client_message_id="later", asked_turn_id="later",
        question="Which branch?", choices=["main", " ", "release"])
    read = call("read", a)["result"]
    assert read["clarify_token"] == new
    assert read["clarify"] == {"clarify_token": new, "question": "Which branch?", "choices": ["main", "release"]}


def test_the_turn_that_asks_mints_a_ticket_holding_its_question(tmp_path, monkeypatch):
    """The mint the settle path calls stores the turn's question on the ticket, so the read above
    needs no asking-turn record. MUTATION: drop ``question=raw.get("question")`` from
    ``_mission_chat_clarify_request_payload``'s mint and this reddens."""
    from types import SimpleNamespace

    from hermes_cli.harness_parts.persona.chat_request import _mission_chat_clarify_request_payload

    a = fixture(tmp_path / "a", monkeypatch, "Amelia")
    raw = {"clarify_request": {"question": "Which branch?", "choices": ["main", "release"]}}
    payload = _mission_chat_clarify_request_payload(SimpleNamespace(raw=raw), session_id=a["session_id"],
        persona_id="builder", persona_instance_id=a["persona_instance_id"],
        client_message_id="dispatch-delivery-x", turn_id="dispatch-delivery-x", requested_by_session=None)
    ticket = PersonaChatClarifyTicketStore().resolve(payload["clarify_token"])
    assert (ticket["question"], ticket["choices"]) == ("Which branch?", ["main", "release"])
