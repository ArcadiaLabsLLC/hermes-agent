"""h-chatperf: the loop's provider-span stamps fire from the REAL loop, in order.

Cold turn ``1e4c06ba`` (2026-10-03) spent 2.6 s between
``provider_request_started`` and ``request_assembled`` with nothing inside it
but ``turn_context_ms``. The loop now announces four instants inside that span
(``conversation_started``, ``turn_context_built``, ``preflight_done``,
``request_built``). This drives the real ``run_conversation`` with a mocked
client and asserts they reach ``status_callback`` in the order the turn passes
them, all before the provider call.

Named sabotage: delete ``_emit_phase_marker(agent, CONVERSATION_REQUEST_BUILT_STEP)``
from ``agent/conversation_loop.py`` -- ``request_built`` goes missing and the
order row reds.
"""

from __future__ import annotations

from unittest.mock import patch

from agent_runtime.conversation_observability import (
    CONVERSATION_PROVIDER_RETURNED_STEP,
    CONVERSATION_PREFLIGHT_DONE_STEP,
    CONVERSATION_REQUEST_ASSEMBLED_STEP,
    CONVERSATION_REQUEST_BUILT_STEP,
    CONVERSATION_STARTED_STEP,
    CONVERSATION_TURN_CONTEXT_BUILT_STEP,
)
from agent_runtime.persona_turn_binding import bind_persona_turn_agent
from tests.agent.test_request_assembled_marker import loop_agent  # noqa: F401 - fixture

_STEPS = (
    CONVERSATION_STARTED_STEP,
    CONVERSATION_TURN_CONTEXT_BUILT_STEP,
    CONVERSATION_PREFLIGHT_DONE_STEP,
    CONVERSATION_REQUEST_BUILT_STEP,
    CONVERSATION_REQUEST_ASSEMBLED_STEP,
    CONVERSATION_PROVIDER_RETURNED_STEP,
)


def test_loop_stamps_fire_in_turn_order_before_the_provider_call(loop_agent):  # noqa: F811
    from tests.agent.test_run_agent import _mock_response

    order: list[str] = []

    def _observe(payload):
        if isinstance(payload, dict) and payload.get("phase") == "timing" and payload.get("step") in _STEPS:
            order.append(payload["step"])

    loop_agent.status_callback = _observe

    def _provider_call(*args, **kwargs):
        order.append("provider_call")
        return _mock_response(content="done.", finish_reason="stop")

    loop_agent.client.chat.completions.create.side_effect = _provider_call
    with (
        patch.object(loop_agent, "_persist_session"),
        patch.object(loop_agent, "_save_trajectory"),
        patch.object(loop_agent, "_cleanup_task_resources"),
        bind_persona_turn_agent(loop_agent),
    ):
        result = loop_agent.run_conversation("say done")

    assert result["final_response"], "the mocked turn must actually complete"
    assert order == [*_STEPS[:-1], "provider_call", CONVERSATION_PROVIDER_RETURNED_STEP], order
