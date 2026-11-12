"""RW1/RW2 — a live chat turn says who and what, and its foreground command is a child row.

Owner screenshot 2026-10-01: Background Work showed
``personainst_dev_agent_8b319ebf · Chat turn · running · 2m 06s · read from the
durable store — no live progress on this lane`` while the turn sat in a silent
foreground ``flutter build windows``. These pin the live half: inside the
process executing the turn, the chat-turn row carries the agent's NAME, the
conversation title, the tool in flight and real progress, and the foreground
command is a ``tool_call`` child row (pid, timeout, output tail) that ``work
peek`` reads and ``work cancel`` stops alone, the turn carrying on.

The foreground command is a REAL one, spawned by ``LocalEnvironment.execute``
on the thread that recorded the tool start — the join under test is the one the
runner makes, not a stub of it.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import ExitStack, contextmanager

import pytest

from agent_runtime import live_turns
from agent_runtime.running_work import (
    KIND_CHAT_TURN,
    KIND_TOOL_CALL,
    STATUS_RUNNING,
    STATUS_STALLING,
    build_running_work,
    cancel_work,
    lanes_chat,
    lanes_process,
    ownership,
    peek_work,
)
from tools import interrupt as _interrupt
from tools.environments import foreground_watch

TURN = "turn-live-1"
SESSION = "persona_chat_personainst_dev_agent_live_000000000001"
INSTANCE = "personainst_dev_agent_live"
MARKER = "RW2-LIVE-MARKER"


@pytest.fixture
def journal(tmp_path, monkeypatch, isolate_agent_runtime_root):
    from agent_runtime.mission_chat_turns import persist_mission_chat_turn

    head = tmp_path / "home"
    head.mkdir()
    for module in (lanes_chat, lanes_process, ownership):
        if hasattr(module, "_head_home"):
            monkeypatch.setattr(module, "_head_home", lambda: (head, "test_home"))
    monkeypatch.setattr(
        "agent_runtime.persona_assignments.persona_instance_display_name",
        lambda handle: "Launcher Dev Agent" if handle == INSTANCE else "",
    )
    monkeypatch.setattr(lanes_chat, "_chat_titles", lambda ids: {SESSION: "Launcher Dev Agent chat"})
    persist_mission_chat_turn(
        session_id=SESSION,
        client_message_id=TURN,
        turn_id=TURN,
        elements=None,
        state="executing",
        write_ahead=True,
        metadata={"persona_instance_id": INSTANCE, "root_chat_session_id": SESSION},
    )


class _Agent:
    def __init__(self) -> None:
        self.interrupts = 0
        self.tool_result: dict = {}
        self.tool_done = threading.Event()

    def get_activity_summary(self) -> dict:
        return {"api_call_count": 3, "seconds_since_activity": 2.0}

    def interrupt(self, *_a, **_k) -> None:
        self.interrupts += 1


@contextmanager
def _build(*, register: bool):
    """A real foreground command on a tool thread that records its call first —
    the order the runner uses (``run.tool.started`` fires on the worker thread
    that then calls ``env.execute``). ``register=False`` is the same command with
    no live turn: the process is not the turn's executor."""

    from tools.environments.local import LocalEnvironment

    agent = _Agent()
    done = agent.tool_done
    command = f"echo {MARKER}; sleep 6"

    def tool_thread() -> None:
        live_turns.tool_started(TURN, "call_build", "terminal", preview=command, command=command, timeout_seconds=30)
        try:
            agent.tool_result = LocalEnvironment().execute(command, timeout=30, bounded_capture=True)
        finally:
            live_turns.tool_finished(TURN, "call_build")
            _interrupt.set_interrupt(False)  # as the tool executor does: idents are reused
            done.set()

    with ExitStack() as stack:
        if register:
            stack.enter_context(
                live_turns.live_turn(turn_id=TURN, session_id=SESSION, persona_instance_id=INSTANCE, agent=agent)
            )
        thread = threading.Thread(target=tool_thread, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            live = foreground_watch.snapshot(owner_tid=thread.ident)
            if live and MARKER in live[0].tail:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"the foreground command never published its output: {foreground_watch.snapshot()}")
        try:
            yield agent
        finally:
            done.wait(30)


def _kind(payload, kind):
    return [row for row in payload["rows"] if row["kind"] == kind]


def test_a_live_turn_reports_name_title_tool_and_foreground_child(journal):
    with _build(register=True):
        payload = build_running_work()

    [turn] = _kind(payload, KIND_CHAT_TURN)
    assert turn["label"] == "Launcher Dev Agent"
    assert turn["owner"]["persona_instance_id"] == INSTANCE
    assert turn["title"] == "Launcher Dev Agent chat"
    assert turn["source_lane"] == "live"
    assert payload["sources"][KIND_CHAT_TURN]["lane"] == "live"
    assert turn["progress"]["source"] == "ok"
    assert turn["progress"]["api_calls"] == 3
    assert turn["progress"]["in_tool"] == "terminal"
    assert turn["status"] == STATUS_RUNNING
    assert turn["current_tool"]["name"] == "terminal"
    assert turn["current_tool"]["timeout_seconds"] == 30
    assert MARKER in turn["current_tool"]["preview"]

    [child] = _kind(payload, KIND_TOOL_CALL)
    assert child["parent_work_id"] == f"chat_turn:{TURN}"
    assert child["work_id"] == f"tool_call:{TURN}:call_build"
    assert isinstance(child["pid"], int) and child["pid_verified"] is True
    assert child["timeout_seconds"] == 30
    assert MARKER in child["tail_preview"]
    assert child["output_chars"] > 0
    assert child["seconds_since_output"] is not None
    assert child["cancellable"] is True
    assert child["owner"] == turn["owner"]


def test_without_the_executing_process_the_row_stays_durable(journal):
    """Positive control on the live join: same journal, same running command, no
    registered turn — the row falls back to the durable answer, with no child."""

    with _build(register=False):
        payload = build_running_work()

    [turn] = _kind(payload, KIND_CHAT_TURN)
    assert turn["source_lane"] == "durable"
    assert turn["progress"]["source"] == "unavailable"
    assert turn["current_tool"] is None
    assert turn["label"] == "Launcher Dev Agent"
    assert _kind(payload, KIND_TOOL_CALL) == []


def test_a_silent_foreground_command_reads_stalling(journal):
    with _build(register=True):
        foreground_watch.snapshot()  # observe the current output count first
        with foreground_watch._lock:  # age the observed silence
            for entry in foreground_watch._entries.values():
                entry.last_output_mono -= 700.0
        payload = build_running_work()

    [turn] = _kind(payload, KIND_CHAT_TURN)
    [child] = _kind(payload, KIND_TOOL_CALL)
    # The in-tool stale threshold is the delegation monitor's (1200 s); 700 s of
    # silence is past half of it — and the agent's own 2 s activity stamp, which
    # the terminal wait keeps fresh, must NOT mask it.
    assert child["status"] == STATUS_STALLING
    assert turn["status"] == STATUS_STALLING
    assert turn["progress"]["seconds_since_progress"] >= 700


def test_peek_reads_the_foreground_tail_and_cancel_stops_the_command_not_the_turn(journal):
    """RT-STOP-TOOL-CALL-ENDS-WHOLE-TURN: Stop on a tool call kills that command; the turn is not interrupted."""
    work_id = f"tool_call:{TURN}:call_build"
    with _build(register=True) as agent:
        peek = peek_work(work_id)
        cancelled_at = time.monotonic()
        cancel = cancel_work(work_id)
        # The real command (``sleep 6``) is killed by its own wait loop, well before it would end.
        assert agent.tool_done.wait(4), "the foreground command outlived its Stop"
        stopped_after = time.monotonic() - cancelled_at
        # Still inside the live turn: the turn's own row is there, with no child left.
        after = build_running_work()

    assert peek["found"] is True
    assert peek["tail_available"] is True
    assert MARKER in peek["tail"]
    assert cancel == {
        "status": "cancelled",
        "code": "",
        "work_id": work_id,
        "kind": KIND_TOOL_CALL,
        "stopped": KIND_TOOL_CALL,
        "turn_continues": True,
        "parent_work_id": f"chat_turn:{TURN}",
    }
    assert agent.interrupts == 0
    assert stopped_after < 4
    assert agent.tool_result["returncode"] == 130
    assert "[Command interrupted]" in agent.tool_result["output"]
    assert [row["work_id"] for row in _kind(after, KIND_CHAT_TURN)] == [f"chat_turn:{TURN}"]
    assert _kind(after, KIND_TOOL_CALL) == []


def test_stopping_a_tool_call_this_process_does_not_run_says_so(journal):
    assert live_turns.interrupt_tool_call(TURN, "call_build", reason="operator_cancel") is False
    with live_turns.live_turn(turn_id=TURN, session_id=SESSION, persona_instance_id=INSTANCE, agent=_Agent()):
        assert live_turns.interrupt_tool_call(TURN, "call_gone", reason="operator_cancel") is False


def test_titles_are_read_only_from_the_chat_sessiondb(tmp_path):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
    conn.executemany("INSERT INTO sessions VALUES (?, ?)", [("a", "Build chat"), ("b", None)])
    conn.commit()
    conn.close()

    assert lanes_chat._titles_in(db, ["a", "b", "c"]) == {"a": "Build chat"}
    # Never creates the store it reads.
    assert lanes_chat._titles_in(tmp_path / "absent.db", ["a"]) == {}
    assert not (tmp_path / "absent.db").exists()
