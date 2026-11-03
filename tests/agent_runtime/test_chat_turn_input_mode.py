"""RT-CHAT-TURN-INPUT-MODE: a spoken turn survives a restart as spoken.

``runtime.chat.message`` takes ``input_mode`` (``typed`` / ``voice``; argv ``--input-mode``), the turn's
write-ahead record stores it, and the operator's history row carries it (``persona chat history`` rows and
the operator conversation projection). Absent stays absent: a typed send adds no flag and no key.
"""

from __future__ import annotations

import pytest

from agent_runtime.chat_turn import ChatTurnInvalid, normalize_chat_message
from agent_runtime.mission_chat_turns.journal import persist_mission_chat_turn
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.operator_channels import _conversation_history_message
from tests.agent_runtime.test_retry_lineage_projection import SESSION, _operator, _reply, _rows

SEND = {"turn_request_id": "t-1", "persona_id": "neko", "message": "hello"}


def test_the_send_lowers_input_mode_to_its_flag_and_refuses_another_word():
    """Mutation: drop the ``--input-mode`` append in ``normalize_chat_message`` -> red."""
    argv = normalize_chat_message({**SEND, "input_mode": "voice"}).argv
    assert argv[argv.index("--input-mode") + 1] == "voice"
    assert "--input-mode" not in normalize_chat_message(SEND).argv
    with pytest.raises(ChatTurnInvalid) as refused:
        normalize_chat_message({**SEND, "input_mode": "shouted"})
    assert refused.value.reason == "input_mode_invalid"


def test_the_parser_takes_the_flag_the_door_lowers():
    from hermes_cli.harness_parts.persona.chat_serve_route import SEND_FLAGS

    assert ("input_mode", "--input-mode", "value") in SEND_FLAGS


def test_a_voice_turns_history_row_carries_input_mode_voice(isolate_agent_runtime_root):
    """Mutations: drop ``input_mode`` from ``_JOURNAL_TEXT_FIELDS`` (the record loses it) or from the
    curation's operator row -> red."""
    for cmid, mode in (("cm-voice", "voice"), ("cm-typed", None)):
        persist_mission_chat_turn(session_id=SESSION, client_message_id=cmid, turn_id=cmid, elements=[],
                                  state="projected", metadata={"input_mode": mode} if mode else None)
    assert mission_chat_turn_record(session_id=SESSION, client_message_id="cm-voice")["input_mode"] == "voice"
    rows = _rows([_operator("cm-voice", "spoken"), _reply("cm-voice", "heard"),
                  _operator("cm-typed", "typed"), _reply("cm-typed", "read")])
    operators = {row["client_message_id"]: row for row in rows if row["role"] == "operator"}
    assert operators["cm-voice"]["input_mode"] == "voice"
    assert "input_mode" not in operators["cm-typed"]


def test_the_operator_conversation_projection_carries_input_mode():
    """Mutation: drop the carry in ``history_messages._carry_retry_lineage`` -> red."""
    message = _conversation_history_message(
        {"id": "op-cm-voice", "role": "operator", "text": "spoken", "timestamp": "2026-11-03T10:00:00+00:00",
         "redaction_status": "safe", "client_message_id": "cm-voice", "input_mode": "voice"},
        channel_id="chan-1", index=0, persona_id="neko", persona_instance_id="personainst_neko", display_names={})
    assert message is not None and message["input_mode"] == "voice"
