"""Durable transcript outcomes and exact-turn dismissal, across a fresh read."""
from __future__ import annotations

import pytest

from agent_runtime.chat_verbs import turn_resolve
from agent_runtime.mission_chat_turns import persist_mission_chat_turn, transition_mission_chat_turn
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.operator_channels.history_messages import _conversation_history_message
from agent_runtime.persona_chat_history.curation import _safe_curated_messages


class TranscriptDB:
    def __init__(self, rows):
        self.rows = rows

    def get_messages(self, session_id, include_inactive=False):
        return self.rows


def _prompt(client_id="prompt"):
    return {"id": 1, "role": "user", "content": "check the build",
            "platform_message_id": client_id, "timestamp": "2026-10-14T10:00:00Z"}


def _read(rows):
    curated, _, unread = _safe_curated_messages(TranscriptDB(rows), session_id="chat")
    assert unread is None
    return curated


@pytest.mark.parametrize(("state", "expected"), [
    ("failed", "failed"), ("interrupted", "interrupted"),
    ("completed", "delivered"), (None, "delivered"),
])
def test_reopened_operator_row_keeps_recorded_outcome(isolate_agent_runtime_root, state, expected):
    if state:
        persist_mission_chat_turn(session_id="chat", client_message_id="prompt",
                                  turn_id="prompt", elements=[], state=state)
    operator = next(row for row in _read([_prompt()]) if row["role"] == "operator")
    message = _conversation_history_message(operator, channel_id="channel", index=0,
                                            persona_id="profile_dev", persona_instance_id="dev")
    assert message["status"] == expected
    assert message.get("settled_state") == state


def _interrupted():
    persist_mission_chat_turn(session_id="chat", client_message_id="prompt",
                              turn_id="prompt", elements=[], state="interrupted")


def _dismiss(**overrides):
    params = dict(session_id="chat", client_message_id="prompt", turn_id="prompt",
                  persona_instance_id="dev", action="dismiss")
    return turn_resolve.resolve_chat_turn(**(params | overrides))


def test_dismiss_survives_reload_without_erasing_the_interruption(isolate_agent_runtime_root, monkeypatch):
    monkeypatch.setattr(turn_resolve, "_owner_instance_id", lambda _: "dev")
    _interrupted()
    assert any(row.get("kind") == "turn_interrupted" for row in _read([_prompt()]))
    receipt = _dismiss()
    assert receipt["ok"] is True
    assert receipt["journal_state"] == "interrupted"
    record = mission_chat_turn_record(session_id="chat", client_message_id="prompt")
    assert record["resolution"] == "dismiss"
    assert record["state"] == "interrupted"
    history = _read([_prompt()])
    marker = next(row for row in history if row.get("kind") == "turn_interrupted")
    assert marker["resolution"] == "dismiss"
    from agent_runtime.operator_channels.conversation import _settle_terminal_tool_calls
    tools = [{"kind": "tool_call", "status": "running", "turn_id": "prompt", "tool": {}}]
    _settle_terminal_tool_calls(tools, history={"messages": history})
    assert tools[0]["status"] == "interrupted"
    assert _dismiss()["ok"] is True  # lost receipt: same operation is safe to repeat


@pytest.mark.parametrize("overrides", [
    {"persona_instance_id": "another_persona"}, {"turn_id": "another_turn"},
    {"client_message_id": "another_prompt"},
])
def test_dismiss_never_changes_a_different_persona_or_turn(isolate_agent_runtime_root, monkeypatch, overrides):
    monkeypatch.setattr(turn_resolve, "_owner_instance_id", lambda _: "dev")
    _interrupted()
    assert _dismiss(**overrides)["ok"] is False
    assert "resolution" not in mission_chat_turn_record(session_id="chat", client_message_id="prompt")


def test_dismiss_does_not_resolve_an_uncertain_request(isolate_agent_runtime_root, monkeypatch):
    monkeypatch.setattr(turn_resolve, "_owner_instance_id", lambda _: "dev")
    for state in ("pending", "executing", "outcome_unknown"):
        transition_mission_chat_turn(session_id="chat", client_message_id="prompt", turn_id="prompt", state=state)
    assert _dismiss()["ok"] is False
    assert mission_chat_turn_record(session_id="chat", client_message_id="prompt")["state"] == "outcome_unknown"


def test_replyless_marker_does_not_offer_a_missing_prompt(isolate_agent_runtime_root):
    _interrupted()
    marker = next(row for row in _read([]) if row.get("kind") == "turn_interrupted")
    assert "Retry the message" not in marker["text"]
    assert marker["operator_message_present"] is False
