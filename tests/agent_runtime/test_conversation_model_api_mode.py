"""RT-CONV-MODEL-SELECT-STALE-API-MODE: a chat switched from Anthropic to ``openai-codex`` ran
every GPT turn on the instance's ``anthropic_messages`` (``…/codex/v1/messages``, a Cloudflare
403). ``api_mode`` belongs to the provider it was chosen with; a chat override onto another
provider derives its own (``agent_runtime/model_api_mode.py::turn_api_mode``). And the 403 whose
body is a challenge page is typed and named by its path (``agent_runtime/provider_challenge.py``).
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.model_api_mode import turn_api_mode
from agent_runtime.profile_runner import AgentRunResult
from tests.agent_runtime.persona_samples import sample_personas


@pytest.mark.parametrize("tier_provider,tier_api_mode,provider,model,expected", [
    ("anthropic", "anthropic_messages", "openai-codex", "gpt-6-sol", "codex_responses"),
    ("openai-codex", "codex_responses", "anthropic", "claude-opus-5-5", "anthropic_messages"),
    # The same provider (an alias of it) keeps the tier's own choice.
    ("anthropic", "chat_completions", "claude", "claude-opus-5-5", "chat_completions"),
])
def test_an_override_onto_another_provider_takes_that_providers_api_mode(
        tier_provider, tier_api_mode, provider, model, expected):
    assert turn_api_mode(tier_provider, tier_api_mode, provider, model) == expected


def test_the_selection_payload_reports_the_override_providers_api_mode():
    from agent_runtime.persona_chat_session import _chat_effective_model_payload

    instance = SimpleNamespace(provider="anthropic", model="claude-opus-5-5",
                               api_mode="anthropic_messages", reasoning_effort=None)
    selection = _chat_effective_model_payload(
        persona=None, config=SimpleNamespace(default_provider=None, default_model=None),
        override={"provider": "openai-codex", "model": "gpt-6-sol"}, instance=instance)

    assert (selection["effective_provider"], selection["effective_api_mode"]) == ("openai-codex", "codex_responses")
    assert selection["reasoning_capabilities"]["api_mode"] == "codex_responses"


class _CapturingRunner:
    request = None

    def run(self, request):
        self.request = request
        return AgentRunResult(final_response="ok", session_id="session_mission_chat",
                              provider=request.provider, model=request.model, base_url=None, messages=[])


def test_the_turn_request_runs_a_chat_override_on_the_selected_providers_api_mode(tmp_path, monkeypatch):
    from agent_runtime.persona_runtime import GPTPersonaRuntime

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    neko = {persona.id: persona for persona in sample_personas()}["neko_supervisor"]
    neko = replace(neko, provider="anthropic", model="claude-opus-5-5", api_mode="anthropic_messages")
    runner = _CapturingRunner()

    GPTPersonaRuntime(default_provider="anthropic", default_model="claude-opus-5-5",
                      agent_runner=runner).mission_chat_reply(
        neko, "hello", permission_session_id="session_mission_chat",
        provider_override="openai-codex", model_override="gpt-6-sol")

    assert (runner.request.provider, runner.request.api_mode) == ("openai-codex", "codex_responses")


# ── the 403 challenge page ──────────────────────────────────────────────────

def _challenge_page(path: str) -> str:
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body>"
            "<p>Enable JavaScript and cookies to continue</p><script>(function(){window._cf_chl_opt={"
            f"cRay:'a4d0006',cUPMDTk:\"{path}?__cf_chl_tk=RJG1BEM2cFlw\"}};"
            "var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1';"
            "}());</script></body></html>")


class _Forbidden(Exception):
    status_code = 403


@pytest.mark.parametrize("path,reason,detail", [
    ("/backend-api/codex/v1/messages", "transport_mismatch",
     ": anthropic_messages sent to openai-codex, which speaks codex_responses"),
    ("/backend-api/codex/responses", "upstream_blocked", ""),
])
def test_a_challenge_403_is_typed_and_names_the_path_it_guarded(monkeypatch, path, reason, detail):
    from agent.error_classifier import FailoverReason, classify_api_error
    from agent.provider_failure import attach_provider_failure
    from agent_runtime.provider_challenge import classify_challenge_refusal
    from hermes_cli import plugins

    monkeypatch.setattr(plugins, "invoke_hook", lambda name, **kwargs: (
        [classify_challenge_refusal(**kwargs)] if name == "transform_api_error_classification" else []))
    classified = classify_api_error(_Forbidden(_challenge_page(path)), provider="openai-codex", model="gpt-6-sol")
    result = {"failed": True}
    attach_provider_failure(result, classified, {})

    assert (classified.reason, classified.retryable) == (FailoverReason.upstream_blocked, False)
    assert result["provider_error"]["reason"] == reason
    assert result["provider_error"]["message"] == f"HTTP 403 — Cloudflare challenge on {path}{detail}"


def test_the_harness_plugin_registers_the_challenge_classifier():
    plugin = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_challenge_under_test", plugin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks: dict[str, list] = {}

    class RecordingCtx:
        def register_hook(self, name, callback):
            hooks.setdefault(name, []).append(callback)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    module.register(RecordingCtx())
    from agent_runtime.provider_challenge import classify_challenge_refusal

    assert hooks.get("transform_api_error_classification") == [classify_challenge_refusal]
