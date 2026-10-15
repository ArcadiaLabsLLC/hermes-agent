"""The chat trace is paged by TURN: an earlier settled turn keeps its tool calls past the 40-entry tail.

Live 2026-10-02 (session ``…b3e699ad0c12``): a later turn emitted ~40 trace
entries, the tail kept only those, and the operator conversation of every
earlier turn in the history window had no ``tool_call`` rows after a reopen.
"""

from __future__ import annotations

from datetime import timedelta

from hermes_time import now

from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.models import Event, PersonaInstance
from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.persona_chat_history import persona_chat_trace_summary
from agent_runtime.persona_chat_history.trace_journal import JOURNAL_TRACE_SOURCE
from agent_runtime.states import WorkerSessionState

SESSION = "persona_chat_personainst_dev_test_b3e699ad0c12"


def _instance() -> PersonaInstance:
    return PersonaInstance(
        id="personainst_dev_test",
        persona_id="dev",
        role="dev",
        display_name="Dev",
        profile_id=None,
        runtime_root="runtime",
        state=WorkerSessionState.IDLE,
        updated_at=now(),
        mode="chat",
        session_id=SESSION,
        default_chat_session_id=SESSION,
    )


def _tool_events(log: EventLog, *, turn_id: str, start, names: list[str]) -> None:
    for offset, name in enumerate(names):
        for kind, step in (("run.tool.started", 0), ("run.tool.finished", 1)):
            log.append(
                Event(
                    ts=start + timedelta(seconds=offset * 2 + step),
                    type=kind,
                    task_id=None,
                    run_id=None,
                    persona_id="dev",
                    payload={"tool_name": name, "summary": f"{name} ran", "status": "ok"},
                    session_id=SESSION,
                    turn_id=turn_id,
                )
            )


def _journal(turn_id: str, names: list[str]) -> None:
    elements = [
        {"kind": "tool", "id": f"{turn_id}:t{index}", "turn_id": turn_id, "seq": index,
         "name": name, "status": "ok", "summary": f"{name} ran", "duration_ms": 7}
        for index, name in enumerate(names)
    ]
    persist_mission_chat_turn(
        session_id=SESSION, client_message_id=turn_id, turn_id=turn_id,
        elements=None, state="running", write_ahead=True,
    )
    persist_mission_chat_turn(
        session_id=SESSION, client_message_id=turn_id, turn_id=turn_id,
        elements=elements, state="projected",
    )


def _tool_calls_by_turn(rows: list[dict]) -> dict[str, list[str]]:
    row = rows[0]
    contract = _conversation_contract(
        channel_id="chan", persona_id="dev", persona_instance_id=row["persona_instance_id"],
        session_id=SESSION, task_id=None, goal_id=None, title="t", state="idle",
        history=None, trace=row,
    )
    out: dict[str, list[str]] = {}
    for message in contract["messages"]:
        if message.get("kind") == "tool_call":
            out.setdefault(message.get("turn_id"), []).append(message["tool"]["tool_name"])
    return out


def test_an_earlier_turn_keeps_its_tool_calls_when_a_later_turn_fills_the_tail(isolate_agent_runtime_root):
    log = EventLog()
    start = now() - timedelta(minutes=10)
    early, late = "agent-chat-send-early", "agent-chat-send-late"
    _tool_events(log, turn_id=early, start=start, names=["read_file", "terminal"])
    late_names = [f"tool_{index}" for index in range(25)]  # 50 entries: past the 40 tail
    _tool_events(log, turn_id=late, start=start + timedelta(minutes=2), names=late_names)
    _journal(early, ["read_file", "terminal"])
    _journal(late, late_names)

    rows = persona_chat_trace_summary(persona_instances=[_instance()], event_log=log)
    calls = _tool_calls_by_turn(rows)

    assert calls[early] == ["read_file", "terminal"]
    # The late turn was CUT by the tail, so it is answered whole from its journal.
    assert calls[late] == late_names
    journalled = [entry for entry in rows[0]["entries"] if entry.get("source") == JOURNAL_TRACE_SOURCE]
    assert {entry["turn_id"] for entry in journalled} == {early, late}


def test_a_turn_the_tail_still_covers_is_left_to_the_trace(isolate_agent_runtime_root):
    log = EventLog()
    turn = "agent-chat-send-only"
    _tool_events(log, turn_id=turn, start=now(), names=["read_file"])
    _journal(turn, ["read_file"])

    rows = persona_chat_trace_summary(persona_instances=[_instance()], event_log=log)

    assert [entry.get("source") for entry in rows[0]["entries"]] == [None, None]
    assert _tool_calls_by_turn(rows) == {turn: ["read_file"]}
