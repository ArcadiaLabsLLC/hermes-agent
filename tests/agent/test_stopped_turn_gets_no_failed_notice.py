"""A turn the person stopped is closed without the failed-turn notice.

RT-STOPPED-TURN-ALSO-SAYS-NOT-PROCESSED: an operator Stop before the model wrote anything
left the accepted user row as the durable tail, and the core closer
(``agent/conversation_loop.py::_close_durable_failed_turn``) closed it with "Your request was
not processed. Send it again…" — an agent bubble beside the host's own "stopped" settle. The
tail must still be closed (the next prompt would merge into the stopped one), so it is closed
with the hidden interrupt row. An interrupt that names itself (a restart, a run budget, a
correction) keeps the notice: its owner replaces it.

The store, the agent's flush and the closer are the production ones.

RT-CONSOLE-STOP-STILL-SAYS-NOT-PROCESSED: the cases above passed while the live console Stop
still wrote the notice, because they called the closer with a result typed by hand. The
console's Stop is ``interrupt_operator_turn`` → ``InterruptScope.cancel("Stopped by the user",
tool_reason=None)`` → a HARD stop that carries those words as the result's
``interrupt_message``, which the first rule read as "an interrupt that names itself". The last
tests run the whole turn (``run_conversation``, real finalizer) and stop it through that seam
while the model call waits.
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


def _run_and_stop(tmp_path, monkeypatch, stop):
    """One real turn whose model call is waiting when ``stop(agent)`` lands; returns (result, rows)."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from agent.interrupt_scope import InterruptScope, bind_interrupt_scope
    from agent_runtime.persona_chat_session import _persona_chat_native_history
    from hermes_cli.harness_parts.serve.operator_interrupt import interrupt_operator_turn
    from hermes_state import SessionDB
    from run_agent import AIAgent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("s", source="test")
    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
    ):
        agent = AIAgent(session_db=db, session_id="s", model="test-model", provider="openai-compat", api_key="test",
                        base_url="http://127.0.0.1:1/v1", quiet_mode=True, skip_context_files=True, skip_memory=True)
    agent._cached_system_prompt = "You are helpful."
    agent.compression_enabled = False
    agent.save_trajectories = False
    scope = InterruptScope()
    serve = SimpleNamespace(
        inflight_lock=__import__("threading").Lock(),
        inflight={"r": SimpleNamespace(turn_request_id="turn-1", interrupt_scope=scope)},
    )

    def _waiting_model_call(*_a, **_k):
        stop(agent, lambda: interrupt_operator_turn(serve, "turn-1"))
        raise InterruptedError("Agent interrupted during API call")  # what the real call raises on the bit

    with (
        bind_interrupt_scope(scope),
        patch.object(agent, "_interruptible_api_call", side_effect=_waiting_model_call),
        patch.object(agent, "_interruptible_streaming_api_call", side_effect=_waiting_model_call),
    ):
        result = agent.run_conversation("please work")
    rows = db.get_messages("s")
    # The NEXT message of the chat, on the stored history: what does the model get to read?
    sent: list[list[dict]] = []

    def _next_model_call(api_kwargs, *_a, **_k):
        sent.append(list(api_kwargs.get("messages") or ()))
        agent.interrupt()
        raise InterruptedError("Agent interrupted during API call")

    with (
        patch.object(agent, "_interruptible_api_call", side_effect=_next_model_call),
        patch.object(agent, "_interruptible_streaming_api_call", side_effect=_next_model_call),
    ):
        agent.run_conversation("something else", conversation_history=_persona_chat_native_history(db, "s"))  # the harness read
    db.close()
    result["next_request"] = sent[0]
    return result, rows


def test_the_consoles_stop_on_a_waiting_model_call_writes_no_failed_turn_notice(tmp_path, monkeypatch):
    result, rows = _run_and_stop(tmp_path, monkeypatch, lambda agent, console_stop: console_stop())

    assert result["interrupted"] is True and result["interrupt_message"] == "Stopped by the user"
    said = [row["content"] for row in rows if row["role"] == "assistant"]
    assert FAILED_TURN_NOTICE not in said and PARTIAL_FAILED_TURN_NOTICE not in said, (
        "the console's Stop still told the person their request was not processed")
    assert [row["role"] for row in rows][-2:] == ["user", "assistant"], "the stopped turn's tail was left open"
    assert rows[-1]["display_kind"] == "hidden"


def test_a_stopped_message_is_not_sent_to_the_model_again_inside_the_next_one(tmp_path, monkeypatch):
    """Live, the stopped message's fixture hold was served a second time on the next turn: the
    display-only notice is stripped before a provider request, so the stopped user row and the
    next one merged into one message. The hidden row stays on the wire as the assistant's
    placeholder, so the two stay apart."""
    result, _rows = _run_and_stop(tmp_path, monkeypatch, lambda agent, console_stop: console_stop())

    last_user = [m for m in result["next_request"] if m.get("role") == "user"][-1]
    assert "something else" in str(last_user["content"]) and "please work" not in str(last_user["content"]), (
        "the stopped message was sent to the model again inside the next one")


def test_a_run_budget_that_ends_a_waiting_model_call_keeps_the_notice(tmp_path, monkeypatch):
    """The harness wall ends the turn through the same interrupt seam, softly and with its own
    words (``profile_runner.execute``): not a person's stop."""
    result, rows = _run_and_stop(
        tmp_path, monkeypatch, lambda agent, _console_stop: agent.interrupt("live run budget exceeded"))

    assert result["interrupted"] is True and result["interrupt_message"] == "live run budget exceeded"
    assert rows[-1]["content"] == FAILED_TURN_NOTICE and rows[-1]["display_kind"] == FAILED_TURN_DISPLAY_KIND
