"""``RT-LATE-STEER-CARRIES-THE-ENDED-TURNS-TIME-NOTICE``: the next turn is sent what the operator typed, not
the ended turn's own "time is nearly up" notice.

Seen live 2026-11-12 (lane w1112b-hm-latesteer, QA fixture): a steer typed at a wave lane's held turn ran next
with the harness's whole "[harness] Wall budget nearly exhausted — … Produce your FINAL checkpoint reply NOW"
paragraph after it, drawn inside the operator's own bubble. The turn's last model call spanned its wall
checkpoint; the checkpoint's nudge is steered into the agent (``WallBudgetCheckpoint.engage``) and, with no
tool round left to carry it, was handed back beside the steer — and ``queue_leftover_steer`` queued the newline
join of everything handed back.

Whole turns (``held_model_turn``): a Work turn on a 62 s budget, held in its one model call until its
checkpoint has opened (the working floor is lowered so that is two seconds in, nothing else is changed), ends;
the root's send queue is then read.

Killing mutation (run, seen red, restored — recorded in the commit body):
* ``_next_turn_text`` returns ``str(pending)`` → both tests red (the notice rides the steer; a turn made of
  the notice alone is queued).
"""

from __future__ import annotations

import threading

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, paths, turn_budget
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.profile_runner.budget import WallBudgetCheckpoint
from agent_runtime.work_store.persona_turn import _turn_args
from tests.agent_runtime.held_model_turn import Running
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # fixtures
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures: a chat, a held model

pytestmark = pytest.mark.timeout(180)

WORK_TURN = "work-BATCH-Q44PM7:L1"
STEER_ID = "agent-chat-send-cadc7833"
NOTICE = "Wall budget nearly exhausted"


@pytest.fixture
def checkpoint_opened(monkeypatch) -> threading.Event:
    """Set once the turn's wall checkpoint has engaged and steered its nudge into the agent."""

    monkeypatch.setattr(turn_budget, "CHECKPOINT_MIN_WORKING_SECONDS", 2.0)
    opened = threading.Event()
    engage = WallBudgetCheckpoint.engage

    def _engage(self, *, trigger: str) -> bool:
        did = engage(self, trigger=trigger)
        opened.set()
        return did

    monkeypatch.setattr(WallBudgetCheckpoint, "engage", _engage)
    return opened


def _a_work_turn_held_across_its_checkpoint(chat, model, checkpoint_opened) -> tuple[str, Running]:
    instance, root = chat
    args = _turn_args(PersonaInstanceStore().get(instance), root, WORK_TURN, "Tidy the meadow.",
                      "work:BATCH-Q44PM7:L1", max_seconds=62.0)
    entry, _position, _replay = send_queue.enqueue(root, WORK_TURN, send_queue.persistable_args(args))
    turn = Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))
    assert model.entered.wait(60), "the Work turn never reached the model"
    assert checkpoint_opened.wait(30), "the turn's wall checkpoint never opened"
    return root, turn


def test_a_late_steer_is_queued_without_the_ended_turns_checkpoint_notice(chat, model, checkpoint_opened):
    root, turn = _a_work_turn_held_across_its_checkpoint(chat, model, checkpoint_opened)
    ack = submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root,
                                    message="also water the roses", client_message_id=STEER_ID, timeout_seconds=20)
    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.hold = False
    model.release.set()
    turn.join(60)

    late = send_queue.find(root, "steer-next-" + STEER_ID)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    assert late.args["message"] == "also water the roses"
    assert late.args["steer_of"] == [STEER_ID]


def test_a_turn_that_ends_holding_only_its_own_notice_queues_no_next_turn(chat, model, checkpoint_opened):
    root, turn = _a_work_turn_held_across_its_checkpoint(chat, model, checkpoint_opened)
    model.hold = False
    model.release.set()
    turn.join(60)

    assert [(e.client_message_id, e.args["message"]) for e in send_queue.entries(root)] == []
