"""Terminal evidence belongs to the failed attempt, not its display text."""

from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


@pytest.fixture
def agent():
    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI"),
    ):
        value = AIAgent(
            api_key="synthetic-test-key", provider="openai", model="test-model",
            api_mode="chat_completions", base_url="http://127.0.0.1:1/v1",
            quiet_mode=True, skip_context_files=True, skip_memory=True,
        )
    value.client = MagicMock()
    value._cached_system_prompt = "Test"
    value._use_prompt_caching = value.compression_enabled = value.save_trajectories = False
    with (
        patch.object(value, "_persist_session"),
        patch.object(value, "_save_trajectory"),
        patch.object(value, "_cleanup_task_resources"),
        patch.object(value, "_try_activate_fallback", return_value=False),
        patch.object(value, "_recover_with_credential_pool", return_value=(False, False)),
        patch("agent.turn_recovery_autorecover.auto_recover_after_exhaustion", return_value=None),
    ):
        yield value


def sdk_error(status, kind):
    error = Exception("provider refusal")
    error.status_code = status
    error.body = {"error": {"type": kind, "message": "Try later", "reset_at": 1893456000}}
    return error


@pytest.mark.parametrize("status,kind", [(401, "invalid_api_key"), (429, "usage_limit_reached"), (503, "overloaded")])
def test_terminal_native_result_carries_its_own_provider_evidence(agent, status, kind):
    agent.client.chat.completions.create.side_effect = sdk_error(status, kind)
    with patch.object(agent, "_summarize_api_error", side_effect=lambda _: "Changed wording"):
        result = agent.run_conversation("test")
    assert agent.client.chat.completions.create.called
    assert result["failed"] is True
    block = result["provider_error"]
    assert block["status_code"] == status
    assert block["reason"] == kind
    assert block["provider"] == "openai"
    assert block["model"] == "test-model"


def test_recovered_error_never_labels_a_later_failure_or_turn(agent):
    quota = sdk_error(429, "usage_limit_reached")
    agent.client.chat.completions.create.side_effect = [quota, ValueError("local validation failed")]
    with patch.object(agent, "_recover_with_credential_pool", side_effect=[(True, True), (False, False)]):
        result = agent.run_conversation("test")
    assert agent.client.chat.completions.create.call_count == 2
    assert result["failed"] is True
    assert result["provider_error"]["status_code"] is None
    assert result["provider_error"].get("reason") != "usage_limit_reached"
    agent.client.chat.completions.create.side_effect = RuntimeError("cannot schedule new futures after interpreter shutdown")
    result = agent.run_conversation("second turn")
    assert result["failure_reason"] == "interpreter_shutdown"
    assert "provider_error" not in result
