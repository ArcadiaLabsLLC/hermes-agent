"""A goal advances on EVERY turn on its root, not only on queued ones (``RT-GOAL-DIRECT-SEND-HOOK``).

A direct operator send settles through the serve's ``SettlePush._record_turn_settle``, a queued one
through the runner's ``on_settle``; both reach ``PersonaTurnExecutor.settled`` exactly once. A chat goal
set by ``runtime.chat.goal.set`` (no Work run bound) is judged and continued as a queued send.

Killing mutation: drop the ``self._goal_after_direct_turn(...)`` call from ``_record_turn_settle`` →
``test_a_direct_send_on_a_bound_root_is_the_goals_turn`` red (the judge is never asked).
"""

from __future__ import annotations

import contextlib
import json
import threading
from types import SimpleNamespace

import pytest

from agent_runtime import chat_goal
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store import goal_turns
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from hermes_cli.harness_parts.serve import settle_push
from hermes_cli.harness_parts.serve.settle_push import SettlePush

from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

ROOT = "persona_chat_root_direct"
CMID = "cm-direct-1"
ARGS = {"persona_id": "neko", "session_id": ROOT, "message": "do the thing", "idempotency_key": "idem-1"}


def _argv(cmid=CMID, verb="message"):
    return ["harness", "mission-chat", verb, "--session-id", ROOT, "--client-message-id", cmid, "--json", "hi"]


def _executor(goals):
    return PersonaTurnExecutor(instances=SimpleNamespace(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                               goals=goals, workdir_of=lambda instance: None)


def _serve(executor, monkeypatch, *, inline=True):
    """A serve's settle half: the real ``_record_turn_settle``, its hook run inline instead of on a thread."""

    session = SimpleNamespace(boot_id="boot-1", work_executor=executor, _service_log=lambda record: None,
                              _settle_store_scope=contextlib.nullcontext, _wake_settle_pusher=lambda: None)
    for name in ("_record_turn_settle", "_goal_after_direct_turn"):
        setattr(session, name, getattr(SettlePush, name).__get__(session))
    monkeypatch.setattr(settle_push, "_turn_args", lambda argv: dict(ARGS))
    if inline:
        monkeypatch.setattr(settle_push, "threading", SimpleNamespace(Thread=_InlineThread))
    return session


class _InlineThread:
    def __init__(self, *, target, name, daemon):
        self._target = target

    def start(self):
        self._target()


def _settle(session, *, rid="req-1", cmid=CMID, reply="did it", verb="message", payload=None):
    body = payload or {"ok": True, "reply": reply, "session_id": ROOT, "type": "chat.final"}
    session._record_turn_settle(SimpleNamespace(rid=rid, argv=_argv(cmid, verb)), [json.dumps(body)], 0)


def _bind(goals):
    goals(ROOT).set("ship it")
    chat_goal.bind(chat_goal.GoalBinding(ROOT, "ws:req", (("repo", "q.md", "RT-X"),), dict(ARGS), "work-ws:req"))


def test_a_direct_send_on_a_bound_root_is_the_goals_turn(monkeypatch):
    goals = FakeGoals()
    _bind(goals)
    goals(ROOT).decisions.append(decision("continue", go_on=True))
    _settle(_serve(_executor(goals), monkeypatch))

    assert goals(ROOT).evaluated == [("did it", True)]
    continuation = send_queue.find(ROOT, "work-ws:req-g1")
    assert continuation is not None and continuation.args["message"] == "continue please"


def test_a_chat_goal_with_no_work_run_continues_as_a_queued_send_and_judges_its_own_turn(monkeypatch):
    goals = FakeGoals()
    goals(ROOT).set("ship it")
    goals(ROOT).decisions += [decision("continue", go_on=True), decision("done")]
    executor = _executor(goals)
    _settle(_serve(executor, monkeypatch))

    [entry] = send_queue.entries(ROOT)
    assert entry.args["message"] == "continue please" and entry.args["persona_id"] == "neko"
    assert "idempotency_key" not in entry.args
    assert entry.args[send_queue.ORIGIN_ARG][goal_turns.CHAT_GOAL_ORIGIN] is True
    executor.settled(entry, 0, {"ok": True, "reply": "all done"})  # the runner's on_settle
    assert goals(ROOT).evaluated == [("did it", True), ("all done", False)]
    assert chat_goal.binding(ROOT) is None


@pytest.mark.parametrize("case", ["queued_answer", "replay", "steer", "no_goal"])
def test_a_turn_is_judged_once_or_not_at_all(monkeypatch, case):
    goals = FakeGoals()
    if case != "no_goal":
        _bind(goals)
    goals(ROOT).decisions.append(decision("continue", go_on=True))
    session = _serve(_executor(goals), monkeypatch)
    parsed: list = []
    monkeypatch.setattr(settle_push, "_turn_args", lambda argv: parsed.append(argv) or dict(ARGS))
    if case == "queued_answer":  # the busy-root answer: its turn settles later, through the runner
        _settle(session, payload={"ok": True, "queued": True, "session_id": ROOT})
    elif case == "replay":  # the same message presented again by another request: its first settle stands
        _settle(session, rid="req-1", reply="first")
        goals(ROOT).evaluated.clear()
        _settle(session, rid="req-2", reply="replayed")
    elif case == "steer":
        _settle(session, verb="steer")
    else:
        _settle(session)

    assert goals(ROOT).evaluated == []
    if case == "no_goal":
        assert parsed == []  # no goal, no argv parse


def test_the_hook_runs_off_the_worker_thread(monkeypatch):
    goals = FakeGoals()
    _bind(goals)
    goals(ROOT).decisions.append(decision("done"))
    session = _serve(_executor(goals), monkeypatch, inline=False)
    seen: list = []
    monkeypatch.setattr(PersonaTurnExecutor, "direct_settled",
                        lambda self, *args: seen.append(threading.current_thread().name))
    _settle(session)
    for thread in threading.enumerate():
        if thread.name == "harness-serve-goal-after-turn":
            thread.join(10)
    assert seen == ["harness-serve-goal-after-turn"]


def test_the_direct_sends_argv_parses_to_the_args_a_queued_send_persists(monkeypatch):
    from hermes_cli.harness_parts.parser import build_parser
    from hermes_cli.harness_parts.serve import argv_lane

    monkeypatch.setattr(argv_lane, "_harness_parser_builder", build_parser)
    args = settle_push._turn_args(["harness", "mission-chat", "message", "--persona", "neko", "--session-id", ROOT,
                                   "--client-message-id", CMID, "--message", "hi", "--json"])

    assert args["persona_id"] == "neko" and args["session_id"] == ROOT and args["message"] == "hi"
    assert "func" not in args and "json" not in args
