"""A long tool call in a serve turn moves to the background past its threshold (RT-LONG-TOOL-CALLS-BACKGROUND).

Fork module: ``tools/long_tool_calls.py``; the arming seam is one guarded line in
``tools/registry.py::ToolRegistry.dispatch``; the running card is ``running_work``'s
``BackgroundToolCallLane``; the verbs are ``runtime.work.background.promote`` and
``runtime.work.cancel``. Design: ``docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md`` §2.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from agent_runtime import live_turns
from tools import fork_completion_events
from tools import interrupt as _interrupt
from tools import long_tool_calls
from tools import process_registry as _pr_mod
from tools.registry import ToolRegistry

TURN = "turn-long-1"
CALL = "call-1"
SESSION_KEY = "persona_chat_long"


class _Agent:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


@pytest.fixture
def queue_registry(monkeypatch, tmp_path):
    reg = _pr_mod.ProcessRegistry()
    reg._completions_restored = True
    monkeypatch.setattr(_pr_mod, "process_registry", reg)
    long_tool_calls.reset_for_tests()
    monkeypatch.setattr(long_tool_calls, "THRESHOLD_S", 0.4)
    monkeypatch.setattr(long_tool_calls, "DECLARED_GRACE_S", 0.1)
    checkpoint = tmp_path / "bg" / long_tool_calls.CHECKPOINT_FILENAME
    monkeypatch.setattr(long_tool_calls, "_routing", lambda kwargs: {
        "session_key": SESSION_KEY, "task_id": str(kwargs.get("task_id") or ""), "owner_task_id": "",
        "parent_session_id": "", "checkpoint": str(checkpoint)})
    yield reg
    long_tool_calls.reset_for_tests()


@pytest.fixture
def tools_reg():
    release = threading.Event()
    reg = ToolRegistry()
    schema = {"name": "slow", "description": "slow", "parameters": {"type": "object", "properties": {}}}

    def slow(args, **kwargs):
        deadline = time.monotonic() + float(args.get("seconds", 5))
        while time.monotonic() < deadline and not release.is_set():
            if _interrupt.is_interrupted():
                return json.dumps({"error": "interrupted"})
            time.sleep(0.02)
        return json.dumps({"answer": args.get("answer", 42)})

    reg.register("slow", "test", schema, slow)
    reg.register("clarify", "test", {**schema, "name": "clarify"}, slow)
    reg.release = release
    yield reg
    release.set()


def _in_live_call(fn, tool="slow"):
    """Run *fn* on a thread the live-turn registry knows as a serve turn's tool thread."""
    out = {}

    def _go():
        live_turns.tool_started(TURN, CALL, tool)
        try:
            out["result"] = fn()
        finally:
            live_turns.tool_finished(TURN, CALL)

    with live_turns.live_turn(turn_id=TURN, session_id="sess", persona_instance_id="pi", agent=_Agent()):
        t = threading.Thread(target=_go)
        t.start()
        t.join(10)
    return out["result"]


def _wait_event(reg, timeout=5.0):
    return reg.completion_queue.get(timeout=timeout)


def test_outside_a_live_serve_turn_the_call_runs_inline(queue_registry, tools_reg):
    assert not long_tool_calls.armed("slow")
    result = tools_reg.dispatch("slow", {"seconds": 0.6})
    assert json.loads(result) == {"answer": 42}
    assert queue_registry.completion_queue.empty()


def test_a_quick_call_in_a_serve_turn_returns_its_own_result(queue_registry, tools_reg):
    result = _in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 0.05, "answer": 7}))
    assert json.loads(result) == {"answer": 7}
    assert queue_registry.completion_queue.empty()


def test_past_the_threshold_the_call_is_promoted_and_its_finish_wakes_the_session(queue_registry, tools_reg, tmp_path):
    result = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 1.2, "answer": 9})))
    assert result["status"] == "running_in_background"
    handle = result["handle"]
    rows = json.loads((tmp_path / "bg" / long_tool_calls.CHECKPOINT_FILENAME).read_text(encoding="utf-8"))
    assert [(r["handle"], r["status"], r["tool_call_id"]) for r in rows] == [(handle, "running", CALL)]

    evt = _wait_event(queue_registry)
    assert evt["type"] == long_tool_calls.EVENT_TYPE and evt["handle"] == handle
    assert evt["session_key"] == SESSION_KEY and evt["outcome"] == "ready"
    text = fork_completion_events.format_fork_completion_event(evt)
    assert text.startswith("[IMPORTANT: Background tool call slow") and '"answer": 9' in text
    rows = json.loads((tmp_path / "bg" / long_tool_calls.CHECKPOINT_FILENAME).read_text(encoding="utf-8"))
    assert rows[0]["status"] == "ready"

    assert fork_completion_events.settle_fork_completion_event(evt) is True
    assert json.loads((tmp_path / "bg" / long_tool_calls.CHECKPOINT_FILENAME).read_text(encoding="utf-8")) == []


def test_a_never_promote_tool_is_not_bracketed(queue_registry, tools_reg):
    result = _in_live_call(lambda: tools_reg.dispatch("clarify", {"seconds": 0.6}), tool="clarify")
    assert json.loads(result) == {"answer": 42}


def test_the_operator_sends_a_call_to_the_background_before_the_threshold(queue_registry, tools_reg, monkeypatch):
    monkeypatch.setattr(long_tool_calls, "THRESHOLD_S", 30.0)
    seen = {}

    def _promote_soon():
        for _ in range(100):
            if long_tool_calls.promotable_handle(TURN, CALL):
                seen["answer"] = long_tool_calls.request_promotion(TURN, CALL)
                return
            time.sleep(0.02)

    threading.Thread(target=_promote_soon).start()
    started = time.monotonic()
    result = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 1.0})))
    assert result["status"] == "running_in_background"
    assert time.monotonic() - started < 5
    assert seen["answer"]["outcome"] == "promote_requested"
    assert _wait_event(queue_registry)["outcome"] == "ready"


def test_promotion_refused_for_an_unknown_call(queue_registry):
    assert long_tool_calls.request_promotion("nope", "nope")["code"] == "not_promotable"


def test_cancel_interrupts_the_worker_and_the_wake_says_cancelled(queue_registry, tools_reg):
    result = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 10})))
    answer = long_tool_calls.cancel(result["handle"])
    assert answer["status"] == "cancel_requested"
    evt = _wait_event(queue_registry)
    assert evt["outcome"] == "cancelled"


def test_an_identical_call_while_one_runs_returns_the_existing_handle(queue_registry, tools_reg):
    first = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 2})))
    second = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 2})))
    assert second["handle"] == first["handle"]
    tools_reg.release.set()
    _wait_event(queue_registry)
    assert queue_registry.completion_queue.empty()


def test_nothing_is_promoted_while_an_approval_prompt_blocks(queue_registry, tools_reg, monkeypatch):
    monkeypatch.setattr(long_tool_calls, "_approval_pending", lambda routing: True)
    result = _in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 0.8}))
    assert json.loads(result) == {"answer": 42}


def test_a_turn_interrupt_reaches_the_worker_while_the_call_is_foreground(queue_registry, tools_reg, monkeypatch):
    monkeypatch.setattr(long_tool_calls, "THRESHOLD_S", 30.0)

    def _stop_soon():
        for _ in range(100):
            if long_tool_calls.promotable_handle(TURN, CALL):
                tid = live_turns._turns[TURN].calls[CALL].tid
                _interrupt.set_interrupt(True, tid)
                return
            time.sleep(0.02)

    threading.Thread(target=_stop_soon).start()
    result = _in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 10}))
    assert json.loads(result) == {"error": "interrupted"}


def test_running_work_shows_the_promoted_call_as_a_cancellable_tool_call(queue_registry, tools_reg, tmp_path, monkeypatch):
    from agent_runtime.running_work import lanes_process

    head = tmp_path / "bg"
    monkeypatch.setattr(lanes_process, "_head_home", lambda: (head, "test_home"))
    monkeypatch.setattr(lanes_process, "_owner_of", lambda session, memo=None: ("", ""))
    result = json.loads(_in_live_call(lambda: tools_reg.dispatch("slow", {"seconds": 3})))
    rows, source = lanes_process._collect_background_tool_calls(now=time.time(), accountant=None)
    assert source["status"] == "ok"
    (row,) = rows
    assert row["kind"] == "tool_call" and row["work_id"] == f"tool_call:{result['handle']}"
    assert row["status"] == "running" and row["cancellable"] is True and row["background"] is True
    tools_reg.release.set()
    _wait_event(queue_registry)
