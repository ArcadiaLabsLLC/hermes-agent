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


def organization_refusal():
    """The recorded Anthropic 403 an organization that forbids OAuth sign-in answers."""
    error = Exception("provider refusal")
    error.status_code = 403
    error.body = {
        "type": "error",
        "error": {
            "type": "permission_error",
            "message": "OAuth authentication is currently not allowed for this organization.",
            "details": {"error_code": "oauth_not_allowed_for_organization"},
        },
        "request_id": "req_011ChEwxi3kH4muCfmQadXWv",
    }
    return error


def test_organization_refusal_reports_the_providers_code(agent):
    agent.client.chat.completions.create.side_effect = organization_refusal()
    block = agent.run_conversation("test")["provider_error"]
    assert block["reason"] == "oauth_not_allowed_for_organization"
    assert block["failure_reason"] == "auth"


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


def test_an_html_error_page_reaches_the_block_as_its_typed_summary_not_the_body(agent):
    # A proxy's 404 page reached the launcher as "<!DOCTYPE html>…" in the refusal block's
    # `message`; the block carries the one-line summary the serve logs, the body stays in the log.
    page = "<!DOCTYPE html><html><head><title>Not Found</title></head><body>" + "x" * 400 + "</body></html>"
    error = Exception(page)
    error.status_code = 404
    agent.client.chat.completions.create.side_effect = error
    result = agent.run_conversation("test")
    block = result["provider_error"]
    assert block["status_code"] == 404
    assert block["message"] == "HTTP 404 — Not Found"


def test_a_saved_failed_turns_error_card_names_the_providers_own_refusal_code(agent):
    # The live refusal card said "does not allow this kind of sign-in", but the failed turn's saved
    # row read "Sign in to that provider again": its error_surface carried only `code: auth`.
    # MUTATION: drop the `surface.update(provider_code_fields(result))` call in
    # agent/error_surface.py::build_error_surface_from_result and this test reddens.
    from agent.conversation_loop import _failed_turn_display_metadata

    agent.client.chat.completions.create.side_effect = organization_refusal()
    result = agent.run_conversation("test")
    surface = _failed_turn_display_metadata(agent, result)["error_surface"]
    assert surface["provider_code"] == "oauth_not_allowed_for_organization"
    assert surface["code"] == "auth"  # other clients branch on `code`; it stays the classifier's


def test_a_refusal_without_a_detail_code_names_no_provider_code(agent):
    # The block's `reason` is the classifier's evidence (`error.type` here), not the provider's
    # `details.error_code`, so the card must not read it as one.
    # MUTATION: make provider_code_fields skip the DETAIL_CODE_MARKER test and this test reddens.
    from agent.error_surface import build_error_surface_from_result

    agent.client.chat.completions.create.side_effect = sdk_error(401, "invalid_api_key")
    with patch.object(agent, "_summarize_api_error", side_effect=lambda _: "Changed wording"):
        result = agent.run_conversation("test")
    assert result["provider_error"]["reason"] == "invalid_api_key"
    assert "provider_code" not in build_error_surface_from_result(result, provider="openai")
