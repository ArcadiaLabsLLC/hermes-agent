"""A live turn replayed through the v2 emitter: tool results and reasoning stream.

Replays the trace payloads of the turn at events.81417412 lines 17578-17595
(the operator's own runtime, 2026-10-01) in their recorded order, through the
emitter exactly as ``_stream_progress`` hands them over. Two defects that turn
showed, each pinned against the replay:

* ``tool.finished`` and the stored tool element carried ``tool_result: null``
  although ``run.tool.finished`` carried the result (line 17588) — every MCP
  card read "No input or result detail was emitted";
* ``run.progress`` ``reasoning_summary`` (17579, 17584, 17593) never left as a
  frame, so the console's "Thinking" rows burst in at turn end from the stored
  trace read.
"""

from __future__ import annotations

import pytest

from agent_runtime.mission_chat_turns.records import _safe_elements
from hermes_cli.harness_parts.persona import chat_events

TURN = "agent-chat-send-be095523-7fb2-473b-a96f-2a24a64b6416"

RUNTIME_RESULT = (
    '{"error": "{\\"schema\\":\\"stagec_marionette_command.safe.v1\\",'
    '\\"ok\\":false,\\"failure_class\\":\\"app_not_attached\\",\\"message_safe\\":'
    '\\"Disk discovery found no live Launcher sessions for profile stagec-smoke.\\"}"}'
)
AUTH_RESULT = RUNTIME_RESULT.replace("found no live", "found zero live")
DESCRIBE_INPUT = (
    'names: ["mcp__launcher_qa__mcp_launcher_qa_get_runtime_state", '
    '"mcp__launcher_qa__mcp_launcher_qa_get_auth_state"]'
)
REASONING = (
    "**Planning session state retrieval** I'll check the live Launcher QA runtime "
    "and report whether an attached QA session is present.",
    "I'll check the live Launcher QA runtime and redaction-safe auth state now.",
    "No. The Stage C QA profile (`stagec-smoke`) has no live Launcher session attached.",
)
RUNTIME = "mcp__launcher_qa__mcp_launcher_qa_get_runtime_state"
AUTH = "mcp__launcher_qa__mcp_launcher_qa_get_auth_state"


def _thinking(text):
    return {
        "type": "run.progress",
        "phase": "thinking_process",
        "step": "reasoning_summary",
        "status": "running",
        "summary": "Agent thinking process updated",
        "reasoning_summary": text,
    }


def _tool(kind, name, status, **extra):
    step = "tool_started" if kind == "started" else "tool_finished"
    return {"type": f"run.tool.{kind}", "phase": "tool", "step": step, "status": status, "tool_name": name, **extra}


def _progress_twin(name, step, status, **extra):
    # The ``run.progress`` twin the sink also forwards for every tool step;
    # the emitter must ignore it (it is not the tool lane).
    return {"type": "run.progress", "phase": "tool", "step": step, "status": status, "tool_name": name, **extra}


#: Lines 17579-17593, in recorded order (17578/17594/17595 are the turn's
#: presence/projection events, which never reach the emitter).
REPLAY = (
    _thinking(REASONING[0]),  # 17579
    _progress_twin("tool_describe", "tool_started", "started", tool_input=DESCRIBE_INPUT),  # 17580
    _tool("started", "tool_describe", "started", tool_input=DESCRIBE_INPUT, tool_call_id="call_M4Q"),  # 17581
    _progress_twin("tool_describe", "tool_finished", "passed", duration_ms=381),  # 17582
    _tool("finished", "tool_describe", "passed", outcome="passed", tool_input=DESCRIBE_INPUT, tool_call_id="call_M4Q"),  # 17583
    _thinking(REASONING[1]),  # 17584
    _progress_twin(RUNTIME, "tool_started", "started"),  # 17585
    _tool("started", RUNTIME, "started", tool_call_id="call_GIU"),  # 17586
    _progress_twin(RUNTIME, "tool_finished", "failed", tool_result=RUNTIME_RESULT),  # 17587
    _tool("finished", RUNTIME, "failed", outcome="failed", tool_result=RUNTIME_RESULT, tool_call_id="call_GIU"),  # 17588
    _progress_twin(AUTH, "tool_started", "started"),  # 17589
    _tool("started", AUTH, "started", tool_call_id="call_Xq7"),  # 17590
    _progress_twin(AUTH, "tool_finished", "failed", tool_result=AUTH_RESULT),  # 17591
    _tool("finished", AUTH, "failed", outcome="failed", tool_result=AUTH_RESULT, tool_call_id="call_Xq7"),  # 17592
    _thinking(REASONING[2]),  # 17593
)


@pytest.fixture
def frames(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", captured.append)
    return captured


def _replay(frames):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    for payload in REPLAY:
        emitter.progress(payload)
    emitter.finish(state="completed")
    return emitter


def _of(frames, kind):
    return [frame for frame in frames if frame.get("type") == kind]


# ── tool_result ─────────────────────────────────────────────────────────────


def test_the_finished_frame_carries_the_tool_result(frames):
    _replay(frames)

    by_name = {frame["name"]: frame for frame in _of(frames, "tool.finished")}
    assert by_name[RUNTIME]["tool_result"] == RUNTIME_RESULT
    assert by_name[AUTH]["tool_result"] == AUTH_RESULT
    # Positive control for the null below: the same frame shape, one variable
    # changed (this call's finished payload carried no result), and the field
    # is the honest absence rather than a result borrowed from a neighbour.
    assert by_name["tool_describe"]["tool_result"] is None
    assert by_name["tool_describe"]["tool_input"] == DESCRIBE_INPUT


def test_the_stored_element_keeps_the_tool_result(frames):
    emitter = _replay(frames)

    stored = {element["name"]: element for element in _safe_elements(emitter.elements) if element["kind"] == "tool"}
    assert stored[RUNTIME]["tool_result"] == RUNTIME_RESULT
    assert stored[AUTH]["tool_result"] == AUTH_RESULT
    assert stored["tool_describe"]["tool_result"] is None


def test_an_oversized_result_is_bounded_like_the_store_bounds_it(frames):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    huge = "line\n" * 2000
    emitter.progress(_tool("started", RUNTIME, "started", tool_call_id="c1"))
    emitter.progress(_tool("finished", RUNTIME, "failed", tool_result=huge, tool_call_id="c1"))

    [frame] = _of(frames, "tool.finished")
    assert frame["tool_result"].endswith("…(rest truncated)…")
    assert len(frame["tool_result"]) < 1900
    # Line structure survives (block grade, not the one-line grade).
    assert frame["tool_result"].startswith("line\nline\n")
    # The store re-bounds at the same 1800, so it keeps the frame's bytes as-is.
    [stored] = _safe_elements(emitter.elements)
    assert stored["tool_result"] == frame["tool_result"]


# ── reasoning ───────────────────────────────────────────────────────────────


def test_reasoning_streams_as_it_happens_in_order_with_the_tools(frames):
    _replay(frames)

    order = [
        (frame["type"], frame.get("name") or frame.get("text"))
        for frame in frames
        if frame["type"] in {"reasoning.summary", "tool.started", "tool.finished", "turn.end"}
    ]
    assert order == [
        ("reasoning.summary", REASONING[0]),
        ("tool.started", "tool_describe"),
        ("tool.finished", "tool_describe"),
        ("reasoning.summary", REASONING[1]),
        ("tool.started", RUNTIME),
        ("tool.finished", RUNTIME),
        ("tool.started", AUTH),
        ("tool.finished", AUTH),
        ("reasoning.summary", REASONING[2]),
        ("turn.end", None),
    ]


def test_reasoning_frames_place_themselves_without_taking_an_element_seq(frames):
    emitter = _replay(frames)

    reasoning = _of(frames, "reasoning.summary")
    assert [frame["index"] for frame in reasoning] == [1, 2, 3]
    assert [frame["id"] for frame in reasoning] == [f"{TURN}_reasoning_{n}" for n in (1, 2, 3)]
    # before tool 1; after tool_describe (seq 1); after both MCP calls (seq 3).
    assert [frame["after_seq"] for frame in reasoning] == [0, 1, 3]
    assert all(frame["turn_id"] == TURN and frame["protocol_version"] == 2 for frame in reasoning)
    # Element seqs stay contiguous and no reasoning element is persisted —
    # the durable copy is the trace row.
    assert [element["seq"] for element in emitter.elements] == [1, 2, 3]
    assert {element["kind"] for element in emitter.elements} == {"tool"}


def test_reasoning_does_not_split_a_streaming_answer(frames):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    emitter.delta("No. The Stage C ")
    emitter.progress(_thinking(REASONING[2]))
    emitter.delta("QA profile has no live session.")
    emitter.finish(state="completed")

    assert len(_of(frames, "segment.start")) == 1
    [segment] = emitter.elements
    assert segment["text"] == "No. The Stage C QA profile has no live session."
    # Positive control: a TOOL event at the same point does end the segment,
    # so the single segment above is the reasoning branch's doing.
    frames.clear()
    other = chat_events._ChatProtocolV2Emitter(turn_id="t2", client_message_id="t2", emit_frames=True)
    other.delta("before ")
    other.progress(_tool("started", RUNTIME, "started", tool_call_id="c9"))
    other.delta("after")
    other.finish(state="completed")
    assert len(_of(frames, "segment.start")) == 2


def test_the_thinking_placeholder_and_empty_text_emit_nothing(frames):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    emitter.progress(_thinking("_thinking"))
    emitter.progress(_thinking("   "))
    emitter.progress({key: value for key, value in _thinking("x").items() if key != "reasoning_summary"})
    assert _of(frames, "reasoning.summary") == []
    # Positive control: the same payload shape with real text does emit.
    emitter.progress(_thinking("real text"))
    assert [frame["text"] for frame in _of(frames, "reasoning.summary")] == ["real text"]


def test_reasoning_is_bounded_at_the_trace_rows_limit(frames):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id=TURN, client_message_id=TURN, emit_frames=True)
    emitter.progress(_thinking("word " * 400))
    [frame] = _of(frames, "reasoning.summary")
    assert len(frame["text"]) == 500
