"""Reopening a partial reply preserves its native outcome and public activity."""
from contextlib import closing

from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


def test_partial_reply_keeps_terminal_state_and_journal_after_reopen(tmp_path, monkeypatch):
    home = tmp_path / "home"
    target = fixture(home, monkeypatch, "Amelia")
    key = "partial-reply"
    elements = [dict(kind="segment", id="plan", turn_id=key, seq=1,
                     seg_type="plan", text="Checking the source", state="settled")]
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.append_message(target["session_id"], "assistant", "Partial answer",
                          platform_message_id=f"{key}:assistant:1")
    persist_mission_chat_turn(session_id=target["session_id"], client_message_id=key,
                             turn_id=key, state="interrupted", elements=elements)
    for _ in range(2):
        result = call("read", target)["result"]
        row = next(row for row in result["messages"] if row["text"] == "Partial answer")
        assert row["settled_state"] == "interrupted"
        assert row["turn_elements"][0]["text"] == "Checking the source"
        assert not result["active_turns"]
