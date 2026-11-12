"""``RT-STOPPED-HELPER-RESULT-SAYS-NOT-PROCESSED``: a stopped helper's result does not say "not processed".

Seen live 2026-11-12 (Eternia lane w1112b-turn5, hermes b2d9d99738, picture 08): a helper stopped from the
Activity list handed its result back to the parent chat as "Partial output: Your request was not
processed. Send it again if you still want me to carry it out."

Reproduced whole: an operator send whose model calls ``delegate_task``, the helper's own model call held
(``held_model_turn``), ``runtime.work.cancel`` on the helper's running-now row (the Activity list's
"Cancel it"), and the real delivery drain forging the result turn — the text asserted on is what the
parent's model was sent. The sentence is the core's failed-turn boundary: the stopped child's closer wrote
it into the CHILD's transcript (its interrupt reason is "parent delegation ended", not a person's stop),
and the delegation result takes the child's last assistant text as its partial output. A helper has no
person to send anything again; its tail is now closed with the hidden interrupt row, as a stopped reply's
is, so the result quotes only what the helper really wrote.

Killing mutations (reds recorded in the commit body):
* ``_close_durable_failed_turn`` drops ``or _helper_ended_by_its_delegation(agent, result)`` → the
  nothing-written case red (the sentence is back; a helper that had written half a reply has a closed tail
  and never got the boundary — that case pins that its own words are what the result quotes);
* ``_helper_ended_by_its_delegation`` drops its ``_delegate_depth`` check, or answers for any recorded
  reason → the control red.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from agent.conversation_loop import _helper_ended_by_its_delegation
from agent.interrupt_control import HELPER_DELEGATION_ENDED_REASON
from agent_runtime import serve_rpc
from agent_runtime.dispatch_delivery import start_delivery_drain
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
ASK = "Please delegate the star count."
GOAL = "HELPER-GOAL: count the stars."
NOT_PROCESSED = "Your request was not processed"


@pytest.fixture
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model(chat_head):
    """The parent delegates, the helper's call is held, the delivered result is acknowledged."""
    from hermes_constants import get_hermes_home

    held = HeldModel()

    def _users(body) -> list[str]:
        return [str(m.get("content")) for m in body["messages"] if m.get("role") == "user"]

    def _reply(body):
        last = body["messages"][-1]
        if last.get("role") == "tool":
            return "Dispatched.", "stop"
        if "ASYNC DELEGATION" in str(last.get("content")):
            return "Noted the result.", "stop"
        return {"role": "assistant", "tool_calls": [{
            "index": 0, "id": "call_1", "type": "function",
            "function": {"name": "delegate_task", "arguments": json.dumps({"goal": GOAL})}}]}, "tool_calls"

    held.hold_if = lambda body: _users(body)[:1] == [GOAL]  # the helper: its goal is its first message
    held.reply = _reply
    held.configure(get_hermes_home())
    stop = threading.Event()
    start_delivery_drain(stop_event=stop, interval_seconds=0.3)  # the serve's drain: delegations run detached
    yield held
    stop.set()
    held.close()


@pytest.mark.parametrize("partial", ["", "Twelve stars so far"], ids=["nothing_written", "half_written"])
def test_a_stopped_helpers_result_quotes_only_what_the_helper_wrote(placed_agent, model, partial):
    from tools import async_delegation

    instance = placed_agent["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    model.partial = partial
    _code, payload = operator_turn(instance, root, "msg-1", ASK).join(90)
    assert payload["reply"] == "Dispatched."
    assert model.entered.wait(60), "the helper never reached the model"
    running = [key for key, record in async_delegation._records.items() if record.get("status") == "running"]
    assert len(running) == 1, async_delegation._records

    cancel = serve_rpc.handle_request(dict(jsonrpc="2.0", id="c", method="runtime.work.cancel",
                                           params=dict(work_id=f"delegation:{running[0]}")), serve_rpc.RpcContext())
    assert cancel["result"]["interrupted"] == 1, cancel

    def _delivered() -> str | None:
        return next((str(r["messages"][-1].get("content")) for r in model.requests
                     if "ASYNC DELEGATION" in str(r["messages"][-1].get("content"))), None)

    deadline = time.monotonic() + 60
    while _delivered() is None:
        assert time.monotonic() < deadline, "the stopped helper's result was never delivered"
        time.sleep(0.2)
    result = _delivered()
    assert "status=interrupted" in result and GOAL in result, result
    assert NOT_PROCESSED not in result, f"the helper's result carries the failed-turn sentence:\n{result}"
    if partial:
        assert f"Partial output:\n{partial}" in result, f"the helper's own words were not kept:\n{result}"


def test_only_a_helper_ended_by_its_delegation_is_spared_the_notice():
    """Controls: an agent a person talks to keeps the notice for this reason, and a helper keeps it for any other."""

    def ended(depth: int, reason: str | None, **result) -> bool:
        agent = SimpleNamespace(_delegate_depth=depth, _turn_cleared_interrupt_reason=reason)
        return _helper_ended_by_its_delegation(agent, {"interrupted": True, **result})

    assert ended(1, HELPER_DELEGATION_ENDED_REASON) is True
    assert ended(0, HELPER_DELEGATION_ENDED_REASON) is False, "a top-level turn is not a helper"
    assert ended(1, "gateway shutdown") is False and ended(1, None) is False, "another interrupt keeps the notice"
    assert ended(1, HELPER_DELEGATION_ENDED_REASON, failed=True) is False
    assert ended(1, HELPER_DELEGATION_ENDED_REASON, interrupted=False) is False


def test_the_reason_is_the_one_a_delegation_stops_its_child_with():
    import inspect

    from tools.delegate_tool_child_run import _signal_child_stop

    assert inspect.signature(_signal_child_stop).parameters["tool_reason"].default == HELPER_DELEGATION_ENDED_REASON
