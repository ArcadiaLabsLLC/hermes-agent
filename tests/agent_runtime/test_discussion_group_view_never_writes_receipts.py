"""Opening a busy GROUP discussion room reads its members' turns and writes nothing.

RT-FU-A-GROUP-DISCUSSION-ROOM-VIEW-STILL-WRITES-ITS-TURNS-RECEIPTS (review w1118a.72). The instance room's view stopped
writing receipts in RT-FU-A-DISCUSSION-ROOM-VIEW-WRITES-RECEIPTS-AND-TIMES-OUT-UNDER-LOAD (``record=False``), but a
group room's turns run on ``ProfileTurns``, whose ``recover`` -> ``_project`` still ran ``attempts.update``
(``BEGIN IMMEDIATE``) on every view. ``record`` is now the adapter contract: the base ``SessionExecution._recovered``
passes it to both adapters, and ``ProfileTurns`` folds a view's answer in memory.

Killing mutations (run 2026-11-21):
- ``ProfileTurns._recover`` writing on a view too (drop the ``if not record`` return) ->
  ``test_a_group_room_view_folds_and_never_writes`` red (the stored row is ``terminal``) and
  ``test_a_view_folds_uncertain_on_a_conversation_error_in_memory`` red (stored ``uncertain``).
- ``SessionExecution._recovered`` dropping ``record=record`` -> both of those red the same way.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.discussions.attempt_store import AttemptStore
from agent_runtime.discussions.executions import ProfileExecution

pytestmark = pytest.mark.timeout(60)

MEMBER = {"member_id": "m1", "session_id": "s1", "profile": "member-profile"}
RUN = {"run_id": "run", "initial": {"group": {"actor": "actor", "client": "client"}}}
TASK = {"identity": SimpleNamespace(task_id="task"), "execution_generation": 1}


class _Runs:
    def get(self, run_id):
        return RUN

    def members(self, run_id):
        return [MEMBER]


class _Conversations:
    """The member's conversation as ``observe_execution`` answers it: its turn finished with a reply."""

    def __init__(self):
        self.error = None

    def observe_execution(self, scope, session_id, native_id):
        if self.error is not None:
            raise self.error
        return {"admitted": True, "turn": {"execution_id": "exec-1"},
                "recovery": {"execution": {"id": "exec-1", "status": "complete",
                                           "result": {"text": "the member's answer"}}}}


@pytest.fixture
def room(tmp_path):
    from gateway.status import get_process_start_time

    attempts = AttemptStore(tmp_path / "state.db")
    row = attempts.begin("run", "task", 1, MEMBER, "hello")
    assert attempts.claim(row, pid=os.getpid(), started=get_process_start_time(os.getpid()) or 0)
    conversations = _Conversations()
    execution = ProfileExecution(SimpleNamespace(), attempts, _Runs(), lambda: conversations)
    yield SimpleNamespace(attempts=attempts, execution=execution, conversations=conversations)
    execution.turns.close()


def _stored(room):
    return room.attempts.get("run", "task", 1)


def test_a_group_room_view_folds_and_never_writes(room):
    view = room.execution.row("run", TASK, record=False)

    assert (view["stage"], view["receipt"]["status"], view["receipt"]["text"]) == (
        "terminal", "settled", "the member's answer")
    stored = _stored(room)
    assert (stored["stage"], stored["receipt"]) == ("running", None)


def test_a_view_folds_uncertain_on_a_conversation_error_in_memory(room):
    room.conversations.error = ConversationError(Refusal.UNAVAILABLE)

    assert room.execution.row("run", TASK, record=False)["stage"] == "uncertain"
    assert _stored(room)["stage"] == "running"


def test_a_decision_records_what_the_conversation_proved(room):
    """The write a view no longer makes is the next decision's: ``row`` with its default records it."""

    room.execution.row("run", TASK, record=False)
    assert room.execution.row("run", TASK)["stage"] == "terminal"
    stored = _stored(room)
    assert (stored["stage"], stored["receipt"]["status"], stored["receipt"]["settlement_id"]) == (
        "terminal", "settled", "exec-1")
