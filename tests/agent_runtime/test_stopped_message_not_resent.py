"""``RT-STOPPED-MESSAGE-HOLD-SERVED-AGAIN-NEXT-TURN``: a message you stopped is not sent to the model again.

Seen live 2026-11-12 (Eternia lane w1112b-turn3, hermes 223df1b465): after a reply the QA fixture held
for 120 s was stopped 3 s in, the next message seemed to sit Thinking about two minutes, as if the
stopped message's hold were served again.

NOT reproduced here, and this is what was ruled out, whole (``held_model_turn``): an operator send held
at the model and stopped by the console's Stop; then the next message, with the serve's resident chat
actor on (the stopped turn's agent and its in-memory message list are REUSED) and off. In both the next
turn makes ONE model request, its last user message is the new message alone, the stopped message sits
before it as its own user message closed by the interrupt row, and the turn answers while the stopped
request is still being held by the model — it does not wait for it. (Also run by hand with the fixture's
wire shape, HTTP/1.1 chunked with keep-alive comments: the next turn took 0.4 s.) What is left is outside
this repository's reach without the client: what the console sent and drew.

Killing mutation (red recorded in the commit body): the core closer leaves a stopped turn's tail open
(no boundary row) → both cases red, the stopped message and the next one reach the model as one.
"""

from __future__ import annotations

import pytest

from agent_runtime.persona_chat_continuity import runtime_registry
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, operator_call, operator_params, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
HELD = "[[qa:hold 120000]] Write me a long essay."


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
    runtime_registry.reset_persona_chat_runtime_registry()


@pytest.mark.parametrize("resident", [True, False], ids=["resident_actor", "fresh_agent"])
def test_the_next_message_after_a_stop_reaches_the_model_alone_and_does_not_wait(placed_agent, model, resident):
    runtime_registry.initialize_persona_chat_runtime_registry(enabled=resident)
    instance = placed_agent["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    model.hold = False
    operator_turn(instance, root, "msg-0", "Hello first.").join(60)  # the actor is resident from here on
    model.hold = True
    model.entered.clear()
    stopped = operator_turn(instance, root, "msg-1", HELD)
    assert model.entered.wait(60)
    operator_call("stop", operator_params(instance, root, "msg-1", persona=PERSONA, workspace=WORKSPACE),
                  interrupt_operator=stopped.interrupt_operator)
    _code, payload = stopped.join(30)
    assert payload["stopped"] is True
    model.hold = False
    sent_before = len(model.requests)

    _code, payload = operator_turn(instance, root, "msg-2", "Thanks anyway.").join(30)

    assert not model.release.is_set(), "the stopped request was let go: this no longer proves the turn did not wait"
    assert bool(payload["profile_timing"].get("resident_actor_reused")) is resident
    assert payload["reply"] == "Thanks, noted."
    assert len(model.requests) - sent_before == 1, "the next message made more than one model request"
    request = model.requests[-1]["messages"]
    users = [str(m["content"]) for m in request if m["role"] == "user"]
    assert users[-1].startswith("Thanks anyway.") and "[[qa:hold" not in users[-1], users[-1][:200]
    assert sum(HELD in text for text in users) == 1, "the stopped message is not in the request exactly once"
    at = next(i for i, m in enumerate(request) if m["role"] == "user" and HELD in str(m["content"]))
    assert request[at + 1]["role"] == "assistant", "the stopped message's tail is open: the next one merges into it"
