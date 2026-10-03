"""One stored Thinking row per emitted ``reasoning.summary`` frame, in emitted order.

The launcher may pair a turn's live Thinking rows with their stored twins by
POSITION only (launcher mission-control-queue "Live Thinking rows"). That is
admissible only if the runtime persists exactly one stored row per live frame,
in the order the frames were emitted. This drives the real chain end to end:

    progress callback -> ChatProgressSink (EventLog append + on_trace)
                      -> _ChatProtocolV2Emitter (the live reasoning.summary frame)
    EventLog -> persona_chat_trace_summary (the raw trace lane)
             -> operator_channel_summary (the conversation's thinking_summary rows)

and compares the frames with both stored projections.

Result (lane h-doors, 2026-10-03): the contract holds for distinct summaries,
and BREAKS in the conversation projection when a summary repeats — the
``thinking_summary`` dedupe (``operator_channels/conversation.py::
_drop_thinking_repeat``) keeps the first occurrence conversation-wide. That
case is pinned below as a strict xfail, so a fix flips it.
"""

from __future__ import annotations

import pytest

from agent_runtime.events import EventLog
from agent_runtime.models import PersonaInstance
from agent_runtime.operator_channels import operator_channel_summary
from agent_runtime.persona_chat_history import persona_chat_trace_summary
from agent_runtime.progress import ChatProgressSink
from agent_runtime.states import WorkerSessionState
from hermes_cli.harness_parts.persona import chat_events

SESSION = "persona_chat_personainst_dev_thinking_order"
TURN = "agent-chat-send-thinking-order"


@pytest.fixture
def frames(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", captured.append)
    return captured


def _thinking(text):
    return {"type": "run.progress", "phase": "thinking_process", "step": "reasoning_summary",
            "status": "running", "summary": "Agent thinking process updated", "reasoning_summary": text}


def _tool(phase, name, call_id):
    payload = {"type": f"run.tool.{phase}", "tool_name": name, "tool_call_id": call_id,
               "status": "started" if phase == "started" else "passed"}
    return payload


def _instance():
    return PersonaInstance(
        id="personainst_dev", persona_id="dev", role="dev", display_name="Dev", profile_id=None,
        runtime_root="test-runtime", state=WorkerSessionState.IDLE, mode="chat", session_id=SESSION,
        updated_at="2026-10-03T00:00:00Z",
    )


def _run_turn(payloads):
    log = EventLog()
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    sink = ChatProgressSink(session_id=SESSION, persona_id="dev", turn_id=TURN, event_log=log,
                            on_trace=emitter.progress)
    callback = sink.callback()
    for payload in payloads:
        callback(payload)
    emitter.finish(state="completed")
    trace = persona_chat_trace_summary(persona_instances=[_instance()], event_log=log)
    channels = operator_channel_summary(persona_instances=[_instance()], persona_chat_history=[],
                                        persona_chat_trace=trace)
    return trace, channels


def _live(frames):
    return [frame["text"] for frame in frames if frame.get("type") == "reasoning.summary"]


def _stored_trace(trace):
    return [entry["reasoning_summary"] for row in trace for entry in row["entries"]
            if entry.get("event") == "progress" and entry.get("reasoning_summary")]


def _stored_conversation(channels):
    return [message["display_text"] for channel in channels for message in channel["conversation"]["messages"]
            if message["kind"] == "thinking_summary" and message.get("turn_id") == TURN]


def test_one_stored_thinking_row_per_frame_in_emitted_order(frames, isolate_agent_runtime_root):
    texts = ["Reading the probe doc first.", "Probe verified; now the echo proof.", "Echo proof passed; reporting."]
    trace, channels = _run_turn([
        _thinking(texts[0]),
        _tool("started", "read_file", "c1"), _tool("finished", "read_file", "c1"),
        _thinking(texts[1]),
        _tool("started", "terminal", "c2"), _tool("finished", "terminal", "c2"),
        _thinking(texts[2]),
    ])
    assert _live(frames) == texts
    assert _stored_trace(trace) == texts
    assert _stored_conversation(channels) == texts


@pytest.mark.xfail(
    strict=True,
    reason="DESIGN (h-doors 2026-10-03): conversation.py::_drop_thinking_repeat keeps only the first "
           "occurrence of a thinking text conversation-wide, so a repeated summary emits two frames "
           "and stores one row; the raw trace lane keeps both",
)
def test_a_repeated_summary_still_stores_one_row_per_frame(frames, isolate_agent_runtime_root):
    texts = ["Checking the runtime.", "Checking the runtime."]
    trace, channels = _run_turn([
        _thinking(texts[0]),
        _tool("started", "terminal", "c1"), _tool("finished", "terminal", "c1"),
        _thinking(texts[1]),
    ])
    assert _live(frames) == texts
    assert _stored_trace(trace) == texts  # holds: the trace lane does not dedupe
    assert _stored_conversation(channels) == texts  # breaks here
