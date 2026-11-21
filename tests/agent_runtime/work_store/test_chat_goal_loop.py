"""A chat's standing goal is its own thing; a Work run's Until done is one user of it.

Row ``RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT`` (owner 2026-11-21: "yea
that logic should be decoupled from tasks so it could be a slash command"). One loop
(``agent_runtime.chat_goal_loop.step``) takes every continuation, for a plain chat and for a Work run;
the chat's goal verbs drive the run that uses it.

Killing mutations, each seen red:
* Work's ``after_turn`` forges its own continuation instead of calling ``chat_goal_loop.step`` →
  ``test_one_loop_takes_every_continuation[work]`` red.
* drop the ``bound is not None`` refusal in ``chat_goal._set`` → ``test_set_on_a_work_runs_chat_is_refused`` red.
* drop the ``stop_with_goal`` call in ``serve_rpc/chat_goal._goal_reply`` →
  ``test_pausing_the_chats_goal_stops_the_run_that_uses_it`` red.
* drop ``_goal_put_down`` from Work's ``after_turn`` → ``test_a_goal_cleared_under_a_running_pass_ends_the_run`` red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_goal, chat_goal_loop
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.serve_rpc import _METHODS
from agent_runtime.work_store.executor import Verdict
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor

from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

ROOT = "persona_chat_root_goal_loop"
RID = "ws:repo:RT-G:2026-11-21:abc"
FIRST = f"work-{RID}"


def _executor(goals):
    executor = PersonaTurnExecutor(instances=SimpleNamespace(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   goals=goals, workdir_of=lambda instance: None)
    told: list = []
    executor.on_settle(lambda run, outcome: told.append(outcome))
    return executor, told


def _bound_pass(goals, *, state=send_queue.STATE_RUNNING):
    goals(ROOT).set("ship it")
    chat_goal.bind(chat_goal.GoalBinding(ROOT, RID, (("repo", "q.md", "RT-G"),), {"persona_id": "neko"}, FIRST))
    entry = send_queue.enqueue(ROOT, FIRST, {"persona_id": "neko", send_queue.ORIGIN_ARG: {"work": RID}})[0]
    if state:
        send_queue.mark(ROOT, FIRST, state=state)
    return send_queue.find(ROOT, FIRST) or entry


@pytest.mark.parametrize("owner", ["chat", "work"])
def test_one_loop_takes_every_continuation(monkeypatch, owner):
    goals = FakeGoals()
    executor, _ = _executor(goals)
    steps: list = []
    real = chat_goal_loop.step
    monkeypatch.setattr(chat_goal_loop, "step", lambda *a, **k: steps.append(a[0]) or real(*a, **k))
    if owner == "work":
        entry = _bound_pass(goals)
    else:
        goals(ROOT).set("ship it")
        entry = send_queue.enqueue(ROOT, "operator-1", {"persona_id": "neko", "message": "go"})[0]
    goals(ROOT).decisions.append(decision("continue", go_on=True))
    executor.settled(entry, 0, {"ok": True, "reply": "one step done"})
    send_queue.remove(ROOT, entry.client_message_id)

    assert steps == [ROOT]
    [queued] = send_queue.entries(ROOT)
    assert queued.args["message"] == "continue please"
    assert queued.client_message_id == (f"{FIRST}-g1" if owner == "work" else chat_goal_loop._cmid("operator-1"))


def _call(verb, **params):
    replies: list = []
    context = SimpleNamespace(spawn_reply=lambda reply: replies.append(reply()) or True, caller=None)
    _METHODS[f"runtime.chat.goal.{verb}"](7, params, context)
    [reply] = replies
    return reply


def test_set_on_a_work_runs_chat_is_refused():
    _call("set", session_id=ROOT, goal="the run's goal")
    chat_goal.bind(chat_goal.GoalBinding(ROOT, RID, (("repo", "q.md", "RT-G"),)))

    reply = _call("set", session_id=ROOT, goal="another goal")
    assert reply["error"]["data"]["reason"] == "executor_busy"
    assert _call("status", session_id=ROOT)["result"]["goal"]["goal"] == "the run's goal"


def test_pausing_the_chats_goal_stops_the_run_that_uses_it():
    """A queued pass never begins; the engine's tick ends the run ``STOPPED``."""

    _call("set", session_id=ROOT, goal="the run's goal")
    chat_goal.bind(chat_goal.GoalBinding(ROOT, RID, (("repo", "q.md", "RT-G"),), {"persona_id": "neko"},
                                         f"{FIRST}-g1"))
    send_queue.enqueue(ROOT, f"{FIRST}-g1", {"persona_id": "neko", send_queue.ORIGIN_ARG: {"work": RID}})

    assert _call("pause", session_id=ROOT)["result"]["goal"]["status"] == "paused"
    assert send_queue.entries(ROOT) == [] and chat_goal.binding(ROOT).stopping is True
    executor, told = _executor(chat_goal.manager)
    executor.wake_parked()
    assert [o.verdict for o in told] == [Verdict.STOPPED] and chat_goal.binding(ROOT) is None


def test_a_goal_cleared_under_a_running_pass_ends_the_run():
    """The engine judges no turn of a goal that is not active; the run must not wait on it forever."""

    goals = FakeGoals()
    executor, told = _executor(goals)
    entry = _bound_pass(goals)
    goals(ROOT).state.status = "cleared"
    goals(ROOT).decisions.append(decision("waiting", reason="the turn engine did not judge this turn"))
    executor.settled(entry, 0, {"ok": True, "reply": "half way"})

    assert [o.verdict for o in told] == [Verdict.STOPPED]
    assert [e.reason for e in told[0].per_row.values()] == ["the chat's goal was cleared"]
    assert chat_goal.binding(ROOT) is None
