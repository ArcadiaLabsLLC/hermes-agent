"""Real turn setup retains its state and durable ordering while laps stay bounded.

Positive control: remove the upstream MCP boundary; the real-build partition fails.
Killing mutation: finish failed builds as completed; unfinished-work guard fails.
"""
from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

import pytest

from agent import turn_context
from agent.agent_runtime_helpers import note_turn_persisted
from agent_runtime import turn_context_timing as timing
from tests.agent.test_turn_context import _FakeAgent, _build


@pytest.fixture
def receipt_probe(monkeypatch):
    now = [0]
    lines = []
    monkeypatch.setattr(timing, "perf_counter_ns", lambda: now[0])
    monkeypatch.setattr(timing.logger, "info", lambda fmt, *args: lines.append(fmt % args))
    monkeypatch.setattr("agent.auxiliary_client.set_runtime_main", lambda *a, **k: None)
    monkeypatch.setattr("agent.agent_runtime_helpers._INFLIGHT_TURNS_BY_SESSION", {})
    return now, lines


def fields(line):
    return dict(re.findall(r"(\w+)=([^\s]+)", line))


def test_one_receipt_partitions_real_build_without_changing_state(receipt_probe, monkeypatch):
    now, lines = receipt_probe
    original_refresh = turn_context._refresh_mcp_tools_between_turns
    original_persist = turn_context._persist_turn_start
    order = []

    def refresh(agent):
        original_refresh(agent)
        now[0] += 7_000_000
        order.append("refresh")

    def persist(*args):
        now[0] += 11_000_000
        original_persist(*args)
        order.append("persist")

    monkeypatch.setattr(turn_context, "_refresh_mcp_tools_between_turns", refresh)
    monkeypatch.setattr(turn_context, "_persist_turn_start", persist)
    agent = _FakeAgent()
    agent._persona_chat_turn_id = "agent-chat-send-first"
    agent.status_callback = lambda *_args: pytest.fail("lap must not invoke status callback")
    history = [{"role": "user", "content": "prior"}, {"role": "assistant", "content": "answer"}]
    result = _build(agent, conversation_history=history, persist_user_timestamp=101.125)
    assert len(lines) == 1
    parsed = fields(lines[0])
    expected = {f"{part}_ms": "0" for part in timing.TURN_CONTEXT_PARTS}
    expected.update(mcp_refresh_ms="7", persist_ms="11")
    assert {key: parsed[key] for key in expected} == expected
    assert parsed["turn"] == agent._persona_chat_turn_id
    assert parsed["status"] == "completed"
    assert int(parsed["total_ms"]) == sum(int(parsed[key]) for key in expected) == 18
    assert parsed["unfinished_ms"] == "0"
    assert order == ["refresh", "persist"]
    assert result.messages == history + [{"role": "user", "content": "hello", "timestamp": 101.125}]
    assert history == [{"role": "user", "content": "prior"}, {"role": "assistant", "content": "answer"}]
    assert result.active_system_prompt == agent._cached_system_prompt == "SYSTEM"
    assert agent._persist_calls == 1
    assert timing._ACTIVE_LAPS.get() is None


def test_failed_real_build_reports_only_closed_parts_and_preserves_exception(receipt_probe, monkeypatch):
    now, lines = receipt_probe
    error = RuntimeError("compaction failed")

    def fail(*args, **kwargs):
        now[0] += 13_000_000
        raise error

    monkeypatch.setattr("agent.turn_context_compaction.run_turn_start_compaction", fail)
    agent = _FakeAgent()
    agent._persona_chat_turn_id = "agent-chat-send-failed"
    with pytest.raises(RuntimeError) as raised:
        _build(agent)
    assert raised.value is error
    parsed = fields(lines[0])
    assert parsed["status"] == "failed"
    assert parsed["unfinished_ms"] == parsed["total_ms"] == "13"
    assert "compaction_ms" not in parsed and "persist_ms" not in parsed and "return_ms" not in parsed
    assert agent._persist_calls == 0
    assert timing._ACTIVE_LAPS.get() is None


def test_cached_agent_turn_ids_and_parts_do_not_leak(receipt_probe):
    _, lines = receipt_probe
    agent = _FakeAgent()
    for turn in ("agent-chat-send-a", "agent-chat-send-b"):
        agent._persona_chat_turn_id = turn
        _build(agent)
        note_turn_persisted(agent)
    assert [fields(line)["turn"] for line in lines] == ["agent-chat-send-a", "agent-chat-send-b"]
    assert all(fields(line)["mcp_refresh_ms"] == "0" for line in lines)
    assert agent._persist_calls == 2


def test_logging_failure_cannot_change_real_return_or_durable_persist(receipt_probe, monkeypatch):
    def broken(*args):
        raise OSError("log unavailable")

    monkeypatch.setattr(timing.logger, "info", broken)
    agent = _FakeAgent()
    agent._persona_chat_turn_id = "agent-chat-send-log-failed"
    assert _build(agent).active_system_prompt == "SYSTEM"
    assert agent._persist_calls == 1
    assert timing._ACTIVE_LAPS.get() is None


def test_clock_failure_is_not_a_zero_duration_receipt(receipt_probe, monkeypatch):
    _, lines = receipt_probe

    def broken():
        raise OSError("clock unavailable")

    monkeypatch.setattr(timing, "perf_counter_ns", broken)
    agent = _FakeAgent()
    agent._persona_chat_turn_id = "agent-chat-send-clock-failed"
    assert _build(agent).active_system_prompt == "SYSTEM"
    assert agent._persist_calls == 1 and lines == []


@pytest.mark.parametrize("turn_id", [None, "unsafe prompt\nvalue", "x" * 161])
def test_untraced_or_invalid_identity_calls_failing_body_exactly_once(receipt_probe, turn_id):
    _, lines = receipt_probe
    calls = []
    error = RuntimeError("original")

    @timing.trace_turn_context
    def body(agent):
        calls.append(agent)
        raise error

    agent = SimpleNamespace(_persona_chat_turn_id=turn_id)
    with pytest.raises(RuntimeError) as raised:
        body(agent)
    assert raised.value is error
    assert calls == [agent] and lines == []


@pytest.mark.parametrize("child_is_traced", [True, False])
def test_nested_build_restores_parent_partition_and_signature(receipt_probe, child_is_traced):
    now, lines = receipt_probe

    @timing.trace_turn_context
    def child(agent):
        now[0] += 3_000_000
        timing.note_turn_context_part("hooks")
        return agent

    @timing.trace_turn_context
    def parent(agent, *, flag=True):
        now[0] += 2_000_000
        timing.note_turn_context_part("runtime_restore")
        child(SimpleNamespace(_persona_chat_turn_id="agent-chat-send-child" if child_is_traced else None))
        now[0] += 5_000_000
        timing.note_turn_context_part("hooks")
        return flag

    assert inspect.signature(parent) == inspect.signature(parent.__wrapped__)
    assert parent(SimpleNamespace(_persona_chat_turn_id="agent-chat-send-parent")) is True
    assert len(lines) == (2 if child_is_traced else 1)
    if child_is_traced:
        assert fields(lines[0])["hooks_ms"] == "3"
    parent_fields = fields(lines[-1])
    assert parent_fields["runtime_restore_ms"] == "2" and parent_fields["hooks_ms"] == "8"
    assert parent_fields["total_ms"] == "10"
    assert timing._ACTIVE_LAPS.get() is None


def test_unknown_duplicate_and_post_finish_laps_are_bounded(receipt_probe):
    now, lines = receipt_probe
    laps = timing.TurnContextLaps("agent-chat-send-bounded")
    now[0] = 1_600_000
    laps.lap("hooks")
    laps.lap("user supplied field")
    now[0] = 2_200_000
    laps.lap("hooks")
    laps.finish(True)
    laps.lap("persist")
    laps.finish(True)
    parsed = fields(lines[0])
    assert len(lines) == 1
    assert parsed["hooks_ms"] == "1" and parsed["return_ms"] == "1"
    assert parsed["total_ms"] == "2" and "persist_ms" not in parsed
