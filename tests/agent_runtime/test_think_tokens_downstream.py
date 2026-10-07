"""h-think-tokens: a turn's reasoning token count and reasoning time reach the Thinking row.

The chain, each link driven for real:

    stream_gap_receipt (per request)  -> TurnReasoning tally on the agent (per turn)
    runner result ``reasoning_window`` -> persona_runtime stores ONE turn-end event
                                        (ChatProgressSink.record_reasoning_usage)
    trace projection folds it onto the turn's Thinking rows -> the conversation's
    ``thinking_summary`` messages (history replay)
    handler: ``turn.end`` frame, ``chat.final`` and the durable turn record.

Absent usage -> the fields are ABSENT everywhere; a reported zero stays ``0``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.events import EventLog
from agent_runtime.models import PersonaInstance
from agent_runtime.operator_channels import operator_channel_summary
from agent_runtime.persona_chat_history import persona_chat_trace_summary
from agent_runtime.profile_runner import AgentRunResult
from agent_runtime.states import WorkerSessionState
from agent_runtime.stream_gap_receipt import (
    StreamGapReceipt,
    TurnReasoning,
    bind_turn_reasoning,
    observe_stream_event,
)
from tests.agent_runtime.persona_samples import sample_personas

SESSION = "persona_chat_personainst_dev_think_tokens"
TURN = "think-tokens-turn"


# --------------------------------------------------------------------------- #
# 1. The receipt window -> the turn tally                                      #
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _completed(reasoning):
    usage = {"output_tokens": 90}
    if reasoning is not None:
        usage["output_tokens_details"] = {"reasoning_tokens": reasoning}
    return {"type": "response.completed", "response": {"usage": usage}}


def _request(agent, clock, *, reasoning, reply_kind="response.output_text.delta", gap_s=1.5,
             terminal=True):
    """One streamed request: created, reasoning frames, the first reply output, terminal."""

    setattr(agent, "_hermes_stream_gap_receipt", StreamGapReceipt(clock=clock, probe_factory=None))
    observe_stream_event(agent, {"type": "response.created"})
    clock.now += gap_s / 2
    observe_stream_event(agent, {"type": "response.reasoning_summary_text.delta", "delta": "hmm"})
    clock.now += gap_s / 2
    observe_stream_event(agent, {"type": reply_kind, "delta": "Hi"})
    clock.now += 0.25
    if terminal:
        observe_stream_event(agent, _completed(reasoning))


def test_one_request_reports_tokens_and_first_event_to_first_text():
    agent, clock = SimpleNamespace(), _Clock()
    with bind_turn_reasoning(agent) as tally:
        _request(agent, clock, reasoning=42)
    assert tally.fields() == {"reasoning_tokens": 42, "reasoning_ms": 1500}
    assert not hasattr(agent, "_hermes_turn_reasoning")


def test_a_tool_round_and_the_reply_round_are_summed():
    agent, clock = SimpleNamespace(), _Clock()
    with bind_turn_reasoning(agent) as tally:
        _request(agent, clock, reasoning=30, reply_kind="response.function_call_arguments.delta", gap_s=1.0)
        _request(agent, clock, reasoning=12, gap_s=0.5)
    assert tally.fields() == {"reasoning_tokens": 42, "reasoning_ms": 1500}


def test_an_abandoned_attempt_is_not_counted():
    agent, clock = SimpleNamespace(), _Clock()
    with bind_turn_reasoning(agent) as tally:
        _request(agent, clock, reasoning=99, terminal=False)
        _request(agent, clock, reasoning=5, gap_s=0.2)
    assert tally.fields() == {"reasoning_tokens": 5, "reasoning_ms": 200}


def test_no_reported_count_is_absent_and_a_reported_zero_is_zero():
    agent, clock = SimpleNamespace(), _Clock()
    with bind_turn_reasoning(agent) as tally:
        _request(agent, clock, reasoning=None)
    assert tally.fields() == {}
    with bind_turn_reasoning(agent) as tally:
        _request(agent, clock, reasoning=0, gap_s=0.1)
    assert tally.fields() == {"reasoning_tokens": 0, "reasoning_ms": 100}
    assert TurnReasoning().fields() == {}


# --------------------------------------------------------------------------- #
# 2. persona_runtime -> the stored Thinking row -> history replay              #
# --------------------------------------------------------------------------- #
def _thinking(text):
    return {"type": "run.progress", "phase": "thinking_process", "step": "reasoning_summary",
            "status": "running", "summary": "Agent thinking process updated", "reasoning_summary": text}


class _ThinkingRunner:
    """Streams two Thinking summaries through the REAL progress chain, then reports usage."""

    def __init__(self, reasoning_window):
        self.reasoning_window = reasoning_window

    def run(self, request):
        for text in ("Reading the probe doc.", "Probe verified; replying."):
            request.progress_callback(_thinking(text))
        return AgentRunResult(
            final_response="ok", session_id=SESSION, provider="openai-codex", model="gpt-5.5",
            base_url=None, messages=[], reasoning_window=dict(self.reasoning_window),
        )


def _instance():
    return PersonaInstance(
        id="personainst_neko", persona_id="neko_supervisor", role="supervisor", display_name="Dev", profile_id=None,
        runtime_root="test-runtime", state=WorkerSessionState.IDLE, mode="chat", session_id=SESSION,
        updated_at="2026-10-06T00:00:00Z",
    )


def _run_persona_turn(reasoning_window):
    from agent_runtime.persona_runtime import GPTPersonaRuntime

    persona = {p.id: p for p in sample_personas()}["neko_supervisor"]
    runtime = GPTPersonaRuntime(default_provider="openai-codex", default_model="gpt-5.5",
                                agent_runner=_ThinkingRunner(reasoning_window))
    runtime.mission_chat_reply(persona, "hello", permission_session_id=SESSION, turn_id=TURN)
    log = EventLog()
    trace = persona_chat_trace_summary(persona_instances=[_instance()], event_log=log)
    channels = operator_channel_summary(persona_instances=[_instance()], persona_chat_history=[],
                                        persona_chat_trace=trace)
    stored = [entry for row in trace for entry in row["entries"] if entry.get("reasoning_summary")]
    replay = [message for channel in channels for message in channel["conversation"]["messages"]
              if message["kind"] == "thinking_summary"]
    return trace, stored, replay


_COUNTS = ("reasoning_tokens", "reasoning_ms")


def test_the_stored_thinking_rows_and_their_replay_carry_the_turn_counts(isolate_agent_runtime_root):
    trace, stored, replay = _run_persona_turn({"reasoning_tokens": 42, "reasoning_ms": 1500})
    assert [e["reasoning_summary"] for e in stored] == ["Reading the probe doc.", "Probe verified; replying."]
    assert [{k: e.get(k) for k in _COUNTS} for e in stored] == [{"reasoning_tokens": 42, "reasoning_ms": 1500}] * 2
    assert [{k: m.get(k) for k in _COUNTS} for m in replay] == [{"reasoning_tokens": 42, "reasoning_ms": 1500}] * 2
    # The carrier event is folded, never a row of its own.
    entries = [entry for row in trace for entry in row["entries"]]
    assert all(entry.get("reasoning_summary") for entry in entries if "reasoning_tokens" in entry)


def test_a_reported_zero_reaches_the_row_as_zero(isolate_agent_runtime_root):
    _, stored, replay = _run_persona_turn({"reasoning_tokens": 0, "reasoning_ms": 80})
    assert [m.get("reasoning_tokens") for m in replay] == [0, 0]
    assert [e.get("reasoning_ms") for e in stored] == [80, 80]


def test_absent_usage_leaves_the_fields_absent(isolate_agent_runtime_root):
    trace, stored, replay = _run_persona_turn({})
    assert len(stored) == 2 and len(replay) == 2
    for row in stored + replay:
        assert not set(_COUNTS) & set(row)


# --------------------------------------------------------------------------- #
# 3. The handler: turn.end frame, chat.final and the durable turn record       #
# --------------------------------------------------------------------------- #
def _provider(reasoning_window):
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            stream = kwargs.get("stream_callback")
            if stream is not None:
                stream("hello world")
            return SimpleNamespace(final_response="hello world", input_tokens=1, output_tokens=2,
                                   total_tokens=3, latency_ms=4, profile_timing={}, raw={},
                                   reasoning_window=dict(reasoning_window))

    return _Provider


def _drive_handler(monkeypatch, capsys, reasoning_window, turn_id):
    from tests.hermes_cli.test_mission_chat_budget_payload import _seed
    from tests.hermes_cli.test_mission_chat_turn_phases import _args, _record_on_disk
    from hermes_cli.harness_parts.persona import chat_turn_message

    _seed(monkeypatch, _provider(reasoning_window))
    assert chat_turn_message._cmd_mission_chat_message(_args(turn_id, stream=True)) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    frames = {frame.get("type"): frame for frame in lines}
    return frames["turn.end"], frames["chat.final"], _record_on_disk


def test_turn_end_chat_final_and_the_turn_record_carry_the_counts(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    turn_end, final, record_on_disk = _drive_handler(
        monkeypatch, capsys, {"reasoning_tokens": 42, "reasoning_ms": 1500}, "think-tokens-live")
    assert {k: turn_end.get(k) for k in _COUNTS} == {"reasoning_tokens": 42, "reasoning_ms": 1500}
    assert {k: final.get(k) for k in _COUNTS} == {"reasoning_tokens": 42, "reasoning_ms": 1500}
    record = record_on_disk(isolate_agent_runtime_root, "think-tokens-live")
    assert {k: record.get(k) for k in _COUNTS} == {"reasoning_tokens": 42, "reasoning_ms": 1500}


def test_without_usage_the_frames_and_record_carry_no_counts(monkeypatch, capsys, isolate_agent_runtime_root):
    turn_end, final, record_on_disk = _drive_handler(monkeypatch, capsys, {}, "think-tokens-none")
    record = record_on_disk(isolate_agent_runtime_root, "think-tokens-none")
    for row in (turn_end, final, record):
        assert not set(_COUNTS) & set(row)


def test_generic_provider_usage_reports_reasoning_without_fabricating_time():
    from agent_runtime.profile_runner.execute import _run_conversation_with_usage_ledger
    from agent_runtime.usage_ledger import record_usage
    def run(**kwargs):
        record_usage({"reasoning_tokens": 17})
        record_usage({"reasoning_tokens": 24})
        return {}
    result = _run_conversation_with_usage_ledger(SimpleNamespace(run_conversation=run), {})
    assert result["reasoning_tokens"] == 41
    assert result["reasoning_window"] == {"reasoning_tokens": 41}
    assert "reasoning_ms" not in result["reasoning_window"]
