"""``RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM``: Stop ends a reply the same way whoever started it.

Read in code 2026-11-21 (w1121a-archaudit): ``stop_operator_execution`` tried three mechanisms in turn — an
until-done pass, a turn the runtime started (``live_turns``), the admitted request's ``InterruptScope`` —
and ``runtime.work.cancel`` on a chat-turn row answered ``cancel_unsupported`` for every reply that was not
an until-done pass: the Activity cancel and the chat's Stop were different functions with different
refusal words. Now every reply registers ONE stop handle when its handler starts
(``live_turns.turn_stop_handle``) and both doors call ``turn_stop.stop_turn``.

The table: a reply from each starter — the operator's send, a send that waited on its busy chat, a
schedule's fire, a Work pass, a goal's next turn, a Lens episode, another agent's relay, a helper's result —
held on a real model call, through the real turn door, stopped through each door (the conversation's Stop,
``runtime.operator.conversation.stop``; the Activity cancel, ``runtime.work.cancel``). Each stops with the
same answer and the same settle.

Killing mutations (reds recorded in the commit body):
* ``chat_admission._within_admitted_turn`` drops ``turn_stop_handle(args)`` → the waiting-reply test red
  (nothing takes the stop when the reply starts, and it calls the model);
* ``live_turns.turn_stop_handle`` binds the scope it was started under instead of its own → the relay rows
  red (the lead's work is stopped with its helper's reply) and the operator-send rows red;
* ``running_work.surface._cancel_chat_turn`` answers ``cancel_unsupported`` for any reply that is not a Work
  pass (the door as it was) → every Activity row but the Work pass red.
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_goal, serve_rpc
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner
from agent_runtime.mission_chat_door import run_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.serde import safe_assignment_token
from agent_runtime.work_store.goal_turns import first_cmid
from agent_runtime.work_store.persona_turn import _turn_args
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, Running, operator_call, operator_params, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
REQUEST = "ws_x:repo:RT-A:2026-11-21:5e2b1c"


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model():
    from hermes_constants import get_hermes_home

    held = HeldModel()
    held.configure(get_hermes_home())
    yield held
    held.close()


class _Chat:
    def __init__(self, placed) -> None:
        self.instance = placed["persona_instance_id"]
        self.root = _call(dict(persona_id=PERSONA, persona_instance_id=self.instance, new_session=True,
                               idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]

    def args(self, cmid: str, requested_by: str):
        return _turn_args(PersonaInstanceStore().get(self.instance), self.root, cmid, "Write the long essay.",
                          requested_by)

    def op(self, method: str, turn: str) -> dict:
        return operator_call(method, operator_params(self.instance, self.root, turn, persona=PERSONA,
                                                     workspace=WORKSPACE))

    def queued(self, cmid: str, requested_by: str) -> send_queue.QueuedSend:
        entry, _position, _replay = send_queue.enqueue(
            self.root, cmid, send_queue.persistable_args(self.args(cmid, requested_by)))
        return entry


@pytest.fixture
def chat(placed_agent) -> _Chat:
    return _Chat(placed_agent)


def _from_queue(chat: _Chat, cmid: str, requested_by: str) -> Running:
    entry = chat.queued(cmid, requested_by)
    return Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))


def _operator_send(chat):
    return "client-send-0001", operator_turn(chat.instance, chat.root, "client-send-0001", "Write the long essay."), None


def _queued_send(chat):
    from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
    from agent_runtime.chat_turn_reservations import reserve_chat_turn

    cmid = "client-send-0002"
    with reserve_chat_turn(turn_request_id=cmid, verb=CHAT_MESSAGE_METHOD, session_scope=chat.root) as reservation:
        reservation.mark_accepted({"queued": True}, request_id="req-2")
    return cmid, _from_queue(chat, cmid, "operator"), None


def _schedule_fire(chat):
    cmid = "task:ws_x:slot:RT-A:20261121T101500Z"
    return cmid, _from_queue(chat, cmid, "schedule:tidy"), None


def _work_pass(chat):
    cmid = first_cmid(REQUEST)
    chat_goal.bind(chat_goal.GoalBinding(chat.root, REQUEST, (), {}, cmid, turns=0))
    return cmid, _from_queue(chat, cmid, f"work:{REQUEST}"), None


def _goal_turn(chat):
    cmid = "goal-0123456789abcdef"
    return cmid, _from_queue(chat, cmid, "goal"), None


def _lens_episode(chat):
    from types import SimpleNamespace

    from agent_runtime.lens.trigger import forge_episode_turn

    cmid = "lens-episode-ep1"
    episode = SimpleNamespace(id="ep1", monitor_id="mon1")
    return cmid, Running(lambda: forge_episode_turn(
        manifest={"persona_id": PERSONA}, episode=episode, message="The meadow sensor tripped.",
        session_id=chat.root, client_message_id=cmid)), None


def _relay(chat):
    """Another agent's inline relay: run under the LEAD's scope, which the Stop must leave alone."""

    from agent.interrupt_scope import InterruptScope, bind_interrupt_scope

    cmid, lead = "relay-from-lead-01", InterruptScope()

    def _run():
        with bind_interrupt_scope(lead):
            return run_mission_chat_turn(chat.args(cmid, "agent_chat"))

    return cmid, Running(_run), lead


def _helper_result(chat):
    from agent_runtime.dispatch_delivery.forge import forge_delivery_turn

    cmid = "bg-completion-async_delegation_5d1e"
    return cmid, Running(lambda: forge_delivery_turn(
        root_session_id=chat.root, persona_id=PERSONA, persona_instance_id=chat.instance,
        message="[Background task finished] the helper's result: done.", client_message_id=cmid)), None


STARTERS = {"operator send": _operator_send, "queued send": _queued_send, "schedule fire": _schedule_fire,
            "Work pass": _work_pass, "goal continuation": _goal_turn, "Lens episode": _lens_episode,
            "relay": _relay, "helper result": _helper_result}


def _conversation_stop(chat: _Chat, cmid: str) -> dict:
    reply = chat.op("stop", cmid)
    assert "result" in reply, reply
    return reply["result"]


def _activity_cancel(chat: _Chat, cmid: str) -> dict:
    reply = serve_rpc.handle_request(dict(jsonrpc="2.0", id="cancel", method="runtime.work.cancel",
                                          params={"work_id": f"chat_turn:{safe_assignment_token(cmid)}"}))
    assert "result" in reply, reply
    assert reply["result"]["status"] == "cancelled", reply
    return reply["result"]


DOORS = {"conversation Stop": _conversation_stop, "Activity cancel": _activity_cancel}
SAME = ("outcome", "owner_observed", "ends", "stopped")


@pytest.mark.parametrize("door", DOORS, ids=list(DOORS))
@pytest.mark.parametrize("starter", STARTERS, ids=list(STARTERS))
def test_stop_ends_the_reply_the_same_way_whoever_started_it(chat, model, starter, door):
    cmid, turn, lead = STARTERS[starter](chat)
    assert model.entered.wait(60), f"the {starter}'s reply never reached the model"

    answer = DOORS[door](chat, cmid)

    expected = {"outcome": "stop_requested", "owner_observed": True, "ends": "now",
                "stopped": "work_run" if starter == "Work pass" else "turn"}
    assert {key: answer.get(key) for key in SAME} == expected, answer
    turn.join(30)  # the model is still held: only the Stop can have ended the reply
    assert not model.release.is_set()
    assert chat.op("status", cmid)["result"]["outcome"] == "stopped"
    if lead is not None:
        assert lead.reason is None, "stopping the relayed reply stopped the lead's own work"


def test_a_reply_still_waiting_in_its_queue_stops_as_it_starts_and_never_reaches_the_model(chat, model):
    cmid = "task:ws_x:slot:RT-A:20261121T111500Z"
    entry = chat.queued(cmid, "schedule:tidy")

    answer = _conversation_stop(chat, cmid)

    assert {key: answer.get(key) for key in SAME} == {
        "outcome": "stop_requested", "owner_observed": True, "ends": "now", "stopped": "turn"}, answer
    Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy())).join(60)
    assert not model.entered.is_set(), "the reply told to stop while it waited still called the model"
    assert send_queue.find(chat.root, cmid) is None
    assert chat.op("status", cmid)["result"]["outcome"] == "stopped"
