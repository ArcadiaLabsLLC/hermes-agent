"""RT-SERVE-CHAT-DROPS-THE-PLAN-WRITE: a plan the agent writes in a served chat reaches Eternia.

Seen live 2026-11-14: three ``todo_list`` writes in a Mission Control chat on a serve
produced ``run.tool.finished`` events with NO ``todo_state`` — the progress sink's
allow-list (``progress._SAFE_PROGRESS_KEYS``) had never named it, so the live tool
element and the saved turn carried no plan, nested or flat. The sink now admits it
through the saved-turn bound only (``mission_chat_turns._safe_todo_state``) with secret
values scrubbed; anything not a list is dropped. Pinned through the real chain:
producer -> ``ChatProgressSink`` -> stream emitter element -> saved turn.

KILLING MUTATION: drop ``"todo_state"`` from ``_SAFE_PROGRESS_KEYS`` —
``test_a_nested_plan_write_reaches_the_live_element_and_the_saved_turn`` goes red
(KeyError: the element has no ``todo_state``), all three red. Skipping the value scrub in
``progress._safe_plan`` (``return plan``) reds ``test_only_the_bounded_plan_shape_passes_the_sink``.
"""
from __future__ import annotations

from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import mission_chat_turn_record, persist_mission_chat_turn
from agent_runtime.progress import ChatProgressSink, _safe_progress_payload
from agent_runtime.profile_runner.tool_payloads import _tool_finished_payload
from hermes_cli.harness_parts.persona import chat_events
from tools.todo_tool import TodoStore, todo_tool

SESSION = "persona_chat_personainst_dev_plan_write_000000000001"
TURN = "turn-plan-write-1"
NESTED = [
    {"id": "build", "content": "Build the conversion", "status": "in_progress"},
    {"id": "convert", "content": "Convert saved documents", "status": "pending", "parent": "build"},
    {"id": "ship", "content": "Ship it", "status": "pending"},
]


def _drive_plan_write(todos, event_log):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=False)
    sink = ChatProgressSink(session_id=SESSION, persona_id="dev", turn_id=TURN, event_log=event_log,
                            on_trace=emitter.progress)
    invocation = {"todos": todos}
    sink.emit("run.tool.started", {"tool_name": "todo_list", "tool_call_id": "call_1"})
    finished = _tool_finished_payload("run.tool.finished", "todo_list", duration=0.1, is_error=False,
                                      result=todo_tool(todos, store=TodoStore()), invocation=invocation)
    finished["tool_call_id"] = "call_1"
    sink.emit("run.tool.finished", finished)
    return [element for element in emitter.elements if element.get("kind") == "tool"]


def test_a_nested_plan_write_reaches_the_live_element_and_the_saved_turn(isolate_agent_runtime_root):
    log = EventLog()
    [element] = _drive_plan_write(NESTED, log)
    assert element["todo_state"] == NESTED  # the live stream element, nested

    persist_mission_chat_turn(session_id=SESSION, client_message_id=TURN, turn_id=TURN,
                              elements=[element], state="executing", write_ahead=True,
                              metadata={"root_chat_session_id": SESSION})
    record = mission_chat_turn_record(session_id=SESSION, client_message_id=TURN)
    [saved] = [item for item in record["elements"] if item.get("kind") == "tool"]
    assert saved["todo_state"] == NESTED  # the reloaded turn is the live one

    [trace] = [event for event in log.tail(50) if event.type == "run.tool.finished"]
    assert trace.payload["todo_state"] == NESTED  # the trace row keeps it too


def test_a_cleared_plan_stays_an_explicit_empty_list(isolate_agent_runtime_root):
    [element] = _drive_plan_write([], EventLog())
    assert element["todo_state"] == []


def test_only_the_bounded_plan_shape_passes_the_sink():
    secret = "sk-ant-api03-" + "A" * 40
    safe = _safe_progress_payload("run.tool.finished", {"tool_name": "todo", "todo_state": [
        {"id": "a", "content": f"use {secret} now", "status": "pending", "note": "free form"},
        {"id": "b", "content": "two", "status": "shipping", "parent": "a"},
        {"id": "c", "content": "three", "status": "pending", "parent": "nowhere"},
        "not an item",
    ]})
    assert safe["todo_state"] == [
        {"id": "a", "content": "use [REDACTED] now", "status": "pending"},
        {"id": "b", "content": "two", "status": "pending", "parent": "a"},
        {"id": "c", "content": "three", "status": "pending"},
    ]
    assert secret not in repr(safe)
    for not_a_plan in ("free text", {"todos": NESTED}, 7):
        assert "todo_state" not in _safe_progress_payload("run.tool.finished", {"todo_state": not_a_plan})
