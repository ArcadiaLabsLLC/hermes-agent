"""PersonaTurnExecutor with ``goal_mode=UNTIL_DONE`` — a goal on the root, continued as queued sends (B3).

Dispatcher plan ``docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md`` §2.2, §5, §6.
The send queue and the goal bindings are the real ones on this test's isolated home; the goal engine
(``GoalManager``), the instance store and the root lookup are fakes.

Killing mutation: the continuation is forged by calling the mission-chat door directly instead of
``chat_root_send_queue`` → ``test_busy_root_queues_never_steers`` red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_goal, mission_chat_door, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store.executor import (
    Assignment, Brief, GoalMode, RunStatus, StopReason, Verdict,
)
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from agent_runtime.work_store.reasons import Reason, WorkRefused

from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

ROOT = "persona_chat_root_goal"
REF = RowRef("repo", "Repo_Brain/20 — Active Initiatives/q.md", "RT-G")
RID = "ws:repo:RT-G:2026-10-18:abc"
TEST_CMD = "scripts/run_tests.sh tests/agent_runtime/test_thing.py"
DONE_REPORT = "Shipped.\n```work_report\nverdict: done\nresult: shipped it\n```\n"


class _Instances:
    def get(self, instance_id):
        if instance_id != "inst-1":
            raise KeyError(instance_id)
        return SimpleNamespace(id="inst-1", persona_id="neko", runtime_root=str(paths.store_root()))


@pytest.fixture(autouse=True)
def no_direct_turns(monkeypatch):
    """A goal run never runs a turn itself: every turn goes through the root's send queue."""

    def refuse(args):
        raise AssertionError("a goal turn ran through the door directly instead of the send queue")

    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


def _assignment(request_id=RID, **kw):
    brief = Brief(title="make it work", objective="Make the thing work.", acceptance="the test is green",
                  tests=(TEST_CMD,))
    return Assignment((REF,), "inst-1", brief, request_id, goal_mode=GoalMode.UNTIL_DONE, **kw)


def _executor(goals=None):
    goals = goals or FakeGoals()
    told: list = []
    executor = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   goals=goals, workdir_of=lambda instance: None)
    executor.on_settle(lambda run, outcome: told.append((run, outcome)))
    return executor, goals, told


def _settle(executor, cmid, reply, *, exit_code=0):
    entry = send_queue.find(ROOT, cmid)
    assert entry is not None, f"no queued send {cmid}"
    executor.settled(entry, exit_code, {"ok": exit_code == 0, "reply": reply})
    send_queue.remove(ROOT, cmid)  # what the runner does after on_settle


def test_until_done_sets_the_goal_with_gates_and_queues_the_first_turn():
    executor, goals, _ = _executor()
    run = executor.start(_assignment())
    goal = goals(ROOT)
    assert goal.state.goal == "Make the thing work." and goal.state.contract.outcome == "the test is green"
    assert goal.gates == [TEST_CMD]
    assert TEST_CMD in goal.state.contract.verification
    bound = chat_goal.binding(ROOT)
    assert bound.request_id == RID and bound.rows == ((REF.slot, REF.note, REF.id),)
    entry = send_queue.find(ROOT, run.client_message_id)
    assert entry.args[send_queue.ORIGIN_ARG]["goal"] is True
    assert executor.status(run.run_id) is RunStatus.QUEUED
    # One run per request id: a replayed start neither re-arms the goal nor queues a second turn.
    goal.gates.append("sentinel")
    assert executor.start(_assignment()).run_id == run.run_id
    assert goal.gates[-1] == "sentinel" and len(send_queue.entries(ROOT)) == 1


def test_goal_gates_can_be_turned_off():
    executor, goals, _ = _executor()
    executor.start(_assignment(goal_gates=False))
    assert goals(ROOT).gates == []


def test_a_second_goal_on_a_bound_root_is_executor_busy():
    executor, _, _ = _executor()
    executor.start(_assignment())
    with pytest.raises(WorkRefused) as refused:
        executor.start(_assignment(request_id="ws:repo:RT-G:2026-10-18:zzz"))
    assert refused.value.reason is Reason.EXECUTOR_BUSY


def test_busy_root_queues_never_steers():
    """An operator send holds the root: the run's first turn queues BEHIND it, and each continuation is a
    queued send — the door is never called by the executor (the autouse fixture fails if it is)."""

    send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "operator"}, "message": "hi"})
    executor, goals, told = _executor()
    run = executor.start(_assignment())
    assert send_queue.position(ROOT, run.client_message_id) == 2
    goals(ROOT).decisions += [decision("continue", go_on=True), decision("continue", go_on=True)]
    _settle(executor, "operator-1", "operator turn")  # bound root: the operator turn is evaluated too
    assert send_queue.find(ROOT, f"{run.client_message_id}-g1") is None  # the run's own turn still waits
    _settle(executor, run.client_message_id, "first work turn")
    assert goals(ROOT).evaluated == [("operator turn", True), ("first work turn", False)]
    continuation = send_queue.find(ROOT, f"{run.client_message_id}-g2")
    assert continuation is not None and continuation.state == send_queue.STATE_QUEUED
    assert continuation.args["message"] == "continue please"
    assert continuation.args[send_queue.ORIGIN_ARG]["work"] == RID
    assert executor.status(run.run_id) is RunStatus.QUEUED and told == []


def test_the_judge_ends_the_run_done_and_the_report_is_kept():
    executor, goals, told = _executor()
    run = executor.start(_assignment())
    goals(ROOT).decisions += [decision("continue", go_on=True), decision("done")]
    _settle(executor, run.client_message_id, "working")
    assert goals(ROOT).evaluated == [("working", False)]
    _settle(executor, f"{run.client_message_id}-g1", DONE_REPORT)
    [(ended, outcome)] = told
    assert ended.run_id == run.run_id and ended.request_id == RID
    assert outcome.verdict is Verdict.DONE and outcome.per_row[REF].result == "shipped it"
    assert chat_goal.binding(ROOT) is None and send_queue.entries(ROOT) == []


@pytest.mark.parametrize(("reply", "decisions", "verdict"), [
    ("```work_report\nverdict: blocked\nresult: stuck\nquestion: which db?\nrecommend: pg\n```", [], Verdict.BLOCKED),
    ("no report", [decision("blocked", reason="cannot be done")], Verdict.BLOCKED),
    ("no report", [decision("continue", reason="turn budget spent")], Verdict.STOPPED),
    (DONE_REPORT, [decision("gate_failed", reason="gate exhausted retries")], Verdict.STOPPED),
])
def test_endings_other_than_done(reply, decisions, verdict):
    executor, goals, told = _executor()
    run = executor.start(_assignment())
    goals(ROOT).decisions += decisions
    _settle(executor, run.client_message_id, reply)
    [(_, outcome)] = told
    assert outcome.verdict is verdict
    assert goals(ROOT).state.status == "paused" and chat_goal.binding(ROOT) is None


def test_a_failed_turn_ends_the_run_failed_without_asking_the_judge():
    executor, goals, told = _executor()
    run = executor.start(_assignment())
    entry = send_queue.find(ROOT, run.client_message_id)
    executor.settled(entry, 2, {"ok": False, "error_kind": "provider_error", "reply": ""})
    [(_, outcome)] = told
    assert outcome.verdict is Verdict.FAILED and goals(ROOT).evaluated == []


def test_stop_removes_a_queued_goal_run_and_waits_on_a_running_one():
    executor, goals, told = _executor()
    run = executor.start(_assignment())
    assert executor.stop(run.run_id, StopReason.OPERATOR)["stopped"] is True
    assert send_queue.entries(ROOT) == [] and chat_goal.binding(ROOT) is None
    assert goals(ROOT).state.status == "paused"

    executor, goals, told = _executor()
    run = executor.start(_assignment(request_id="ws:repo:RT-G:2026-10-18:def"))
    send_queue.mark(ROOT, run.client_message_id, state=send_queue.STATE_RUNNING)
    assert executor.status(run.run_id) is RunStatus.RUNNING
    assert executor.stop(run.run_id, StopReason.OPERATOR)["stopped"] is False
    _settle(executor, run.client_message_id, "still working")
    [(_, outcome)] = told
    assert outcome.verdict is Verdict.STOPPED and goals(ROOT).evaluated == []
