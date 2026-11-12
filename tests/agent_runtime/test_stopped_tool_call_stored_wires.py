"""``RT-STOPPED-TOOL-CALL-STORED-CHAT-SAYS-FAILED``: a tool call you stopped reads Stopped in the stored chat.

Seen live 2026-11-12 (Eternia lane w1112b-turn5, hermes b2d9d99738, pictures 04-06): a ``sleep 170`` step
read "1 stopped" while its reply was live and flipped to "Failed · exit 130 / 1 failed" once the reply
settled, on the next message and after a reload. ``bd0837e231`` put ``outcome: stopped`` on
``run.tool.finished`` and on the stored turn element; the rows the console draws once the stored chat
takes over travel on two other wires — the persona history's trace row (from the event, or from the turn
journal for a turn the event tail no longer covers) and the operator conversation's ``tool_call`` — and
those said ``status: failed`` alone.

Reproduced whole (``held_model_turn``): an operator send whose model calls ``terminal`` with a long
``sleep``, the console's Stop while the command runs, then the stored chat read through the functions the
snapshot reads it with. ``status`` stays ``failed`` for older readers; ``outcome`` is carried, never
derived again (``agent_runtime.serde.tool_outcome_fields`` is the one carry).

Killing mutations (reds recorded in the commit body):
* ``_trace_entry`` drops its ``tool_outcome_fields`` line → the event-row and the conversation asserts red;
* ``_journal_entries`` drops its line → the journal-row assert red;
* ``_merge_tool_detail`` drops its line → the conversation assert red.
"""

from __future__ import annotations

import json
import time

import pytest

from agent_runtime.events import EventLog
from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_history import persona_chat_trace_summary
from agent_runtime.persona_chat_history.trace_journal import JOURNAL_TRACE_SOURCE, page_chat_trace_by_turn
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, operator_call, operator_params, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
STOPPED = "stopped-tool-turn"


def _sleep_call(seconds: int) -> dict:
    return {"role": "assistant", "tool_calls": [{
        "index": 0, "id": "call_1", "type": "function",
        "function": {"name": "terminal", "arguments": json.dumps({"command": f"sleep {seconds}"})}}]}


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model():
    from hermes_constants import get_hermes_home

    held = HeldModel()
    held.hold = False
    held.reply = lambda body: (
        ("The command ended.", "stop") if any(m.get("role") == "tool" for m in body["messages"])
        else (_sleep_call(120), "tool_calls"))
    held.configure(get_hermes_home())
    yield held
    held.close()


def _trace_entries(instance_id: str) -> list[dict]:
    log = EventLog()
    rows = persona_chat_trace_summary(
        persona_instances=[PersonaInstanceStore(event_log=log).get(instance_id)], event_log=log)
    return list(rows[0]["entries"]) if rows else []


def _tool_rows(entries: list[dict], event: str) -> list[dict]:
    return [e for e in entries if e.get("event") == event and e.get("tool_name") == "terminal"]


def test_a_stopped_tool_call_says_stopped_on_the_trace_row_the_journal_row_and_the_conversation(placed_agent, model):
    instance = placed_agent["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    turn = operator_turn(instance, root, STOPPED, "Run the long command.")
    deadline = time.monotonic() + 60
    while not _tool_rows(_trace_entries(instance), "tool_started"):
        assert time.monotonic() < deadline, "the terminal call never started"
        time.sleep(0.2)
    reply = operator_call("stop", operator_params(instance, root, STOPPED, persona=PERSONA, workspace=WORKSPACE),
                          interrupt_operator=turn.interrupt_operator)
    assert reply["result"]["owner_observed"] is True, reply
    turn.join(60)

    # The persona history's trace row, from the run.tool.finished event.
    entries = _trace_entries(instance)
    finished = _tool_rows(entries, "tool_finished")
    assert len(finished) == 1, entries
    assert (finished[0]["status"], finished[0].get("outcome"), finished[0]["exit_code"]) == ("failed", "stopped", 130)
    assert "timed_out" not in finished[0]

    # The same turn once the event tail no longer covers it: the row comes from the turn journal.
    journalled = page_chat_trace_by_turn([], session_id=root, persona_id=PERSONA, cut_turn_ids=set(), tail=40)
    stored = _tool_rows(journalled, "tool_finished")
    assert len(stored) == 1 and stored[0]["source"] == JOURNAL_TRACE_SOURCE, journalled
    assert (stored[0]["status"], stored[0].get("outcome")) == ("failed", "stopped")

    # The operator conversation's tool_call, built from either.
    for name, trace in (("event rows", entries), ("journal rows", journalled)):
        conversation = _conversation_contract(
            channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root,
            goal_id=None, title="Chat", state="idle", history=None, trace={"entries": trace})
        calls = [m for m in conversation["messages"] if m["kind"] == "tool_call"]
        assert len(calls) == 1, f"{name}: {conversation['messages']}"
        assert (calls[0]["status"], calls[0]["tool"]["status"]) == ("failed", "failed"), name
        assert calls[0]["tool"].get("outcome") == "stopped", f"{name}: the tool_call says failed alone"


def test_a_command_that_fails_by_itself_stays_failed_and_a_deadline_says_timed_out():
    """Controls on the carry: the word comes from the finished payload, never from the exit code."""
    from types import SimpleNamespace

    from agent_runtime.operator_channels.trace_messages import _conversation_tool_call_messages
    from agent_runtime.persona_chat_history.trace_rows import _trace_entry

    def row(**payload):
        return _trace_entry(SimpleNamespace(type="run.tool.finished", ts=None, turn_id="t1", payload={
            "tool_name": "terminal", "status": "failed", "exit_code": 130, **payload}))

    own = row(outcome="failed")
    timed = row(outcome="timed_out", timed_out=True)
    legacy = row()
    assert own["outcome"] == "failed" and "timed_out" not in own
    assert (timed["outcome"], timed["timed_out"]) == ("timed_out", True)
    assert "outcome" not in legacy, "a row stored before the field gains no word of its own"
    tools = [m["tool"] for m in _conversation_tool_call_messages(
        [own, timed, legacy], channel_id="c", persona_id="p", persona_instance_id=None)]
    assert [(t.get("outcome"), t.get("timed_out")) for t in tools] == [
        ("failed", None), ("timed_out", True), (None, None)]
