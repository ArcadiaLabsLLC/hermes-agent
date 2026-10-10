"""Every provider dispatch logs the reasoning effort its request carried (``api_call_effort``).

The fork's ``chat_turn_effort`` receipt is per run; a per-call effort (a fallback re-resolve, a
mid-turn switch) was unlogged, so a turn could not be proven low from the log. The
``llm_execution`` middleware sees the assembled request and names the effort per call.
"""

from __future__ import annotations

import logging

import pytest

from agent_runtime.conversation_observability import time_provider_dispatch
from agent_runtime.request_effort import request_effort


@pytest.mark.parametrize(("request_payload", "effort"), [
    ({"reasoning_effort": "low"}, "low"),
    ({"reasoning": {"effort": "high", "summary": "auto"}}, "high"),
    ({"extra_body": {"reasoning": {"enabled": False, "effort": "none"}}}, "none"),
    ({"extra_body": {"reasoning_effort": "minimal"}}, "minimal"),
    ({"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}}, "medium"),
    ({"thinking": {"type": "enabled", "budget_tokens": 2048}}, "budget:2048"),
    ({"thinking": {"type": "disabled"}}, "none"),
    ({"messages": []}, "-"),
    (None, "-"),
])
def test_the_request_names_its_effort(request_payload, effort):
    assert request_effort(request_payload) == effort


def test_a_dispatch_logs_the_effort_its_request_carried(caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.conversation_observability")

    result = time_provider_dispatch(
        {"model": "gpt-5", "reasoning": {"effort": "low"}}, lambda: "reply",
        api_call_count=3, api_mode="codex_responses", provider="openai-codex", model="gpt-5")

    assert result == "reply"
    receipts = [r.getMessage() for r in caplog.records if r.getMessage().startswith("api_call_effort ")]
    assert receipts == ["api_call_effort call=3 model=gpt-5 provider=openai-codex effort=low"]
