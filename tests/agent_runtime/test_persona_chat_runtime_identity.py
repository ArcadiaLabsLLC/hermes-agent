"""Resolved client changes invalidate reuse, without exposing their secrets."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_runtime.persona_chat_continuity.runtime_registry import (
    PersonaChatRuntimeRegistry,
)
from agent_runtime.profile_runner.execute import AgentRunExecution
from agent_runtime.profile_runner.models import AgentRunRequest


def _execution(registry, runtime, factory):
    request = AgentRunRequest(
        profile=None,
        root_chat_session_id="root",
        session_id="tip",
        persona_chat_runtime_registry=registry,
        persona_chat_runtime_signature="context",
        persona_chat_native_revision="revision",
    )
    execution = AgentRunExecution(None, None, request)
    execution.runtime = deepcopy(runtime)
    execution.construct_agent = factory
    execution.acquire_agent()
    return execution


@pytest.mark.parametrize(
    "field, changed",
    [
        ("base_url", "https://other.invalid/v1"),
        ("api_key", "new-secret"),
        ("api_mode", "responses"),
        ("model", "other-model"),
        ("provider", "other-provider"),
    ],
)
def test_resolved_client_change_rebuilds_and_reports_names_only(field, changed, caplog):
    runtime = dict(
        provider="custom",
        model="model",
        api_mode="chat_completions",
        base_url="https://first.invalid/v1",
        api_key="old-secret",
    )
    factory = Mock(side_effect=lambda: SimpleNamespace(close=Mock()))
    registry = PersonaChatRuntimeRegistry()
    first = _execution(registry, runtime, factory)
    with caplog.at_level("INFO"):
        second = _execution(registry, {**runtime, field: changed}, factory)
    assert second.agent is not first.agent
    first.agent.close.assert_called_once_with()
    assert second.timing["resident_actor_reused"] == 0
    assert second.timing["resident_rebuild_component_resolved_runtime"] == 1
    assert "old-secret" not in caplog.text and "new-secret" not in caplog.text
    assert "first.invalid" not in caplog.text and "other.invalid" not in caplog.text


def test_unchanged_client_reuses_but_clears_turn_state_and_keeps_usage_anchor():
    anchor = {"prompt_tokens": 12}
    agent = SimpleNamespace(
        close=Mock(),
        _usage_anchor=anchor,
        session_prompt_tokens=12,
        _interrupt_requested=True,
        _current_turn_id="old-turn",
    )
    factory = Mock(return_value=agent)
    registry = PersonaChatRuntimeRegistry()
    _execution(registry, {"provider": "custom"}, factory)
    second = _execution(
        registry, {"provider": "custom", "diagnostic_count": 2}, factory
    )
    assert second.agent is agent and factory.call_count == 1
    assert second.timing["resident_actor_reused"] == 1
    assert agent._usage_anchor is anchor
    assert agent.session_prompt_tokens == 0
    assert not agent._interrupt_requested and agent._current_turn_id is None
