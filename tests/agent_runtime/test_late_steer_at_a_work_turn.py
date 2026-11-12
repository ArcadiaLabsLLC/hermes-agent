"""``RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT``: a too-late steer at a task run is the
operator's own chat message.

A steer typed at a running Work turn that arrives after the turn's last tool round runs as the chat root's
next turn, ``steer-next-<id>``. Until 2026-11-12 that turn was queued from a copy of the Work turn's own send,
so it was, in every field but the message and its ids, another turn OF THE WORK REQUEST — its requester
(``work:<request>``), its time budget, its origin (the request, its rows, its lane), a wave lane's working
folder — and when it ended the run was reported ended a second time, as "failed" (a chat reply carries no
work report). Reproduced here by lane w1112b-hm-rejoin4b (55ca79e8ba) and put to the owner.

RULED 2026-11-12 (owner: "it should be an ordinary chat message"): for a one-shot and a wave-lane Work run the
late steer runs next as the operator's own chat turn — what ``runtime.chat.message`` would have queued at that
moment. The run is reported ended ONCE, as it ended. An until-done run's late steer stays a turn of the run
(there every turn of the bound chat feeds the run's after-turn hook, by design).

Whole turns (``held_model_turn``): a Work turn — hand-queued as ``PersonaTurnExecutor.start_from`` queues it,
and (the wave-lane test) queued BY ``start_from`` the way ``BatchLaneExecutor.start`` calls it, with the lane's
working folder and lent skills — is held in its one model call, takes a steer through
``submit_mission_chat_steer`` and ends; the queued ``steer-next-…`` entry is then run by the send runner with
the Work executor's own settle hook (``RunnerPolicy.on_settle``). The other two minting sites (the settle's
ledger sweep, the serve boot's) are read at the queue entry they write — the entry's args are the turn's args
(``chat_root_send_runner._turn_args``).

Killing mutations (each run, seen red, restored — recorded in the commit body):
* ``_next_turn_send`` keeps ``dict(send_args)`` for every turn → the one-shot, wave-lane, ledger-sweep and boot
  tests red (requester, budget, origin, working folder; the run reported ended twice);
* ``_is_until_done_send`` drops its ``goal`` term → the until-done test red;
* ``_operators_own_send`` keeps the run's ``max_seconds`` → the parser-agreement test and the one-shot test red.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, paths
from agent_runtime.chat_turn import OPERATOR_REQUESTED_BY, normalize_chat_message
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.mission_chat_workdir import RUN_WORKDIR_ARG
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.running_work import build_running_work
from agent_runtime.running_work.vocabulary import KIND_CHAT_TURN
from agent_runtime.work_store.executor import Assignment, Brief
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor, _turn_args
from hermes_cli.harness_parts.persona.chat_turn_commit import leftover_steer
from tests.agent_runtime import test_dead_turn_steer_boot_requeue as boot
from tests.agent_runtime import test_steer_accepted_as_reply_ends as gap
from tests.agent_runtime.held_model_turn import Running
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT
from tests.agent_runtime.test_persona_assignments_chat_history import _mission_chat_test_args
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # fixtures
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures: a chat, a held model

pytestmark = pytest.mark.timeout(180)

REQUEST = "BATCH-Q44PM7:L1"
WORK_TURN = "work-" + REQUEST
STEER_ID = "agent-chat-send-cadc7833"
LATE_TURN = "steer-next-" + STEER_ID
WORK_BUDGET = 1234.0
ROW = RowRef("repo", "queue.md", "RT-A")
#: The origin ``PersonaTurnExecutor.start_from`` writes on a Work run's queued send.
WORK_ORIGIN = {"owner": None, "gateway": False, "kind": "work", "work": REQUEST, "rows": [ROW.items()], "goal": False}
#: The origin of a send whose sender has no live connection: an ordinary message's, naming no run.
OPERATOR_ORIGIN = {"owner": None, "gateway": False}


def _steer(root: str, steer_id: str, text: str) -> dict:
    return submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root, message=text,
                                     client_message_id=steer_id, timeout_seconds=20)


def _row(root: str) -> dict:
    [row] = [row for row in build_running_work()["rows"]
             if row["kind"] == KIND_CHAT_TURN and row["owner"]["session_id"] == root]
    return row


def _reports(executor: PersonaTurnExecutor) -> list[tuple[str, str, str]]:
    """Every ending the executor reports to its listeners (the Work engine, the batch dispatcher), in order:
    (work request, the turn reported as its run, verdict)."""

    reported: list[tuple[str, str, str]] = []
    executor.on_settle(lambda run, outcome: reported.append(
        (run.request_id, run.run_id.partition("/")[2], outcome.verdict.value)))
    return reported


@contextlib.contextmanager
def _screen(_entry):
    """The serve's stream for a queued turn (``RunnerPolicy.stream``): the turn runs streamed, as it does live."""

    yield SimpleNamespace(finish=lambda exit_code, payload: None)


def _assert_the_operators_own_send(args: dict, message: str, steer_id: str) -> None:
    assert args["message"] == message and args["steer_of"] == [steer_id]
    assert args["requested_by"] == OPERATOR_REQUESTED_BY
    assert args["max_seconds"] is None, "a turn a person sent has no wall clock"
    assert args[send_queue.ORIGIN_ARG] == OPERATOR_ORIGIN
    assert not args.get(RUN_WORKDIR_ARG), "the late turn would run in the run's working folder"


def test_a_late_steer_at_a_work_turn_runs_next_as_the_operators_own_message(chat, model):
    instance, root = chat
    executor = PersonaTurnExecutor()
    reported = _reports(executor)
    policy = chat_root_send_runner.RunnerPolicy(on_settle=executor.settled)

    args = _turn_args(PersonaInstanceStore().get(instance), root, WORK_TURN, "Tidy the meadow.",
                      f"work:{REQUEST}", max_seconds=WORK_BUDGET)
    entry, _position, _replay = send_queue.enqueue(
        root, WORK_TURN, send_queue.persistable_args(args, origin=WORK_ORIGIN))
    work_turn = Running(lambda: chat_root_send_runner._run_entry(entry, policy))
    assert model.entered.wait(60), "the Work turn never reached the model"
    assert _row(root)["steerable"] is True  # a Work turn takes a steer though it streams to no screen
    ack = _steer(root, STEER_ID, "also water the roses")
    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.hold = False
    model.release.set()
    work_turn.join(60)

    # The Work turn had one model call, so the steer landed in no tool round: it is the root's next turn —
    # and the Work request has been reported ended, on the Work turn's reply alone.
    assert reported == [(REQUEST, WORK_TURN, "failed")]  # "failed": the rig's model writes no work report
    late = send_queue.find(root, LATE_TURN)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    _assert_the_operators_own_send(late.args, "also water the roses", STEER_ID)
    assert late.args["persona_instance_id"] == instance and late.args["session_id"] == root

    # Run with no screen (this rig's default policy), the late turn takes no steer: it is steerable for the
    # reason any operator turn is — a stream — and no longer because a ``work:`` requester starts the watcher.
    model.entered.clear()
    model.release.clear()
    model.hold = True
    late_turn = Running(lambda: chat_root_send_runner._run_entry(late, policy))
    assert model.entered.wait(60), "the late steer's turn never reached the model"
    assert any("also water the roses" in text for text in model.user_texts())
    row = _row(root)
    assert row["work_id"] == "chat_turn:" + LATE_TURN and row["steerable"] is False, row
    assert "work_request" not in row, row
    refused = _steer(root, "agent-chat-send-0", "nobody is watching")
    assert refused["ok"] is False and refused["error_kind"] == "no_active_turn", refused
    model.hold = False
    model.release.set()
    late_turn.join(60)

    # The run is reported ended ONCE: the late turn's settle is the chat's, not the run's. (Before the ruling
    # a second ``(REQUEST, LATE_TURN, "failed")`` followed, which the engine and the dispatcher dropped.)
    assert reported == [(REQUEST, WORK_TURN, "failed")]
    assert send_queue.entries(root) == []


def test_a_steer_late_for_the_late_turn_is_the_next_ordinary_turn(chat, model):
    """Streamed, as the serve runs a queued send: the late turn takes a steer like any operator turn, and a
    steer too late for IT is queued as the operator's own message again — never a turn of the ended run."""

    instance, root = chat
    executor = PersonaTurnExecutor()
    reported = _reports(executor)
    policy = chat_root_send_runner.RunnerPolicy(on_settle=executor.settled, stream=_screen)
    args = _turn_args(PersonaInstanceStore().get(instance), root, WORK_TURN, "Tidy the meadow.",
                      f"work:{REQUEST}", max_seconds=WORK_BUDGET)
    entry, _position, _replay = send_queue.enqueue(
        root, WORK_TURN, send_queue.persistable_args(args, origin=WORK_ORIGIN))
    work_turn = Running(lambda: chat_root_send_runner._run_entry(entry, policy))
    assert model.entered.wait(60), "the Work turn never reached the model"
    assert _steer(root, STEER_ID, "also water the roses")["execution_state"] == "accepted"
    model.hold = False
    model.release.set()
    work_turn.join(60)
    late = send_queue.find(root, LATE_TURN)

    model.entered.clear()
    model.release.clear()
    model.hold = True
    late_turn = Running(lambda: chat_root_send_runner._run_entry(late, policy))
    assert model.entered.wait(60), "the late steer's turn never reached the model"
    row = _row(root)
    assert row["work_id"] == "chat_turn:" + LATE_TURN and row["steerable"] is True, row
    second = _steer(root, "agent-chat-send-2", "and the tulips")
    assert second["ok"] is True and second["execution_state"] == "accepted", second
    model.hold = False
    model.release.set()
    late_turn.join(60)

    chained = send_queue.find(root, "steer-next-agent-chat-send-2")
    assert chained is not None, [e.client_message_id for e in send_queue.entries(root)]
    _assert_the_operators_own_send(chained.args, "and the tulips", "agent-chat-send-2")
    Running(lambda: chat_root_send_runner._run_entry(chained, policy)).join(60)
    assert any("and the tulips" in text for text in model.user_texts())
    assert reported == [(REQUEST, WORK_TURN, "failed")]


def test_a_late_steer_at_a_wave_lanes_turn_does_not_run_in_the_lanes_folder_or_with_its_skills(
        chat, model, tmp_path):
    """Queued BY ``start_from`` exactly as ``BatchLaneExecutor.start`` calls it: the lane's id in the origin, its
    worktree as the turn's working folder, its lent skills."""

    instance, root = chat
    lane_folder = tmp_path / "lane-worktree"
    lane_folder.mkdir()
    executor = PersonaTurnExecutor(wake=lambda: None, queue_skills=lambda **_kwargs: {"ok": True})
    reported = _reports(executor)
    policy = chat_root_send_runner.RunnerPolicy(on_settle=executor.settled)
    run = executor.start_from(
        Assignment((ROW,), instance, Brief(title="Tidy", objective="Tidy the meadow."), REQUEST,
                   skills=("lane-skill",)),
        {"batch_lane": "L1"}, message="Lane brief: tidy the meadow.", workdir=str(lane_folder))
    entry = send_queue.find(root, run.client_message_id)
    # The premise: the lane's turn is queued with all of it.
    assert entry.args[RUN_WORKDIR_ARG] == str(lane_folder)
    assert entry.args[send_queue.ORIGIN_ARG]["batch_lane"] == "L1"
    assert entry.args[send_queue.ORIGIN_ARG]["skills"] == ["lane-skill"]

    lane_turn = Running(lambda: chat_root_send_runner._run_entry(entry, policy))
    assert model.entered.wait(60), "the lane's turn never reached the model"
    lane_prompt = str(model.requests[-1]["messages"])
    assert _steer(root, STEER_ID, "also water the roses")["execution_state"] == "accepted"
    model.hold = False
    model.release.set()
    lane_turn.join(60)
    assert reported == [(REQUEST, WORK_TURN, "failed")]

    late = send_queue.find(root, LATE_TURN)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    _assert_the_operators_own_send(late.args, "also water the roses", STEER_ID)
    origin = late.args[send_queue.ORIGIN_ARG]
    assert "batch_lane" not in origin and "skills" not in origin and "rows" not in origin, origin

    model.entered.clear()
    model.release.clear()
    model.hold = True
    late_turn = Running(lambda: chat_root_send_runner._run_entry(late, policy))
    assert model.entered.wait(60), "the late steer's turn never reached the model"
    late_prompt = str(model.requests[-1]["messages"])
    model.hold = False
    model.release.set()
    late_turn.join(60)
    # What the model was told: the lane's turn names the lane's folder, the late turn does not.
    assert str(lane_folder) in lane_prompt, "the rig's lane turn was not told its folder — the premise is gone"
    assert str(lane_folder) not in late_prompt
    assert reported == [(REQUEST, WORK_TURN, "failed")]


def _work_send(monkeypatch, module, tmp_path) -> None:
    """Make ``module``'s turn a wave lane's Work turn: its requester, budget, working folder and origin."""

    folder = tmp_path / "lane-worktree"
    folder.mkdir()

    def _args(client_message_id: str):
        args = _mission_chat_test_args(client_message_id, stream=False)
        args.requested_by, args.max_seconds = f"work:{REQUEST}", WORK_BUDGET
        setattr(args, RUN_WORKDIR_ARG, str(folder))
        setattr(args, send_queue.ORIGIN_ARG, dict(WORK_ORIGIN, batch_lane="L1"))
        return args

    monkeypatch.setattr(module, "_args", _args)


def test_a_steer_accepted_as_a_work_turns_reply_ends_is_queued_as_the_operators_own_message(
        monkeypatch, isolate_agent_runtime_root, persisted_persona_samples, tmp_path):
    """The settle's ledger sweep (``_requeue_from_ledger``): accepted, in neither the transcript nor the hand-back."""

    _work_send(monkeypatch, gap, tmp_path)
    gap._a_turn_returns_after_accepting(monkeypatch, [("cm-steer-gap", "also check the logs")])

    _assert_the_operators_own_send(
        send_queue.find(ROOT, "steer-next-cm-steer-gap").args, "also check the logs", "cm-steer-gap")


def test_a_dead_work_turns_steer_is_queued_at_boot_as_the_operators_own_message(
        monkeypatch, isolate_agent_runtime_root, persisted_persona_samples, tmp_path):
    """The serve boot's sweep of a dead executor's ledger, from the send the watcher kept beside it."""

    _work_send(monkeypatch, boot, tmp_path)
    boot._a_turn_dies_holding_a_steer(monkeypatch)
    assert leftover_steer.requeue_dead_turn_steers() == ["steer-next-cm-steer-orphan"]

    _assert_the_operators_own_send(send_queue.find(ROOT, "steer-next-cm-steer-orphan").args,
                                   "this was typed before the crash", "cm-steer-orphan")


def test_a_late_steer_at_an_until_done_run_stays_a_turn_of_the_run():
    """Left as it was (the ruling): on a chat bound to an until-done run every turn feeds the run's hook."""

    send = {"persona_id": "p", "persona_instance_id": "personainst_1", "requested_by": f"work:{REQUEST}",
            "max_seconds": WORK_BUDGET, send_queue.ORIGIN_ARG: dict(WORK_ORIGIN, goal=True)}

    late = leftover_steer._next_turn_send(send, session_id="root", text="one more thing", next_id=LATE_TURN,
                                          ids=[STEER_ID])

    assert late["requested_by"] == f"work:{REQUEST}" and late["max_seconds"] == WORK_BUDGET
    assert late[send_queue.ORIGIN_ARG] == dict(WORK_ORIGIN, goal=True)
    assert late["message"] == "one more thing" and late["steer_of"] == [STEER_ID]


def test_the_operators_own_send_is_what_the_real_parser_gives_the_apps_message():
    """``_operators_own_send`` against ``runtime.chat.message`` lowered and parsed (the parser the serve binds):
    every field it states is the parser's value for the app's send, and every field the parser adds that it
    does not state is empty — so a turn run from it is the turn an ordinary send runs."""

    from hermes_cli.harness_parts.serve.argv_lane import _build_harness_parser

    request = normalize_chat_message({"turn_request_id": LATE_TURN, "persona_id": "p", "message": "m",
                                      "session_id": "root", "persona_instance_id": "personainst_1"})
    parsed = send_queue.persistable_args(_build_harness_parser().parse_args(request.argv))
    ours = leftover_steer._next_turn_send(
        {"persona_id": "p", "persona_instance_id": "personainst_1", "requested_by": f"work:{REQUEST}",
         "max_seconds": WORK_BUDGET, RUN_WORKDIR_ARG: "/lane", send_queue.ORIGIN_ARG: WORK_ORIGIN},
        session_id="root", text="m", next_id=LATE_TURN, ids=[])

    stated = {key: value for key, value in ours.items() if key != send_queue.ORIGIN_ARG}
    assert {key: parsed.get(key) for key in stated} == stated
    unstated = {key: value for key, value in parsed.items() if key not in stated and value not in (None, False, "", [])}
    # The parser's own routing words (which sub-command was typed), not fields of the send.
    assert set(unstated) <= {"command", "harness_command", "mission_chat_command", "persona"}, unstated
