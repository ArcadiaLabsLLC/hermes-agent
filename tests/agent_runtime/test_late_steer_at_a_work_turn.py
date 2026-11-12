"""``RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT``: what a late steer at a Work turn runs as TODAY.

A steer typed at a running Work turn that arrives after the turn's last tool round runs as the chat root's
next turn, ``steer-next-<id>``. That turn is queued from a copy of the Work turn's own send
(``leftover_steer.queue_leftover_steer`` / ``_requeue_from_ledger`` over ``persistable_args``), so it is, in
every field but the message and its ids, another turn OF THE WORK REQUEST — though a person typed it.

This file STATES that behaviour; it does not bless it. The row is a ``DECISION`` for the owner (should the
late message count as part of the task, or be an ordinary chat message?). Whichever is ruled, the lane that
builds it changes the assertions marked ``TODAY`` and nothing else here.

Whole turns (``held_model_turn``), as ``test_steer_next_turn_names_its_steer`` drives them: a Work turn queued
the way ``PersonaTurnExecutor.start_from`` queues it (requester, budget and the ``work`` origin), held in its
one model call, takes a steer through ``submit_mission_chat_steer`` and ends; the queued ``steer-next-…`` entry
is then run by the send runner, with the Work executor's own settle hook (``RunnerPolicy.on_settle``).

Killing mutations (each run, seen red, restored — recorded in the commit body):
* ``queue_leftover_steer`` and ``_requeue_from_ledger`` set ``requested_by="operator"`` on the queued send →
  the requester assertion red;
* the same two drop the copied ``send_origin`` (so the fresh ``send_origin()`` stands) → the origin assertion
  red.
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, paths
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.running_work import build_running_work
from agent_runtime.running_work.vocabulary import KIND_CHAT_TURN
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor, _turn_args
from tests.agent_runtime.held_model_turn import Running
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # fixtures
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures: a chat, a held model

pytestmark = pytest.mark.timeout(180)

REQUEST = "BATCH-Q44PM7:L1"
WORK_TURN = "work-" + REQUEST
STEER_ID = "agent-chat-send-cadc7833"
LATE_TURN = "steer-next-" + STEER_ID
WORK_BUDGET = 1234.0
#: The origin ``PersonaTurnExecutor.start_from`` writes on a Work run's queued send.
WORK_ORIGIN = {"owner": None, "gateway": False, "kind": "work", "work": REQUEST, "rows": [], "goal": False}


def _steer(root: str, steer_id: str, text: str) -> dict:
    return submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root, message=text,
                                     client_message_id=steer_id, timeout_seconds=20)


def _row(root: str) -> dict:
    [row] = [row for row in build_running_work()["rows"]
             if row["kind"] == KIND_CHAT_TURN and row["owner"]["session_id"] == root]
    return row


def test_a_late_steer_at_a_work_turn_runs_next_as_another_turn_of_that_work_request(chat, model):
    instance, root = chat
    executor = PersonaTurnExecutor()
    reported: list[tuple[str, str, str]] = []  # (work request, the turn reported as its run, verdict)
    executor.on_settle(lambda run, outcome: reported.append(
        (run.request_id, run.run_id.partition("/")[2], outcome.verdict.value)))
    policy = chat_root_send_runner.RunnerPolicy(on_settle=executor.settled)

    args = _turn_args(PersonaInstanceStore().get(instance), root, WORK_TURN, "Tidy the meadow.",
                      f"work:{REQUEST}", max_seconds=WORK_BUDGET)
    entry, _position, _replay = send_queue.enqueue(
        root, WORK_TURN, send_queue.persistable_args(args, origin=WORK_ORIGIN))
    work_turn = Running(lambda: chat_root_send_runner._run_entry(entry, policy))
    assert model.entered.wait(60), "the Work turn never reached the model"
    ack = _steer(root, STEER_ID, "also water the roses")
    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.hold = False
    model.release.set()
    work_turn.join(60)

    # The Work turn had one model call, so the steer landed in no tool round: it is the root's next turn —
    # and the Work request has ALREADY been reported ended, on the Work turn's reply alone.
    assert reported == [(REQUEST, WORK_TURN, "failed")]  # "failed": the rig's model writes no work report
    late = send_queue.find(root, LATE_TURN)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    assert late.args["message"] == "also water the roses" and late.args["steer_of"] == [STEER_ID]

    # TODAY: the person's late message is queued as a turn of the Work request — its requester, its time
    # budget and its origin (which names the request, its rows and where its settle is reported).
    assert late.args["requested_by"] == f"work:{REQUEST}"
    assert late.args["max_seconds"] == WORK_BUDGET
    assert late.args[send_queue.ORIGIN_ARG] == WORK_ORIGIN

    model.entered.clear()
    model.release.clear()
    model.hold = True
    late_turn = Running(lambda: chat_root_send_runner._run_entry(late, policy))
    assert model.entered.wait(60), "the late steer's turn never reached the model"
    # The model is given the late message as the turn's own user message.
    assert any("also water the roses" in text for text in model.user_texts())

    # TODAY: it takes a steer for the reason a Work turn does (a ``work:`` requester starts the steer watcher,
    # RT-STEER-ONLY-STREAMING-TURNS), not because anyone is watching a stream — and a steer that is late for
    # THIS turn is queued as a third turn of the same Work request.
    row = _row(root)
    assert row["work_id"] == "chat_turn:" + LATE_TURN and row["steerable"] is True, row
    assert "work_request" not in row, row  # the board is not told the turn belongs to the request
    second = _steer(root, "agent-chat-send-2", "and the tulips")
    assert second["ok"] is True and second["execution_state"] == "accepted", second
    model.hold = False
    model.release.set()
    late_turn.join(60)
    chained = send_queue.find(root, "steer-next-agent-chat-send-2")
    assert chained is not None and chained.args["requested_by"] == f"work:{REQUEST}"

    # TODAY: when the late turn ends, the Work request is reported ended a SECOND time, as that turn — a
    # plain chat reply carries no work report, so the second report reads "failed". (Read in code, not
    # driven here: the Work engine and the batch dispatcher drop a report for a run they already settled.)
    assert reported == [(REQUEST, WORK_TURN, "failed"), (REQUEST, LATE_TURN, "failed")]
