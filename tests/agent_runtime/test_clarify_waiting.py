"""MC-A-QUESTION-THE-CHAT-MOVED-PAST-STILL-WAITS-FOR-YOUR-ANSWER: a question stops reading as waiting
once its agent's current chat is another chat where somebody sent a turn after it was asked.

Real profile stores and the RPC dispatcher (the read the Launcher's Home menu shows "Waiting for your
answer" from); no serve or provider process. Killing mutations (recorded in the landing commit):
``waiting_clarify_ticket`` answering the open ticket without ``clarify_question_moved_past`` -> the
moved-on case reds; drop the ``_RUNTIME_DELIVERED`` test -> the delivered-turn control reds.
"""

from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_session_models import _require_idle
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture

import pytest


def _asked(tmp_path, monkeypatch):
    chat = fixture(tmp_path / "home", monkeypatch, "Neko")
    token = PersonaChatClarifyTicketStore().mint(
        chat_session_id=chat["session_id"], persona_instance_id=chat["persona_instance_id"],
        persona_id=chat["persona_id"])
    return chat, token


def _moved_to(chat, turn_id):
    later = f"persona_chat_{chat['persona_instance_id']}_fedcba654321"
    persist_mission_chat_turn(session_id=later, client_message_id=turn_id, turn_id=turn_id,
                              state="projected", elements=[{"kind": "segment", "text": "Next"}])
    PersonaInstanceStore().patch_fields(chat["persona_instance_id"], default_chat_session_id=later)


def test_a_question_waits_while_its_chat_is_the_agents_current_one(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    assert call("read", chat)["result"]["clarify_token"] == token
    with pytest.raises(OperatorConversationRefused):
        _require_idle(chat["session_id"])


def test_a_question_the_operator_moved_past_stops_waiting(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    _moved_to(chat, "agent-chat-send-later")
    assert call("read", chat)["result"]["clarify_token"] is None
    _require_idle(chat["session_id"])
    # Read only: the ticket itself stays open, so an answer still binds.
    assert PersonaChatClarifyTicketStore().resolve(token)["state"] == "open"


def test_a_turn_the_runtime_delivered_elsewhere_is_not_moving_on(tmp_path, monkeypatch):
    """Positive control: the same move, made by a helper's delivered answer."""
    chat, token = _asked(tmp_path, monkeypatch)
    _moved_to(chat, "dispatch-delivery-dispatch-abc123")
    assert call("read", chat)["result"]["clarify_token"] == token
