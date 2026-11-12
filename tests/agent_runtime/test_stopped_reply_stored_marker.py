"""``RT-STOPPED-REPLY-STORED-CHAT-DOES-NOT-SAY-STOPPED``: the stored chat still says a reply was stopped.

The console's own "You stopped this reply…" line belongs to the live turn and goes with the next send;
from then on the stored chat is the only record. Live 2026-11-12 (Eternia lane w1112b-turn3, hermes
223df1b465) it said nothing: the stopped turn's tail was the "Your request was not processed…" assistant
row, and a turn that holds a reply row gets no terminal marker.

Each case here is a whole turn (``held_model_turn``): an operator send stopped through the console's Stop
(the serve's hard stop) or a runtime-started turn stopped through the live-turn seam, while the real
model call waits — then the NEXT message is sent and answered, and the chat is read back through both
stored-history projections Eternia reads: the persona history (``runtime.operator.conversation.read``)
and the operator-channel conversation (``operator_channels._conversation_contract``).

What the reproduction found on ``b4107444f5``: the persona history already kept the marker in all three
cases — ``bf1e592371`` replaced the notice row with a hidden interrupt row, which is no reply, and
``1dea529702`` stopped counting a half reply marked ``interrupted`` — so those are pinned here, not
changed. The one gap left was the operator-channel conversation, whose marker did not carry
``stopped: true``: there a stop read as a crash ("Turn interrupted").

Killing mutations (reds recorded in the commit body):
* ``HistoryMessage.marker`` drops ``stopped`` → every case red on the conversation projection;
* ``_AgentCurator.before_curation`` counts a half reply marked ``interrupted`` as the turn's reply → the
  half-written case red (no marker at all);
* the core closer writes the failed-turn notice for a stopped turn again → the nothing-written and
  helper-result cases red (the notice row is a reply, so no marker).
"""

from __future__ import annotations

import pytest

from agent_runtime.dispatch_delivery.forge import forge_delivery_turn
from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.persona_chat_history.vocabulary import STOPPED_TURN_MARKER_TEXT
from tests.agent_runtime.held_model_turn import (
    OWNER, HeldModel, Running, operator_call, operator_params, operator_turn,
)
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
STOPPED = "stopped-turn"
NEXT = "next-message"


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


def _stop_an_operator_reply(instance: str, root: str, model: HeldModel) -> None:
    turn = operator_turn(instance, root, STOPPED, "Write me a long essay.")
    assert model.entered.wait(60), "the turn never reached the model"
    reply = operator_call("stop", operator_params(instance, root, STOPPED, persona=PERSONA, workspace=WORKSPACE),
                          interrupt_operator=turn.interrupt_operator)
    assert reply["result"]["owner_observed"] is True, reply
    _code, payload = turn.join(30)
    assert payload["stopped"] is True and payload["reply"] == model.partial


def _stop_a_helper_result_reply(instance: str, root: str, model: HeldModel) -> None:
    turn = Running(lambda: forge_delivery_turn(
        root_session_id=root, persona_id=PERSONA, persona_instance_id=instance,
        message="[Background task finished] the helper's result: done.", client_message_id=STOPPED))
    assert model.entered.wait(60), "the turn never reached the model"
    reply = operator_call("stop", operator_params(instance, root, STOPPED, persona=PERSONA, workspace=WORKSPACE))
    assert reply["result"]["owner_observed"] is True, reply
    turn.join(30)


@pytest.mark.parametrize(
    ("stop", "partial"),
    [(_stop_an_operator_reply, ""), (_stop_an_operator_reply, "The first half of the answer"),
     (_stop_a_helper_result_reply, "")],
    ids=["nothing_written", "half_written", "helper_result_reply"],
)
def test_a_stopped_reply_still_says_stopped_after_the_next_message(placed_agent, model, stop, partial):
    instance = placed_agent["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    model.partial = partial
    stop(instance, root, model)
    model.hold = False
    _code, payload = operator_turn(instance, root, NEXT, "Thanks anyway.").join(60)
    assert payload["reply"] == "Thanks, noted."

    read = operator_call("read", operator_params(instance, root, None, persona=PERSONA, workspace=WORKSPACE))
    history = read["result"]
    conversation = _conversation_contract(
        channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root, goal_id=None,
        title="Chat", state="idle", history=history, trace=None)

    for name, messages, text_key in (("persona history", history["messages"], "text"),
                                     ("operator conversation", conversation["messages"], "display_text")):
        kinds = [str(m.get("kind") or m.get("role")) for m in messages]
        markers = [m for m in messages if m.get("kind") == "turn_interrupted"]
        assert len(markers) == 1, f"{name}: the stopped turn left no record that it was stopped: {kinds}"
        marker = markers[0]
        assert marker.get("stopped") is True, f"{name}: the marker does not say the stop was the person's"
        assert marker[text_key] == STOPPED_TURN_MARKER_TEXT and marker["client_message_id"] == STOPPED
        at = messages.index(marker)
        before = [m for m in messages[:at] if str(m.get("client_message_id") or "").startswith(STOPPED)]
        after = [m for m in messages[at + 1:] if str(m.get("client_message_id") or "").startswith(STOPPED)]
        assert before and not after, f"{name}: the marker is not the stopped turn's last row: {kinds}"
        assert any(str(m.get("client_message_id") or "") == NEXT for m in messages[at + 1:]), (
            f"{name}: the marker sorted after the next message: {kinds}")
        said = [str(m.get(text_key) or "") for m in messages]
        assert not any("Your request was not processed" in text for text in said), said
        if partial:
            assert partial in said, f"{name}: the half-written reply was not kept: {said}"
