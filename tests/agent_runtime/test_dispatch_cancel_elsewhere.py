"""D1.07 S1b (owner ruling a) — a dispatch another process supervises is cancelled through the row.

The canceller writes ``cancel_requested``; the supervising process's cancel watch
turns it into its own ``request_cancel`` (the interrupt of the native turn and the
settle the owner's Stop uses). Two processes are modelled in one: "the other process" is a
direct ``request_cancel`` while the dispatch is NOT marked supervised; "the
supervisor" is the worker thread, with the mark set.
"""

from __future__ import annotations

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
from tests.agent_runtime.dispatch_turn_stub import StubTurn, bind_stub_turn
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import cancel_watch, native

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


def _armed() -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    return dispatch_id


def _supervise(dispatch_id, monkeypatch, *, on_stamp=None):
    """Start the supervisor worker on a native turn that runs until interrupted; return (worker, stub)."""

    stub = bind_stub_turn(monkeypatch, StubTurn(block=True))
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    if on_stamp is not None:
        real_stamp = dispatch_store.set_dispatch_owner

        def stamp(*args, **kwargs):
            result = real_stamp(*args, **kwargs)
            on_stamp()
            return result

        monkeypatch.setattr(dispatch_store, "set_dispatch_owner", stamp)
    agent_chat_dispatch._mark_supervised(dispatch_id)
    worker = threading.Thread(
        target=agent_chat_dispatch._run_dispatch,
        args=(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 30,
                            "client_message_id": f"agent-dispatch-{dispatch_id}"}),
        daemon=True,
    )
    worker.start()
    return worker, stub


def _wait_for(predicate, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_running_turn_another_process_supervises_is_requested_not_stopped_here(store_home, monkeypatch):
    dispatch_id = _armed()
    assert set_dispatch_owner(dispatch_id, owner_pid=4242, owner_started_at=777)
    # The supervising process is RUNNING (pid 4242 is a stand-in): a provably-gone one is
    # settled instead (test_running_work's ...whose_process_ended_settles_it_at_once).
    monkeypatch.setattr("gateway.status._pid_exists", lambda pid: True)
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: 777)
    monkeypatch.setattr(native, "interrupt_dispatch_turn", lambda *a: pytest.fail("a non-owner interrupted a turn"))

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")

    assert answer["outcome"] == "cancel_requested"
    assert answer["poll_seconds"] == cancel_watch.CANCEL_POLL_SECONDS
    row = get_dispatch(dispatch_id)
    assert (row["state"], row["cancel_requested"]) == ("running", "operator_stop")


def test_the_supervisors_watch_turns_the_durable_mark_into_its_own_cancel(store_home, monkeypatch):
    """Killing mutation: drop the ``request_cancel`` call in ``poll_cancel_requests``
    → nothing is interrupted and the row stays running."""

    dispatch_id = _armed()
    worker, stub = _supervise(dispatch_id, monkeypatch)
    assert _wait_for(lambda: (get_dispatch(dispatch_id) or {}).get("started_at"))

    assert request_dispatch_cancel(dispatch_id, "operator_stop")  # the other process's write
    assert cancel_watch.poll_cancel_requests() == [dispatch_id]
    assert cancel_watch.poll_cancel_requests() == []  # asked once, not once per pass
    worker.join(5)

    assert stub.interrupted.is_set()
    row = get_dispatch(dispatch_id)
    assert row["state"] == "cancelled"
    assert "operator_stop" in row["result"]["error"]


def test_the_watch_thread_runs_while_something_is_supervised_and_then_exits(store_home, monkeypatch):
    monkeypatch.setattr(cancel_watch, "CANCEL_POLL_SECONDS", 0.02)
    dispatch_id = _armed()
    worker, stub = _supervise(dispatch_id, monkeypatch)
    assert _wait_for(lambda: (get_dispatch(dispatch_id) or {}).get("started_at"))

    cancel_watch.ensure_cancel_watch()
    request_dispatch_cancel(dispatch_id, "operator_stop")
    worker.join(5)

    assert stub.interrupted.is_set()
    assert get_dispatch(dispatch_id)["state"] == "cancelled"
    assert _wait_for(lambda: cancel_watch._thread is None), "the watch outlived the last supervised dispatch"


def test_a_mark_written_while_the_turn_starts_is_caught_after_the_owner_stamp(store_home, monkeypatch):
    dispatch_id = _armed()

    def a_cancel_lands_after_the_queue_check():
        request_dispatch_cancel(dispatch_id, "operator_stop")

    worker, stub = _supervise(dispatch_id, monkeypatch, on_stamp=a_cancel_lands_after_the_queue_check)
    worker.join(5)

    assert stub.interrupted.is_set()
    assert get_dispatch(dispatch_id)["state"] == "cancelled"


def test_a_queued_dispatch_cancelled_elsewhere_runs_nothing_when_its_worker_arrives(store_home, monkeypatch):
    dispatch_id = _armed()
    assert agent_chat_dispatch.request_cancel(dispatch_id)["outcome"] == "cancelled"

    stub = bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "ran anyway"}))
    agent_chat_dispatch._mark_supervised(dispatch_id)
    agent_chat_dispatch._run_dispatch(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 1})

    assert stub.calls == []
    assert get_dispatch(dispatch_id)["state"] == "cancelled"


def test_a_settled_row_takes_no_mark(store_home):
    dispatch_id = _armed()
    dispatch_store.record_completion(dispatch_id, state=dispatch_store.STATE_COMPLETED, reply="kept")

    assert request_dispatch_cancel(dispatch_id, "late") is False
    answer = agent_chat_dispatch.request_cancel(dispatch_id)
    assert answer["outcome"] == "already_finished"
    assert get_dispatch(dispatch_id)["cancel_requested"] == ""
