"""A turn's tool-call step is not its reply.

Reproduces the 2026-10-02 18:52Z QA turn (archive events.81417412 lines
18083-18100, SessionDB rows 3950-3956): user row, assistant ``tool_calls`` rows,
tool rows, and no final assistant row -- the executor died after the last tool
result. A resend of the same id read the last ``tool_calls`` row as the turn's
reply, settled the journal ``projected`` with ``stored_reply: ""`` and the
operator got silence.
"""

from __future__ import annotations

import json

from hermes_state import SessionDB
from hermes_cli.harness_parts.persona.chat_history_writes import _persona_chat_existing_turn

_SESSION = "persona_chat_personainst_dev_agent_test"
_CMID = "agent-chat-send-b9477f43-dd5f-442d-b270-f7d7ba97f6a5"
_TOOL = "mcp__launcher_qa__mcp_launcher_qa_open_app_tab"


def _tool_call(call_id: str) -> list[dict]:
    return [{"id": call_id, "type": "function", "function": {"name": "tool_call", "arguments": json.dumps({"calls": [{"name": _TOOL, "arguments": {"tab": "news"}}]})}}]


def _evidence_turn(db: SessionDB) -> None:
    db.create_session(_SESSION, source="cli")
    db.append_message(_SESSION, "user", content="screnshot news", platform_message_id=_CMID)
    db.append_message(_SESSION, "assistant", tool_calls=_tool_call("call_1"), finish_reason="tool_calls",
                      platform_message_id=f"{_CMID}:assistant:3")
    db.append_message(_SESSION, "tool", content='{"error": "tool_call takes exactly one entry"}', tool_name="tool_call",
                      tool_call_id="call_1", platform_message_id=f"{_CMID}:tool:4")
    db.append_message(_SESSION, "assistant", tool_calls=_tool_call("call_2"), finish_reason="tool_calls",
                      platform_message_id=f"{_CMID}:assistant:5")
    db.append_message(_SESSION, "tool", content='{"error": "auth_required"}', tool_name=_TOOL,
                      tool_call_id="call_2", platform_message_id=f"{_CMID}:tool:6")


def test_a_turn_that_ended_on_a_tool_result_has_no_reply(tmp_path):
    with SessionDB(db_path=tmp_path / "state.db") as db:
        _evidence_turn(db)
        found = _persona_chat_existing_turn(session_db=db, session_id=_SESSION, client_message_id=_CMID)

    assert found["operator"]["content"] == "screnshot news"
    assert "assistant" not in found


def test_the_final_answer_after_the_tool_steps_is_the_reply(tmp_path):
    """Positive control: the same turn, finished. The reply is found, and it is
    the final row, not a tool-call step."""

    with SessionDB(db_path=tmp_path / "state.db") as db:
        _evidence_turn(db)
        db.append_message(_SESSION, "assistant", content="News is behind sign-in; run dev_login first.",
                          finish_reason="stop", platform_message_id=f"{_CMID}:assistant:7")
        found = _persona_chat_existing_turn(session_db=db, session_id=_SESSION, client_message_id=_CMID)

    assert found["assistant"]["content"] == "News is behind sign-in; run dev_login first."
