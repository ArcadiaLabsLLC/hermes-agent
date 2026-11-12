"""A turn the person stopped is closed without the failed-turn notice.

RT-STOPPED-TURN-ALSO-SAYS-NOT-PROCESSED: an operator Stop before the model wrote anything
left the accepted user row as the durable tail, and the core closer
(``agent/conversation_loop.py::_close_durable_failed_turn``) closed it with "Your request was
not processed. Send it again…" — an agent bubble beside the host's own "stopped" settle. The
tail must still be closed (the next prompt would merge into the stopped one), so it is closed
with the hidden interrupt row. An interrupt that names itself (a restart, a run budget, a
correction) keeps the notice: its owner replaces it.

The store, the agent's flush and the closer are the production ones.
"""

from __future__ import annotations

import pytest

from agent.agent_runtime_helpers_placeholders import _INTERRUPTED_PLACEHOLDER
from agent.conversation_loop import _close_durable_failed_turn
from agent.turn_failure_copy import (
    FAILED_TURN_DISPLAY_KIND,
    FAILED_TURN_NOTICE,
    PARTIAL_FAILED_TURN_NOTICE,
)


def _stopped_turn(tmp_path, monkeypatch, result: dict, *, tool_ran: bool = False):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("s", source="test")
    agent = AIAgent(session_db=db, session_id="s", model="test-model", provider="openai-compat", api_key="test",
                    base_url="http://127.0.0.1:1/v1", quiet_mode=True, skip_context_files=True, skip_memory=True)
    messages = [{"role": "user", "content": "please work"}]
    if tool_ran:
        call = {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
        messages += [
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    agent._flush_messages_to_session_db(messages)  # the turn's own flush: the tail is open
    result = {"final_response": None, "completed": False, "messages": messages, **result}
    _close_durable_failed_turn(agent, result)
    _close_durable_failed_turn(agent, result)  # redelivery: the tail is closed, nothing is added
    return db, db.get_messages("s")


@pytest.mark.parametrize("tool_ran", [False, True], ids=["nothing_written", "a_tool_had_run"])
def test_a_turn_the_person_stopped_is_closed_with_no_failed_turn_notice(tmp_path, monkeypatch, tool_ran):
    db, rows = _stopped_turn(tmp_path, monkeypatch, {"interrupted": True}, tool_ran=tool_ran)

    said = [row["content"] for row in rows if row["role"] == "assistant"]
    assert FAILED_TURN_NOTICE not in said and PARTIAL_FAILED_TURN_NOTICE not in said, (
        "a stopped turn was told its request was not processed")
    assert all(row.get("display_kind") != FAILED_TURN_DISPLAY_KIND for row in rows)
    tail = rows[-1]
    assert tail["role"] == "assistant", "the stopped turn's tail was left open for the next prompt to merge into"
    assert tail["display_kind"] == "hidden" and not tail["content"]
    assert tail.get("api_content") == _INTERRUPTED_PLACEHOLDER
    assert len(rows) == (4 if tool_ran else 2), "the closer wrote the boundary twice"
    db.close()


@pytest.mark.parametrize(
    "result",
    [
        {"interrupted": True, "interrupt_message": "Gateway restarting"},
        {"interrupted": True, "interrupt_message": "live run budget exceeded"},
        {"failed": True, "failure_reason": "timeout"},
    ],
    ids=["restart", "run_budget", "provider_failure"],
)
def test_a_turn_that_was_not_stopped_by_the_person_keeps_the_notice(tmp_path, monkeypatch, result):
    db, rows = _stopped_turn(tmp_path, monkeypatch, result)

    assert rows[-1]["content"] == FAILED_TURN_NOTICE
    assert rows[-1]["display_kind"] == FAILED_TURN_DISPLAY_KIND
    db.close()
