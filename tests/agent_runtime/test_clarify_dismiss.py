"""RT-FU-THE-OPERATOR-CAN-DISMISS-AN-AGENTS-QUESTION-WITHOUT-ANSWERING-IT: the operator closes an
agent's waiting question through ``runtime.chat.clarify.dismiss``; the chat stops waiting and the
agent's next turn there reads one line saying so.

Real profile stores and the RPC dispatcher; no serve or provider process. Killing mutations
(recorded in the landing commit): ``PersonaChatClarifyTicketStore.dismiss`` without its
``state != open`` arm -> the answered-question test reds; the verb's ``client_scope`` check skipped
-> the scoped-caller test reds; ``take_dismissal_note`` not unlinking -> "told once" reds;
``_compose_volatile_tail`` without the ``clarify_dismissed`` contributor -> the next-turn line reds.
"""

from __future__ import annotations

from dataclasses import replace

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.mission_chat_turn_context import _compose_volatile_tail
from agent_runtime.mission_chat_turn_resolvers import DEFAULT_RESOLVERS
from agent_runtime.operator_session_models import _require_idle
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture

QUESTION = "Which branch should I merge into?"


def _asked(tmp_path, monkeypatch):
    chat = fixture(tmp_path / "home", monkeypatch, "Neko")
    token = PersonaChatClarifyTicketStore().mint(
        chat_session_id=chat["session_id"], persona_instance_id=chat["persona_instance_id"],
        persona_id=chat["persona_id"], question=QUESTION, choices=["main", "release"])
    return chat, token


def _dismiss(session_id, token, *, caller=LOCAL_CONSOLE):
    context = serve_rpc.RpcContext(caller=caller)
    request = {"jsonrpc": "2.0", "id": "d", "method": "runtime.chat.clarify.dismiss",
               "params": {"session_id": session_id, "clarify_token": token}}
    return serve_rpc.handle_request(request, context)


def _next_turn_tail(session_id) -> str:
    resolvers = replace(DEFAULT_RESOLVERS, admission_line=lambda *_args, **_kwargs: "")
    return _compose_volatile_tail(persona=None, session_id=session_id, wall_budget=None, capability={},
                                  resolvers=resolvers).content


def test_a_dismissed_question_stops_waiting_and_the_next_turn_is_told_once(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    assert call("read", chat)["result"]["clarify"]["question"] == QUESTION

    result = _dismiss(chat["session_id"], token)["result"]

    assert (result["outcome"], result["dismissed"], result["state"]) == ("dismissed", True, "dismissed")
    read = call("read", chat)["result"]
    assert (read["clarify_token"], read["clarify"]) == (None, None)
    _require_idle(chat["session_id"])
    assert PersonaChatClarifyTicketStore().resolve(token)["bound_via"] == "dismissed"
    tail = _next_turn_tail(chat["session_id"])
    assert f'The operator dismissed your earlier question ("{QUESTION}") without answering it' in tail
    assert "dismissed" not in _next_turn_tail(chat["session_id"])


def test_dismissing_again_or_an_unknown_question_answers_with_its_reason(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    _dismiss(chat["session_id"], token)
    _next_turn_tail(chat["session_id"])

    again = _dismiss(chat["session_id"], token)["result"]
    unknown = _dismiss(chat["session_id"], "clarify-000000000000")["result"]

    assert (again["outcome"], again["dismissed"]) == ("already_dismissed", False)
    assert (unknown["outcome"], unknown["dismissed"], unknown["state"]) == ("unknown_ticket", False, None)
    # Neither left a second note for the next turn.
    assert "dismissed" not in _next_turn_tail(chat["session_id"])


def test_an_answered_question_is_not_dismissed(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    PersonaChatClarifyTicketStore().settle(token, client_message_id="answer-1")

    result = _dismiss(chat["session_id"], token)["result"]

    assert (result["outcome"], result["state"]) == ("already_answered", "answered")
    assert PersonaChatClarifyTicketStore().resolve(token)["state"] == "answered"
    assert "dismissed" not in _next_turn_tail(chat["session_id"])


def test_a_question_asked_in_another_chat_is_refused(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)

    frame = _dismiss(f"persona_chat_{chat['persona_instance_id']}_fedcba654321", token)

    assert frame["error"]["data"]["reason"] == "foreign_chat_session"
    assert call("read", chat)["result"]["clarify_token"] == token


def test_a_scoped_caller_cannot_dismiss_in_another_scopes_chat(tmp_path, monkeypatch):
    from contextlib import closing

    from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
    from hermes_state import SessionDB

    target = fixture(tmp_path / "phone", monkeypatch, "Owner")
    owners = f"persona_chat_{target['persona_instance_id']}_0a0a0a000001"
    with closing(SessionDB(db_path=tmp_path / "phone" / "state.db")) as db:
        db.create_session(owners, source=PERSONA_CHAT_SESSION_SOURCE, model_config={"client_scope": "a" * 64})
        db.append_message(owners, "user", "hello")
    token = PersonaChatClarifyTicketStore().mint(
        chat_session_id=owners, persona_instance_id=target["persona_instance_id"],
        persona_id=target["persona_id"], question=QUESTION)

    request = {"jsonrpc": "2.0", "id": "d", "method": "runtime.chat.clarify.dismiss",
               "params": {"session_id": owners, "clarify_token": token, "client_scope": "c" * 64}}
    frame = serve_rpc.handle_request(request, serve_rpc.RpcContext(caller=LOCAL_CONSOLE))

    assert "chat root is not owned by this client scope" in str(frame), frame
    assert PersonaChatClarifyTicketStore().resolve(token)["state"] == "open"
