"""``RT-STEER-ONLY-STREAMING-TURNS`` (RULED 2026-11-12): a Work turn that streams to no screen takes a steer.

The steer watcher was started only for a turn streaming to a screen, so a steer sent at any other turn was
refused ``no_active_turn`` and the client sent it as a new message that waited for the turn to end. The
owner's ruling: a Work turn takes operator steers (the operator watches it on the board); a forged
delivery or relay turn stays unsteerable, so a background completion's notice is never steered.

Whole turns (``held_model_turn``): a Work pass and a helper-result turn, each run through the real door
with ``stream=False`` and held at the model while the steer arrives through ``submit_mission_chat_steer``.

Killing mutations (reds recorded in the commit body):
* ``_agent_ready_for_steer`` keeps the stream gate for a Work turn → the Work test red (``no_active_turn``);
* the gate dropped for every turn (the reverted 24bf6bb455) → the forged-turn test red (``accepted``).
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, paths
from agent_runtime.dispatch_delivery.forge import forge_delivery_turn
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.work_store.persona_turn import _turn_args
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, Running
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
STEER = "Look at the logs too."


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


@pytest.fixture
def chat(placed_agent) -> tuple[str, str]:
    instance = placed_agent["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    return instance, root


def _steer(root: str) -> dict:
    return submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root, message=STEER,
                                     client_message_id="steer-1")


def test_a_work_turn_that_streams_to_no_screen_takes_a_steer(chat, model):
    instance, root = chat
    cmid = "work-ws_x:repo:RT-A:2026-11-12:e30b7e"
    args = _turn_args(PersonaInstanceStore().get(instance), root, cmid, "Tidy the meadow.",
                      "work:ws_x:repo:RT-A:2026-11-12:e30b7e")
    assert args.stream is False
    entry, _position, _replay = send_queue.enqueue(root, cmid, send_queue.persistable_args(args))
    turn = Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))
    assert model.entered.wait(60), "the Work turn never reached the model"

    ack = _steer(root)

    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.release.set()
    turn.join(60)
    # Accepted is not lost: it reached this turn's model, or it is the root's next queued message.
    read_by_model = any(STEER in text for request in model.requests for text in
                        (str(m.get("content")) for m in request["messages"]))
    queued = any(STEER in str(e.args.get("message")) for e in send_queue.entries(root))
    assert read_by_model or queued, "the accepted steer reached nothing"


def test_a_forged_helper_result_turn_still_refuses_a_steer(chat, model):
    instance, root = chat
    turn = Running(lambda: forge_delivery_turn(
        root_session_id=root, persona_id=PERSONA, persona_instance_id=instance,
        message="[Background task finished] the helper's result: done.",
        client_message_id="bg-completion-async_delegation_7f3a"))
    assert model.entered.wait(60), "the forged turn never reached the model"

    ack = _steer(root)

    assert ack.get("ok") is not True and ack.get("error_kind") == "no_active_turn", ack
    model.release.set()
    turn.join(60)
