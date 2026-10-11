"""D1.07 S1b (owner ruling a) — a dispatch another process supervises is cancelled through the row.

The canceller writes ``cancel_requested``; the supervising process's cancel watch
turns it into its own ``request_cancel`` (the identity-guarded kill and settle the
owner's Stop uses). Two processes are modelled in one: "the other process" is a
direct ``request_cancel`` while the dispatch is NOT marked supervised; "the
supervisor" is the worker thread, with the mark set.
"""

from __future__ import annotations

import io
import subprocess
import threading
import time

import pytest

from agent_runtime import dispatch_store
from agent_runtime.dispatch_store import (
    get_dispatch,
    mint_dispatch_id,
    record_dispatch,
    request_dispatch_cancel,
    set_dispatch_owner,
)
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import cancel_watch
import tools.agent_chat_dispatch.local_child  # noqa: F401 - the spawn the tests patch

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


class _BlockingProc:
    def __init__(self):
        self.pid = 4242
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.returncode = -9
        self.release = threading.Event()

    def wait(self, timeout=None):
        if not self.release.wait(timeout=timeout):
            raise subprocess.TimeoutExpired(cmd="child", timeout=timeout or 0)
        return self.returncode


def _armed() -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    return dispatch_id


def _supervise(dispatch_id, monkeypatch, *, on_spawn=None):
    """Start the supervisor worker on a blocking child; return (worker, proc, kills)."""

    proc = _BlockingProc()
    kills: list[tuple[int, int]] = []

    def on_kill(pid, started):
        kills.append((pid, started))
        proc.release.set()

    def spawn(argv, env):
        if on_spawn is not None:
            on_spawn()
        return proc

    monkeypatch.setattr(agent_chat_dispatch.local, "_spawn_child", spawn)
    monkeypatch.setattr(agent_chat_dispatch.local, "_child_identity", lambda pid: 777)
    monkeypatch.setattr(agent_chat_dispatch.local, "_kill_child", on_kill)
    agent_chat_dispatch._mark_supervised(dispatch_id)
    worker = threading.Thread(
        target=agent_chat_dispatch._run_dispatch,
        args=(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 30}),
        daemon=True,
    )
    worker.start()
    return worker, proc, kills


def _wait_for(predicate, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_running_child_another_process_supervises_is_requested_not_killed(store_home, monkeypatch):
    dispatch_id = _armed()
    assert set_dispatch_owner(dispatch_id, owner_pid=4242, owner_started_at=777)
    monkeypatch.setattr(
        agent_chat_dispatch.local, "_kill_child", lambda *a: pytest.fail("a non-owner killed by pid")
    )

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")

    assert answer["outcome"] == "cancel_requested"
    assert answer["poll_seconds"] == cancel_watch.CANCEL_POLL_SECONDS
    row = get_dispatch(dispatch_id)
    assert (row["state"], row["cancel_requested"]) == ("running", "operator_stop")


def test_the_supervisors_watch_turns_the_durable_mark_into_its_own_cancel(store_home, monkeypatch):
    """Killing mutation: drop the ``request_cancel`` call in ``poll_cancel_requests``
    → nothing is killed and the row stays running."""

    dispatch_id = _armed()
    worker, _proc, kills = _supervise(dispatch_id, monkeypatch)
    assert _wait_for(lambda: (get_dispatch(dispatch_id) or {}).get("started_at"))

    assert request_dispatch_cancel(dispatch_id, "operator_stop")  # the other process's write
    assert cancel_watch.poll_cancel_requests() == [dispatch_id]
    assert cancel_watch.poll_cancel_requests() == []  # asked once, not once per pass
    worker.join(5)

    assert kills == [(4242, 777)]
    row = get_dispatch(dispatch_id)
    assert row["state"] == "cancelled"
    assert "operator_stop" in row["result"]["error"]


def test_the_watch_thread_runs_while_something_is_supervised_and_then_exits(store_home, monkeypatch):
    monkeypatch.setattr(cancel_watch, "CANCEL_POLL_SECONDS", 0.02)
    dispatch_id = _armed()
    worker, _proc, kills = _supervise(dispatch_id, monkeypatch)
    assert _wait_for(lambda: (get_dispatch(dispatch_id) or {}).get("started_at"))

    cancel_watch.ensure_cancel_watch()
    request_dispatch_cancel(dispatch_id, "operator_stop")
    worker.join(5)

    assert kills == [(4242, 777)]
    assert get_dispatch(dispatch_id)["state"] == "cancelled"
    assert _wait_for(lambda: cancel_watch._thread is None), "the watch outlived the last supervised dispatch"


def test_a_mark_written_while_the_child_spawns_is_caught_after_the_owner_stamp(store_home, monkeypatch):
    dispatch_id = _armed()

    def a_cancel_lands_after_the_queue_check():
        request_dispatch_cancel(dispatch_id, "operator_stop")

    worker, _, kills = _supervise(dispatch_id, monkeypatch, on_spawn=a_cancel_lands_after_the_queue_check)
    worker.join(5)

    assert kills == [(4242, 777)]
    assert get_dispatch(dispatch_id)["state"] == "cancelled"


def test_a_queued_dispatch_cancelled_elsewhere_runs_nothing_when_its_worker_arrives(store_home, monkeypatch):
    dispatch_id = _armed()
    assert agent_chat_dispatch.request_cancel(dispatch_id)["outcome"] == "cancelled"

    monkeypatch.setattr(
        agent_chat_dispatch.local, "_spawn_child", lambda *a: pytest.fail("a cancelled dispatch spawned")
    )
    agent_chat_dispatch._mark_supervised(dispatch_id)
    agent_chat_dispatch._run_dispatch(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 1})

    assert get_dispatch(dispatch_id)["state"] == "cancelled"


def test_a_settled_row_takes_no_mark(store_home):
    dispatch_id = _armed()
    dispatch_store.record_completion(dispatch_id, state=dispatch_store.STATE_COMPLETED, reply="kept")

    assert request_dispatch_cancel(dispatch_id, "late") is False
    answer = agent_chat_dispatch.request_cancel(dispatch_id)
    assert answer["outcome"] == "already_finished"
    assert get_dispatch(dispatch_id)["cancel_requested"] == ""
