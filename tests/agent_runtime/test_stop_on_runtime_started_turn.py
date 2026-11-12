"""``RT-STOP-ON-RUNTIME-STARTED-TURN-IS-REFUSED``: Stop works on a reply the agent started by itself.

Seen live 2026-11-12 (Eternia lane w1112b-turn3): the chat's Stop on Base's own turn for a helper's result
(turn ``bg-completion-async_delegation_…``) answered ``execution_not_admitted`` and the turn ran on. Only an
operator send holds an admission receipt; every turn the runtime starts for itself — a background
completion or a dispatch reply forged through the mission-chat door, a schedule fire / Work pass / goal turn
/ leftover steer / platform message run from the send queue — has none and is not in the serve's in-flight
table, the only two things ``runtime.operator.conversation.stop`` could stop. ``fc7a627c02`` closed it for an
until-done pass alone.

Driven whole (``held_model_turn``): a real instance and chat root, the turn run through the real door to
a real model call that is waiting when the console's Stop arrives through ``serve_rpc.handle_request``.

Killing mutations (reds recorded in the commit body):
* ``stop_operator_execution`` skips ``_stop_live_turn`` (the code as it was) → both Stop tests red
  (``execution_not_admitted``);
* ``live_turns.interrupt_turn`` ignores ``session_id`` → the other-conversation control red (the turn is stopped
  by a Stop sent to a different chat);
* ``execution_status`` drops ``_journal_by_turn_id`` → the queued-run test red (status stays ``unsettled``).
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner
from agent_runtime.dispatch_delivery.forge import forge_delivery_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.serde import safe_assignment_token
from agent_runtime.work_store.persona_turn import _turn_args
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, Running, operator_call, operator_params
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
NOT_PROCESSED = "Your request was not processed"


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
        self.root = self.new_root("chat-1")

    def new_root(self, key: str) -> str:
        return _call(dict(persona_id=PERSONA, persona_instance_id=self.instance, new_session=True,
                          idempotency_key=key, client_scope=OWNER))["result"]["session_id"]

    def op(self, method: str, turn: str, *, root: str | None = None) -> dict:
        return operator_call(method, operator_params(self.instance, root or self.root, turn,
                                                     persona=PERSONA, workspace=WORKSPACE))

    def rows(self) -> list[dict]:
        from hermes_state import SessionDB

        return SessionDB().get_messages(self.root)


@pytest.fixture
def chat(placed_agent) -> _Chat:
    return _Chat(placed_agent)


def _forged_completion(chat: _Chat, cmid: str) -> Running:
    """The background-completion drain's own forge (``BackgroundDrain.forge_turn``), on its own thread."""

    return Running(lambda: forge_delivery_turn(
        root_session_id=chat.root, persona_id=PERSONA, persona_instance_id=chat.instance,
        message="[Background task finished] the helper's result: done.", client_message_id=cmid))


def test_stop_on_a_helper_result_reply_is_accepted_and_the_reply_stops(chat, model):
    cmid = "bg-completion-async_delegation_7f3a"
    turn = _forged_completion(chat, cmid)
    assert model.entered.wait(60), "the forged turn never reached the model"

    reply = chat.op("stop", cmid)

    assert "result" in reply, reply
    assert {k: reply["result"][k] for k in ("turn_request_id", "outcome", "admitted", "stop_requested",
                                            "owner_observed", "dependent_dispatches")} == {
        "turn_request_id": cmid, "outcome": "stop_requested", "admitted": False, "stop_requested": True,
        "owner_observed": True, "dependent_dispatches": []}
    ok, payload = turn.join(30)  # the model is still held: only the Stop can have ended the turn
    assert not model.release.is_set()
    # Delivered, not a failed delivery: the drain must not forge the same result again.
    assert ok is True and payload["reply"] == "" and str(payload["execution_state"].value) == "stopped"
    assert chat.op("status", cmid)["result"]["outcome"] == "stopped"
    said = [str(row.get("content") or "") for row in chat.rows() if row["role"] == "assistant"]
    assert not any(NOT_PROCESSED in text for text in said), said


def test_stop_on_a_turn_run_from_the_send_queue_is_accepted_by_its_turn_id(chat, model):
    """A schedule fire / Work pass / goal turn: queued by the runtime, run by the queued-send runner.

    The console names it by its running-work row, ``chat_turn:<turn id>`` — the client message id with
    its ``:`` spelled ``_`` — so the Stop and the status read after it must both know that spelling.
    """

    cmid = "task:ws_x:slot:RT-A:20261112T101500Z"
    instance = PersonaInstanceStore().get(chat.instance)
    args = send_queue.persistable_args(_turn_args(instance, chat.root, cmid, "Tidy the meadow.", "schedule:tidy"))
    entry, _position, _replay = send_queue.enqueue(chat.root, cmid, args)
    turn = Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))
    assert model.entered.wait(60), "the queued turn never reached the model"
    turn_id = safe_assignment_token(cmid)
    assert turn_id != cmid

    reply = chat.op("stop", turn_id)

    assert reply.get("result", {}).get("outcome") == "stop_requested", reply
    assert reply["result"]["owner_observed"] is True and reply["result"]["admitted"] is False
    turn.join(30)
    assert not model.release.is_set()
    assert send_queue.find(chat.root, cmid) is None, "the stopped turn is still on the root's queue"
    assert chat.op("status", turn_id)["result"]["outcome"] == "stopped"
    assert chat.op("status", cmid)["result"]["outcome"] == "stopped"


def test_a_stop_that_names_no_running_turn_of_this_conversation_is_refused_as_before(chat, model):
    cmid = "bg-completion-async_delegation_9c1d"
    other_root = chat.new_root("chat-2")
    turn = _forged_completion(chat, cmid)
    assert model.entered.wait(60)

    unknown = chat.op("stop", "bg-completion-never-ran")
    from_other_chat = chat.op("stop", cmid, root=other_root)

    assert unknown["error"]["data"] == {"reason": "execution_not_admitted"}, unknown
    assert from_other_chat["error"]["data"] == {"reason": "execution_not_admitted"}, from_other_chat
    assert turn.thread.is_alive(), "a Stop sent to another conversation stopped this one's turn"
    model.release.set()
    ok, payload = turn.join(60)
    assert ok is True and payload["reply"] == "Thanks, noted."


def test_stop_on_an_admitted_send_that_ran_from_the_queue_reaches_the_turn(chat, model):
    """An operator send that waited for its busy root holds a receipt but is run by the queued-send runner:
    the serve's in-flight table (``interrupt_operator`` answers False) does not hold it, the live table does."""

    from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
    from agent_runtime.chat_turn_reservations import reserve_chat_turn

    cmid = "client-send-0042"
    with reserve_chat_turn(turn_request_id=cmid, verb=CHAT_MESSAGE_METHOD, session_scope=chat.root) as reservation:
        reservation.mark_accepted({"queued": True}, request_id="req-1")
    instance = PersonaInstanceStore().get(chat.instance)
    args = send_queue.persistable_args(_turn_args(instance, chat.root, cmid, "Tidy the meadow.", "operator"))
    entry, _position, _replay = send_queue.enqueue(chat.root, cmid, args)
    turn = Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))
    assert model.entered.wait(60)

    reply = chat.op("stop", cmid)

    assert reply.get("result", {}).get("outcome") == "stop_requested", reply
    assert reply["result"]["admitted"] is True and reply["result"]["owner_observed"] is True
    turn.join(30)
    assert not model.release.is_set(), "the admitted queued turn ran on after its Stop was accepted"
