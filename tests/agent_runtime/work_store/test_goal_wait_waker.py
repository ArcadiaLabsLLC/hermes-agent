"""A judge ``wait`` parks a bound Work run; the serve's waker continues it when the barrier lifts.

``RT-GOAL-WAIT-WAKER``: upstream's CLI polls the barrier when idle; the serve polls it on the Work
engine's tick (``goal_turns.wake_parked`` through ``PersonaTurnExecutor.wake_parked``).

Killing mutation: ``wake_parked`` returns 0 without looking → ``test_a_lifted_barrier_continues_the_run``
red. A turn that settles while the barrier still holds answers ``waiting``; mapping it to ``_stopped``
again → ``test_a_turn_settled_while_parked_keeps_the_run`` red.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from agent_runtime import chat_goal
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store import engine as work_engine
from agent_runtime.work_store import goal_turns
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor

from tests.agent_runtime.work_store.contract_fakes import FakeGoal, FakeGoals, decision

ROOT = "persona_chat_root_wait"
RID = "ws:repo:RT-W:2026-10-18:abc"
FIRST = f"work-{RID}"


class _BarrierGoal(FakeGoal):
    """A goal whose barrier the test lifts: upstream's ``waiting_until`` + ``is_waiting``."""

    holding = True

    def set(self, goal, *, max_turns=None, contract=None):
        state = super().set(goal, max_turns=max_turns, contract=contract)
        state.waiting_on_pid = state.waiting_on_session = None
        state.waiting_until = 0.0
        return state

    def evaluate_after_turn(self, last_response, *, user_initiated=True):
        decided = super().evaluate_after_turn(last_response, user_initiated=user_initiated)
        if decided.get("verdict") == "wait":
            self.state.waiting_until = 9e9
        return decided

    def is_waiting(self):
        return self.holding


class _Goals(FakeGoals):
    def __call__(self, session_id):
        return self.by_root.setdefault(session_id, _BarrierGoal(session_id))


def _parked_run():
    goals = _Goals()
    executor = PersonaTurnExecutor(instances=SimpleNamespace(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   goals=goals, workdir_of=lambda instance: None)
    told: list = []
    executor.on_settle(lambda run, outcome: told.append(outcome))
    goals(ROOT).set("ship it")
    chat_goal.bind(chat_goal.GoalBinding(ROOT, RID, (("repo", "q.md", "RT-W"),), {"persona_id": "neko"}, FIRST))
    entry = send_queue.enqueue(ROOT, FIRST, {"persona_id": "neko", send_queue.ORIGIN_ARG: {"work": RID}})[0]
    goals(ROOT).decisions.append(decision("wait", reason="the build is running"))
    executor.settled(entry, 0, {"ok": True, "reply": "started the build"})
    send_queue.remove(ROOT, FIRST)
    assert chat_goal.binding(ROOT).held is True and told == []
    return executor, goals, told


def test_a_held_barrier_parks_the_run():
    executor, _goals, _ = _parked_run()

    assert executor.wake_parked() == 0
    assert send_queue.entries(ROOT) == []


def test_a_lifted_barrier_continues_the_run():
    executor, goals, told = _parked_run()
    goals(ROOT).holding = False

    assert executor.wake_parked() == 1
    [entry] = send_queue.entries(ROOT)
    assert entry.client_message_id == f"{FIRST}-g1"
    assert entry.args["message"].startswith("[Continuing toward your standing goal]")
    assert chat_goal.binding(ROOT).held is False and told == []
    assert executor.wake_parked() == 0  # not held any more: one continuation, never two


def test_a_queued_send_on_the_root_is_left_to_settle_on_its_own():
    executor, goals, _ = _parked_run()
    goals(ROOT).holding = False
    send_queue.enqueue(ROOT, "operator-1", {"message": "hi"})

    assert executor.wake_parked() == 0


def test_a_turn_settled_while_parked_keeps_the_run():
    executor, goals, told = _parked_run()
    goals(ROOT).decisions.append(decision("waiting", reason="still waiting"))
    operator = send_queue.enqueue(ROOT, "operator-1", {"message": "how is it going"})[0]
    executor.settled(operator, 0, {"ok": True, "reply": "still building"})

    assert told == [] and chat_goal.binding(ROOT) is not None and goals(ROOT).state.status == "active"


def test_the_engine_loop_runs_the_waker_after_each_tick():
    stop = threading.Event()
    calls: list = []
    engine = SimpleNamespace(tick=lambda: calls.append("tick"))
    thread = work_engine.start_work_engine(stop_event=stop, engine=engine, interval_s=0.01,
                                           on_tick=lambda: (calls.append("wake"), stop.set()))
    thread.join(10)

    assert calls[:2] == ["tick", "wake"]


# ── RT-CHAT-GOAL-WAIT-NO-WAKER: a chat goal no Work run owns parks and wakes the same way ──

CHAT_ROOT = "persona_chat_root_chat_goal_wait"


def _parked_chat_goal():
    goals = _Goals()
    executor = PersonaTurnExecutor(instances=SimpleNamespace(), root_of=lambda store, **_: CHAT_ROOT,
                                   wake=lambda: None, goals=goals, workdir_of=lambda instance: None)
    goals(CHAT_ROOT).set("ship it")
    entry = send_queue.enqueue(CHAT_ROOT, "operator-1", {"persona_id": "neko", "message": "start the build",
                                                         "idempotency_key": "k1"})[0]
    goals(CHAT_ROOT).decisions.append(decision("wait", reason="the build is running"))
    executor.settled(entry, 0, {"ok": True, "reply": "started the build"})
    send_queue.remove(CHAT_ROOT, "operator-1")
    assert chat_goal.binding(CHAT_ROOT) is None and send_queue.entries(CHAT_ROOT) == []
    return executor, goals


def test_a_chat_goal_parked_on_wait_holds_while_the_barrier_holds():
    executor, _ = _parked_chat_goal()

    assert executor.wake_parked() == 0
    assert send_queue.entries(CHAT_ROOT) == []


def test_a_lifted_barrier_continues_a_chat_goal_from_the_settled_turn():
    """Killing mutation: drop the chat-goal park (``chat_goal.park``) or its scan in ``wake_parked`` → red."""

    executor, goals = _parked_chat_goal()
    goals(CHAT_ROOT).holding = False

    assert executor.wake_parked() == 1
    [entry] = send_queue.entries(CHAT_ROOT)
    assert entry.args["persona_id"] == "neko" and "idempotency_key" not in entry.args
    assert entry.args["message"].startswith("[Continuing toward your standing goal]")
    assert entry.args[send_queue.ORIGIN_ARG][goal_turns.CHAT_GOAL_ORIGIN] is True
    assert executor.wake_parked() == 0  # one continuation, never two


def test_a_chat_goal_that_ends_leaves_nothing_parked():
    executor, goals = _parked_chat_goal()
    goals(CHAT_ROOT).pause("operator paused")
    goals(CHAT_ROOT).holding = False

    assert executor.wake_parked() == 0
    assert chat_goal.parked() == []
