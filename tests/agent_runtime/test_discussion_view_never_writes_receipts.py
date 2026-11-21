"""Opening a busy discussion room reads its turns and writes nothing, so it never queues behind a receipt commit.

RT-FU-A-DISCUSSION-ROOM-VIEW-WRITES-RECEIPTS-AND-TIMES-OUT-UNDER-LOAD (review w1118a.71). Seen 2026-11-21 under
load: ``sqlite3.OperationalError: database is locked`` from ``DiscussionService.view`` -> ``room_state.task_rows``
-> ``executions.row`` -> ``native.recover`` -> ``attempt_store.update`` (``BEGIN IMMEDIATE`` at ``synchronous=FULL``)
while the room's workers committed their own receipts. A view now folds what the turn journal proves in memory
(``recover(record=False)``); the write stays with the worker and the decision paths, which record before they
decide, so a turn whose worker died is still recorded by the next decision.

Killing mutation (run 2026-11-21): ``InstanceExecution._recovered`` passing ``record=True`` (the view writing
again) -> ``test_a_view_of_a_turn_the_journal_settled_answers_terminal_and_writes_nothing`` red (the stored
row is ``terminal``) and ``test_a_view_answers_while_a_receipt_commit_holds_the_write_lock`` red (the view is
still waiting on the lock after 3 s), plus the task-rows test. ``room_state.task_rows`` dropping ``record=False``
-> the task-rows test red. ``NativeTurns.execution_absent`` reading the stored row again instead of recovering it
-> the retry test red (the stored row stays ``running``).
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from agent_runtime.discussions import room_state
from agent_runtime.discussions.attempt_store import AttemptStore
from agent_runtime.discussions.executions import InstanceExecution

pytestmark = pytest.mark.timeout(60)

MEMBER = {"member_id": "m1", "session_id": "s1"}
TASK = {"identity": SimpleNamespace(task_id="task"), "execution_generation": 1}
SETTLED = {"native_committed": True, "auxiliary_result": {"clarify": None}, "stored_reply": "the member's answer"}


class _Journal:
    """The native context's one method recovery reads: what the turn journal recorded for a turn."""

    def __init__(self, record):
        self.record = record

    def journal(self, session_id, native_id):
        return self.record


@pytest.fixture
def room(tmp_path):
    """One attempt claimed by a worker that is gone (another pid), whose turn the journal says settled."""

    from gateway.status import get_process_start_time

    attempts = AttemptStore(tmp_path / "state.db")
    row = attempts.begin("run", "task", 1, MEMBER, "hello")
    # A dead owner: a pid that is not this process, with a start stamp no live process has.
    assert attempts.claim(row, pid=os.getpid(), started=(get_process_start_time(os.getpid()) or 0) + 1)
    execution = InstanceExecution(_Journal(SETTLED), attempts)
    yield SimpleNamespace(attempts=attempts, execution=execution)
    execution.turns.close()


def _stored(room):
    return room.attempts.get("run", "task", 1)


def test_a_view_of_a_turn_the_journal_settled_answers_terminal_and_writes_nothing(room):
    view = room.execution.row("run", TASK, record=False)

    assert (view["stage"], view["receipt"]["status"], view["receipt"]["text"]) == (
        "terminal", "settled", "the member's answer")
    stored = _stored(room)
    assert (stored["stage"], stored["receipt"]) == ("running", None)


def test_a_decision_records_what_the_journal_proved(room):
    """The write a view no longer makes is the next decision's: ``row`` with its default records it."""

    room.execution.row("run", TASK, record=False)
    assert room.execution.row("run", TASK)["stage"] == "terminal"
    assert (_stored(room)["stage"], _stored(room)["receipt"]["status"]) == ("terminal", "settled")


def test_retry_records_a_dead_workers_settled_turn_before_it_judges(room):
    """``retry`` reads the STORED row (``room_commands._attempt``); it records the journal's answer first, so a
    turn that settled before its worker died is recorded settled, never judged on a stale ``running`` row."""

    room.execution.retry(_stored(room))
    assert (_stored(room)["stage"], _stored(room)["receipt"]["status"]) == ("terminal", "settled")


def test_a_view_answers_while_a_receipt_commit_holds_the_write_lock(room):
    """A room worker's FULL commit stalled in its fsync holds the receipts file's write lock exactly like this."""

    held = room.attempts.connect()
    held.execute("BEGIN IMMEDIATE")
    answered: list = []
    viewer = threading.Thread(target=lambda: answered.append(room.execution.row("run", TASK, record=False)),
                              daemon=True)
    try:
        viewer.start()
        viewer.join(timeout=3)
        assert not viewer.is_alive(), "the view queued behind the held receipt write lock"
    finally:
        held.rollback()
        held.close()
        viewer.join(timeout=30)
    assert answered and answered[0]["stage"] == "terminal"


def test_task_rows_reads_each_turn_as_a_view(room, monkeypatch):
    """The room's view (``RoomState.task_rows``) folds the journal and leaves the stored receipt alone."""

    monkeypatch.setattr(room_state.driver, "list_tasks", lambda db_path, room_id: [{
        **TASK, "status": "dispatched",
        "payload": {"target_member_id": "m1", "source_event_seq": 1}}])
    monkeypatch.setattr(room_state.policy, "task_round_index", lambda identity, limits: 0)
    state = room_state.RoomState.__new__(room_state.RoomState)
    state.db_path = None
    state.runs = SimpleNamespace(get=lambda run_id: {"run_id": run_id})
    state.limits = lambda run: None
    state.executions = SimpleNamespace(for_run=lambda run: room.execution)

    rows = state.task_rows("run")

    assert [row["attempt_stage"] for row in rows] == ["terminal"]
    assert _stored(room)["stage"] == "running"
