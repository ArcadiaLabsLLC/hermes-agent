"""RT-AGENT-REQUEST-WHOSE-PROCESS-ENDED-STAYS-LISTED-FOR-MORE-THAN-A-SWEEP (review w1118a.55 D11).

Seen 2026-11-19: agent requests stayed in Running now as "unconfirmed" long past the 60 s
orphan sweep. One test per candidate cause, on Linux with the pid and start-time probes
faked where a recycled number is needed:

1. the supervising process still holds the id (the sweep skips it) — it lets go once its
   child exits, even while a survivor in a session of its own holds the child's pipe;
2. the delivery drain was not running the sweep — its loop runs the orphan sweep on its
   first pass and the unanswered-cancel sweep on every pass;
3. the sweep read another store than the projection — under a persona turn's flipped
   ``HERMES_HOME`` the sweep still settles the row the projection lists;
4. the likeliest, read in code: a pid alive again but unprovable (recycled, no baseline)
   keeps the row by design, and Stop only wrote a cancel no supervisor was left to take —
   now a Stop no supervisor takes within its answer window settles the row ``unknown``.

Killing mutations (reds recorded in the commit body):
* ``_run_dispatch`` drops ``_forget_supervised`` from its ``finally`` -> candidate 1 red;
* the drain loop drops ``sweep_orphaned_dispatches()`` -> candidate 2 red;
* ``dispatch_db_path`` resolves the ambient ``get_hermes_home()`` -> candidate 3 red;
* ``settle_if_cancel_unanswered`` drops its ``cancel_seen_at`` check -> the taken-cancel test red;
* ``settle_if_cancel_unanswered`` drops its window comparison -> the inside-the-window test red;
* ``poll_cancel_requests`` drops ``ack_dispatch_cancel`` -> the watch-takes-it test red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from agent_runtime import dispatch_store
from agent_runtime.dispatch_delivery import drain
from agent_runtime.dispatch_store import (
    CANCEL_ANSWER_WINDOW_SECONDS,
    get_dispatch,
    mint_dispatch_id,
    record_dispatch,
    set_dispatch_owner,
    settle_unanswered_cancels,
)
from agent_runtime.running_work.lanes_chat import DispatchLane
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import cancel_watch

pytestmark = pytest.mark.timeout(120)

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    yield home
    for dispatch_id in list(agent_chat_dispatch.supervised_dispatch_ids()):
        agent_chat_dispatch._forget_supervised(dispatch_id)


def _running(owner_pid: int, owner_started_at: int | None) -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    assert set_dispatch_owner(dispatch_id, owner_pid=owner_pid, owner_started_at=owner_started_at)
    return dispatch_id


def _listed(dispatch_id: str) -> bool:
    rows, _source = DispatchLane(now=time.time(), accountant=None).collect()
    # Listed as RUNNING: an ended request stays a while as ended work (RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE).
    return any(row["work_id"].endswith(dispatch_id) and not row.get("finished_at") for row in rows)


def _recycled_and_unprovable(monkeypatch) -> None:
    """The owner pid is alive again and its start time cannot be read: not provably gone."""
    monkeypatch.setattr("gateway.status._pid_exists", lambda pid: True)
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: None)


# 1 ---------------------------------------------------------------------------


@pytest.mark.live_system_guard_bypass  # kills the one survivor this test started
def test_1_the_supervisor_lets_go_once_its_child_exits_though_a_survivor_holds_the_pipe(
    store_home, tmp_path, monkeypatch
):
    pid_file = tmp_path / "pid"
    script = (
        "import subprocess, sys, json\n"
        # A survivor in a session of its own (not the group's), holding the child's stdout.
        "p = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
        "open(sys.argv[1], 'w').write(str(p.pid))\n"
        "print(json.dumps({'capability_id': 'x', 'ok': True, 'reply': 'done'}), flush=True)\n"
    )
    monkeypatch.setattr(
        agent_chat_dispatch.local, "build_dispatch_argv",
        lambda spec, deadline_epoch: [sys.executable, "-c", script, str(pid_file)],
    )
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    agent_chat_dispatch._mark_supervised(dispatch_id)
    try:
        started = time.monotonic()
        agent_chat_dispatch._run_dispatch(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 60})

        assert time.monotonic() - started < 60  # within a sweep
        assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()
        assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_COMPLETED
        assert not _listed(dispatch_id)
    finally:
        try:
            os.kill(int(pid_file.read_text()), 9)  # windows-footgun: ok — POSIX-only stop of this test's survivor
        except (OSError, ValueError):
            pass


# 2 ---------------------------------------------------------------------------


def test_2_the_delivery_drain_runs_both_sweeps(store_home, monkeypatch):
    orphan_swept = threading.Event()
    cancels_swept = threading.Event()
    monkeypatch.setattr(drain, "drain_once", lambda policy=None: None)
    monkeypatch.setattr(drain, "drain_background_completions", lambda policy=None: None)
    monkeypatch.setattr(drain, "sweep_skill_lends", lambda: 0)
    monkeypatch.setattr(drain, "sweep_orphaned_dispatches", lambda: orphan_swept.set() or 0)
    monkeypatch.setattr(drain, "sweep_unanswered_cancels", lambda: cancels_swept.set() or 0)
    stop = threading.Event()
    thread = drain.start_delivery_drain(stop_event=stop, interval_seconds=0.01)
    try:
        assert orphan_swept.wait(10) and cancels_swept.wait(10)
    finally:
        stop.set()
        thread.join(timeout=10)


# 3 ---------------------------------------------------------------------------


def test_3_the_sweep_reads_the_store_the_projection_lists_from(store_home, tmp_path, monkeypatch):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=30)
    dispatch_id = _running(dead.pid, 12345)
    assert _listed(dispatch_id)

    # A persona turn in this process flips the ambient home while it runs.
    turn_home = tmp_path / "persona-turn-home"
    turn_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(turn_home))

    assert drain.sweep_orphaned_dispatches() == 1

    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_UNKNOWN
    assert not _listed(dispatch_id)


# 4 ---------------------------------------------------------------------------


def test_4_a_stop_no_supervisor_takes_settles_the_row_once_its_window_passes(store_home, monkeypatch):
    dispatch_id = _running(424242, None)
    _recycled_and_unprovable(monkeypatch)
    # The sweep keeps it: alive and unprovable is not gone (burying it could bury a live build).
    assert drain.sweep_orphaned_dispatches() == 0
    assert _listed(dispatch_id)

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")
    assert answer["outcome"] == "cancel_requested"
    asked = get_dispatch(dispatch_id)["cancel_requested_at"]

    assert settle_unanswered_cancels(now=asked + CANCEL_ANSWER_WINDOW_SECONDS + 1) == 1

    row = get_dispatch(dispatch_id)
    assert row["state"] == dispatch_store.STATE_UNKNOWN
    assert "no process answered" in row["result"]["error"]
    assert not _listed(dispatch_id)


def test_4_a_stop_inside_its_window_is_left_to_the_supervisor(store_home, monkeypatch):
    dispatch_id = _running(424242, None)
    _recycled_and_unprovable(monkeypatch)
    agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")
    asked = get_dispatch(dispatch_id)["cancel_requested_at"]

    assert settle_unanswered_cancels(now=asked + CANCEL_ANSWER_WINDOW_SECONDS / 2) == 0
    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_RUNNING


def test_4_a_stop_a_supervisor_took_is_never_settled_from_outside(store_home, monkeypatch):
    dispatch_id = _running(424242, None)
    _recycled_and_unprovable(monkeypatch)
    agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")
    asked = get_dispatch(dispatch_id)["cancel_requested_at"]
    assert dispatch_store.ack_dispatch_cancel(dispatch_id)

    assert settle_unanswered_cancels(now=asked + 10 * CANCEL_ANSWER_WINDOW_SECONDS) == 0
    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_RUNNING


def test_4_the_supervisors_watch_takes_the_cancel_before_acting(store_home, monkeypatch):
    dispatch_id = _running(424242, 777)
    dispatch_store.request_dispatch_cancel(dispatch_id, "operator_stop")
    agent_chat_dispatch._mark_supervised(dispatch_id)
    monkeypatch.setattr(agent_chat_dispatch.local, "_kill_child", lambda pid, started: None)
    try:
        assert cancel_watch.poll_cancel_requests() == [dispatch_id]
        assert get_dispatch(dispatch_id)["cancel_seen_at"] is not None
    finally:
        agent_chat_dispatch.local._take_cancel_mark(dispatch_id)


def test_4_the_answer_window_outwaits_several_watch_polls():
    assert CANCEL_ANSWER_WINDOW_SECONDS >= 3 * cancel_watch.CANCEL_POLL_SECONDS


def test_a_store_an_older_build_wrote_is_read_after_adding_the_new_columns(store_home):
    import sqlite3

    dispatch_id = _running(424242, 777)
    path = dispatch_store.dispatch_db_path()
    conn = sqlite3.connect(path)
    for column in ("owner_group", "cancel_requested_at", "cancel_seen_at"):
        conn.execute(f"ALTER TABLE mission_chat_dispatches DROP COLUMN {column}")
    conn.commit()
    conn.close()

    assert [row["dispatch_id"] for row in dispatch_store.running_dispatches()] == [dispatch_id]
    assert json.loads(json.dumps(get_dispatch(dispatch_id)))["owner_group"] is None


def test_a_stop_in_a_process_that_never_dispatched_still_clears_an_ended_request(store_home, monkeypatch):
    """Seen live 2026-11-20 (lane w1118a-hstop): a serve restarted after a request's supervisor
    ended had never loaded the dispatch lane and answered ``not_owned_here``, leaving the row and
    what it started running. Mutation: drop the import in ``surface._cancel_dispatch`` -> red."""
    from agent_runtime.running_work import surface

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=30)
    dispatch_id = _running(dead.pid, 12345)
    real_module = surface._module
    monkeypatch.setattr(
        surface, "_module", lambda name: None if name == "tools.agent_chat_dispatch" else real_module(name)
    )

    result = surface.cancel_work(f"dispatch:{dispatch_id}")

    assert (result["status"], result.get("outcome")) == ("ok", "settled"), result
    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_UNKNOWN
