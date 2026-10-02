"""Native clarification survives reconstruction without a second question store."""
from types import SimpleNamespace

from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from hermes_cli.harness_parts.persona.chat_request import _mission_chat_clarify_request_payload
from tests.agent_runtime.test_operator_conversation_attachment import fixture, call


def test_current_question_reopens_and_disappears_after_native_settlement(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    question = {"question": "Which project?", "choices": ["Launcher", "Harness"]}
    payload = _mission_chat_clarify_request_payload(
        SimpleNamespace(raw={"clarify_request": question}),
        session_id=target["session_id"], persona_id=target["persona_id"],
        persona_instance_id=target["persona_instance_id"], client_message_id="ask",
        turn_id="ask", requested_by_session=None)
    assert payload["clarify_token"]
    page = call("read", target)["result"]
    assert page["question"] == question
    assert page["clarify_token"] == payload["clarify_token"]
    store = PersonaChatClarifyTicketStore()
    store.settle(payload["clarify_token"], client_message_id="answer", bound_via="token")
    reopened = call("read", target)["result"]
    assert reopened["question"] is None
    assert reopened["clarify_token"] is None
