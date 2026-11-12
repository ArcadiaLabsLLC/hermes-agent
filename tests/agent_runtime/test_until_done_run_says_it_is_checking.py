"""Between two passes of an until-done run, the chat is held — and ``running_work`` says by what.

``RT-CHAT-HELD-BETWEEN-UNTIL-DONE-PASSES-LISTS-NOTHING-RUNNING`` (seen live by Eternia lane w1112b-turn7: a
message sent between passes sat ``queued`` for 183 s and 185 s with nothing listed as running, the header at
"Standing by"). Reproduced here first, as whole turns (lane w1112b-hm-turnfu): when a pass ends, the runner's
settle asks the goal judge — a model call — BEFORE it removes the pass's queue entry, so the root stays held;
with the judge's call held, ``running_work`` listed nothing for the chat and the pass's entry read
``running``. On the QA fixture the judge is held by the brief's own ``[[qa:hold 170000]]`` (the goal text rides
the judge's prompt), and its three attempts at about a minute each are the three minutes seen live.

Fixed: while it checks, the run is a ``chat_turn`` row of the run (``phase: checking``, its ``work_request`` and
pass, the Stop that ends the whole run), and a Stop pressed then ends the run instead of the judge's verdict.

Killing mutations (each run, seen red, restored — recorded in the commit body):
* ``goal_turns._checked`` drops its ``checking_since`` bind → the listing test red;
* ``ChatTurnLane.collect`` skips ``_checking_runs`` → the listing test red;
* ``after_turn`` ignores ``_stopped_while_checking`` → the Stop test red.
"""

from __future__ import annotations

import threading

import pytest

from agent_runtime import chat_goal, chat_root_send_runner
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.running_work import build_running_work, cancel_work
from agent_runtime.running_work.vocabulary import KIND_CHAT_TURN, PHASE_CHECKING
from agent_runtime.work_store.executor import Assignment, Brief, GoalMode
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.held_model_turn import Running
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # fixtures
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures

pytestmark = pytest.mark.timeout(180)

REQUEST = "ws_x:repo:RT-A:2026-11-12:e30b7e"


def _is_judge(body: dict) -> bool:
    return "judge" in str(body["messages"][0].get("content", "")).lower()[:400]


def _rows(root: str) -> list[dict]:
    return [row for row in build_running_work()["rows"]
            if row["kind"] == KIND_CHAT_TURN and (row.get("owner") or {}).get("session_id") == root]


def _a_pass_ends_and_its_check_is_held(chat, model):
    """Start an until-done run, let pass 1 reply, and hold the judge's model call. Returns what the test needs."""

    instance, root = chat
    executor = PersonaTurnExecutor(wake=lambda: None)
    ended: list[str] = []
    executor.on_settle(lambda run, outcome: ended.append(outcome.verdict.value))
    run = executor.start(Assignment((RowRef("repo", "q.md", "RT-A"),), instance,
                                    Brief(title="Keep the meadow tidy", objective="Keep the meadow tidy"), REQUEST,
                                    goal_mode=GoalMode.UNTIL_DONE))
    entry = send_queue.find(root, run.client_message_id)
    first_pass = Running(lambda: chat_root_send_runner._run_entry(
        entry, chat_root_send_runner.RunnerPolicy(on_settle=executor.settled)))
    assert model.entered.wait(60), "pass 1 never reached the model"
    judging, verdict = threading.Event(), threading.Event()

    def reply(body):
        if _is_judge(body):
            judging.set()
            verdict.wait(120)
            return ('{"verdict": "continue", "reason": "more to do"}', "stop")
        return ("Tidied one corner.", "stop")

    model.reply = reply
    model.hold = False
    model.release.set()
    assert judging.wait(60), "the run never asked its judge"
    return root, run, entry, first_pass, verdict, ended


def test_a_run_checking_a_pass_is_listed_as_running(chat, model):
    root, run, entry, first_pass, verdict, _ended = _a_pass_ends_and_its_check_is_held(chat, model)

    # The premise, as seen live: pass 1 has ended, its entry still holds the chat, and a message sent now waits.
    assert send_queue.find(root, entry.client_message_id).state == send_queue.STATE_RUNNING
    send_queue.enqueue(root, "agent-chat-send-1", {"message": "how is it going?", "session_id": root})
    [row] = _rows(root)
    assert row["status"] == "running" and row["phase"] == PHASE_CHECKING, row
    assert row["work_request"] == REQUEST and row["goal"]["pass"] == 1, row
    assert row["cancellable"] is True and row["steerable"] is False, row

    verdict.set()
    first_pass.join(60)
    assert not [r for r in _rows(root) if r.get("phase") == PHASE_CHECKING]
    assert chat_goal.binding(root).checking_since is None


def test_stop_while_it_checks_ends_the_run(chat, model):
    root, run, entry, first_pass, verdict, ended = _a_pass_ends_and_its_check_is_held(chat, model)
    [row] = _rows(root)

    answer = cancel_work(row["work_id"])
    assert answer["stopped"] == "work_run" and answer["work_request"] == REQUEST, answer
    verdict.set()  # the judge says "continue" — the Stop wins
    first_pass.join(60)

    assert ended == ["stopped"]
    assert chat_goal.binding(root) is None
    assert [e.client_message_id for e in send_queue.entries(root)] == [], "a second pass was queued"
