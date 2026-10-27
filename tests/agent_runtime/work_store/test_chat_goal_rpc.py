"""``runtime.chat.goal.*`` over upstream's ``GoalManager``, and the after-turn hook's slot rule (B3).

Dispatcher plan ``docs/agent-runtime-harness/archive/dispatcher-and-libraries-2026-10-18.md`` §5, §6.
The RPC tests drive the registered handlers with the REAL ``GoalManager`` on this test's isolated home
(SessionDB ``state_meta``); the slot test uses the goal fakes and the real send queue.

Killing mutation: the after-turn hook forges the continuation while an operator send is queued (drop
the ``waiting`` hold in ``goal_turns._forge``) → ``test_operator_send_wins_slot`` red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_goal, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.serve_rpc import _METHODS, _METHOD_TIERS
from agent_runtime.work_store.executor import Assignment, Brief, GoalMode
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor

from tests.agent_runtime._serve_rpc_manifest import expected_manifest
from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

SESSION = "persona_chat_root_rpc"
VERBS = ("set", "status", "pause", "resume", "clear")


def _call(verb, **params):
    replies: list = []
    context = SimpleNamespace(spawn_reply=lambda reply: replies.append(reply()) or True, caller=None)
    assert _METHODS[f"runtime.chat.goal.{verb}"](7, params, context) == {"deferred": True}
    [reply] = replies
    return reply


def test_the_five_verbs_are_console_methods_in_the_manifest():
    manifest = expected_manifest()
    for verb in VERBS:
        name = f"runtime.chat.goal.{verb}"
        assert _METHOD_TIERS[name] == "console" and name in manifest["methods"]
        assert manifest["tiers"][name] == "console"


def test_set_status_pause_resume_clear_round_trip_through_goal_manager():
    reply = _call("set", session_id=SESSION, goal="Ship the widget", max_turns=5,
                  contract={"outcome": "widget ships"}, gates=["python -c 0"])
    goal = reply["result"]["goal"]
    assert goal["status"] == "active" and goal["goal"] == "Ship the widget" and goal["max_turns"] == 5
    assert goal["contract"]["outcome"] == "widget ships"
    assert [g["command"] for g in goal["gates"]] == ["python -c 0"]
    assert _call("status", session_id=SESSION)["result"]["goal"]["status"] == "active"
    paused = _call("pause", session_id=SESSION, reason="lunch")["result"]["goal"]
    assert paused["status"] == "paused" and paused["paused_reason"] == "lunch"
    assert _call("resume", session_id=SESSION)["result"]["goal"]["status"] == "active"
    assert _call("clear", session_id=SESSION)["result"]["goal"]["status"] == "cleared"


@pytest.mark.parametrize(("verb", "params", "code", "reason"), [
    ("status", {}, -32602, "invalid_request"),
    ("set", {"session_id": SESSION, "goal": ""}, -32602, "invalid_request"),
    ("set", {"session_id": SESSION, "goal": "x", "gates": "not a list"}, -32602, "invalid_request"),
    ("pause", {"session_id": "persona_chat_root_none"}, 4001, "no_goal"),
])
def test_refusals_are_typed(verb, params, code, reason):
    reply = _call(verb, **params)
    assert reply["error"]["code"] == code and reply["error"]["data"]["reason"] == reason


def test_status_names_the_work_run_that_owns_the_goal():
    chat_goal.bind(chat_goal.GoalBinding(SESSION, "rid-9", (("s", "n", "RT-9"),)))
    _call("set", session_id=SESSION, goal="Own it")
    assert _call("status", session_id=SESSION)["result"]["goal"]["run"] == "rid-9"


ROOT = "persona_chat_root_slot"
REF = RowRef("repo", "Repo_Brain/20 — Active Initiatives/q.md", "RT-S")


def test_operator_send_wins_slot():
    """A turn ends wanting a continuation while an operator send waits: nothing is forged; the
    operator's turn runs, is judged as a user turn, and the continuation is forged after it."""

    goals = FakeGoals()
    instances = SimpleNamespace(get=lambda _id: SimpleNamespace(id="inst-1", persona_id="neko",
                                                                runtime_root=str(paths.store_root())))
    executor = PersonaTurnExecutor(instances=instances, root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   goals=goals, workdir_of=lambda instance: None)
    brief = Brief(title="t", objective="Do it.", tests=("python -c 0",))
    run = executor.start(Assignment((REF,), "inst-1", brief, "rid-slot", goal_mode=GoalMode.UNTIL_DONE))
    send_queue.mark(ROOT, run.client_message_id, state=send_queue.STATE_RUNNING)
    send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "operator"}, "message": "wait!"})
    goals(ROOT).decisions += [decision("continue", go_on=True), decision("continue", go_on=True)]

    executor.settled(send_queue.find(ROOT, run.client_message_id), 0, {"ok": True, "reply": "turn one"})
    send_queue.remove(ROOT, run.client_message_id)
    assert [e.client_message_id for e in send_queue.entries(ROOT)] == ["operator-1"]
    assert chat_goal.binding(ROOT).held is True

    executor.settled(send_queue.find(ROOT, "operator-1"), 0, {"ok": True, "reply": "operator turn"})
    send_queue.remove(ROOT, "operator-1")
    assert [e.client_message_id for e in send_queue.entries(ROOT)] == [f"{run.client_message_id}-g2"]
    assert goals(ROOT).evaluated == [("turn one", False), ("operator turn", True)]
    assert chat_goal.binding(ROOT).held is False
