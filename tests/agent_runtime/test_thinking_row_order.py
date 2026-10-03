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

Result (lane h-doors, 2026-10-03): the positional contract holds for distinct
summaries and BREAKS when a summary repeats (the conversation's
``_drop_thinking_repeat`` dedupe), when a secret filter drops a row, or when a
cap trims one. Owner ruling the same day: pair by a stable id, not position.
So every summary carries ``reasoning_id`` (``<turn_id>_reasoning_<n>``), minted
by ``ChatProgressSink`` on the one dict that is both forwarded as the live frame
and appended as the stored row; the tests below pin that drops leave GAPS and
never re-number a surviving row (lane h-thinkid).
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


def _id(n):
    return f"{TURN}_reasoning_{n}"


def _live_ids(frames):
    return [(frame["text"], frame["reasoning_id"], frame["id"]) for frame in frames
            if frame.get("type") == "reasoning.summary"]


def _stored_trace_ids(trace):
    return [(entry["reasoning_summary"], entry["reasoning_id"]) for row in trace for entry in row["entries"]
            if entry.get("event") == "progress" and entry.get("reasoning_summary")]


def _stored_conversation_ids(channels):
    return [(message["display_text"], message.get("reasoning_id")) for channel in channels
            for message in channel["conversation"]["messages"]
            if message["kind"] == "thinking_summary" and message.get("turn_id") == TURN]


def _turn_with(texts):
    payloads = []
    for n, text in enumerate(texts, start=1):
        payloads.append(_thinking(text))
        payloads += [_tool("started", "terminal", f"c{n}"), _tool("finished", "terminal", f"c{n}")]
    return _run_turn(payloads)


def test_the_live_frame_id_is_the_stored_row_id(frames, isolate_agent_runtime_root):
    texts = ["Reading the probe doc first.", "Probe verified; now the echo proof.", "Echo proof passed; reporting."]
    trace, channels = _turn_with(texts)
    expected = [(text, _id(n)) for n, text in enumerate(texts, start=1)]
    assert _live_ids(frames) == [(text, rid, rid) for text, rid in expected]
    assert _stored_trace_ids(trace) == expected
    assert _stored_conversation_ids(channels) == expected
    assert channels[0]["conversation"]["schema_version"] == 3


def test_a_dropped_repeat_leaves_a_gap_not_a_shift(frames, isolate_agent_runtime_root):
    trace, channels = _turn_with(["Checking the runtime.", "Checking the runtime.", "Runtime is healthy."])
    assert [rid for _, rid, _ in _live_ids(frames)] == [_id(1), _id(2), _id(3)]
    # The raw trace lane keeps both repeats; the conversation dedupe drops the
    # second, and the survivor after it keeps id 3.
    assert [rid for _, rid in _stored_trace_ids(trace)] == [_id(1), _id(2), _id(3)]
    assert _stored_conversation_ids(channels) == [
        ("Checking the runtime.", _id(1)), ("Runtime is healthy.", _id(3)),
    ]


def test_positive_control_distinct_text_persists_every_row(frames, isolate_agent_runtime_root):
    # The same three frames with the second one's text changed: nothing is a
    # repeat, so all three rows persist — proving the gap above is the dedupe's.
    _, channels = _turn_with(["Checking the runtime.", "Checking the runtime again.", "Runtime is healthy."])
    assert [rid for _, rid in _stored_conversation_ids(channels)] == [_id(1), _id(2), _id(3)]


SECRET = "Rotating the api-key: abc123 next"
BENIGN = "Rotating the api key next"


@pytest.mark.parametrize(("middle", "stored"), [(SECRET, [1, 3]), (BENIGN, [1, 2, 3])],
                         ids=["filtered", "positive-control"])
def test_a_filtered_row_keeps_the_other_rows_ids(frames, isolate_agent_runtime_root, middle, stored):
    # The sink admits SECRET (a frame is emitted) and the trace projection's
    # secret filter drops its stored row; BENIGN is the same bytes minus the
    # assignment shape, and must persist.
    trace, channels = _turn_with(["Opening the vault config.", middle, "Vault rotated."])
    assert [rid for _, rid, _ in _live_ids(frames)] == [_id(1), _id(2), _id(3)]
    assert [rid for _, rid in _stored_trace_ids(trace)] == [_id(n) for n in stored]
    assert [rid for _, rid in _stored_conversation_ids(channels)] == [_id(n) for n in stored]
