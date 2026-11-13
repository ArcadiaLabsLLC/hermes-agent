"""Stock ``next_prompt`` and Console ``console_next_prompt`` routes coexist; one producer per call.

RT-NEXT-PROMPT-PROVIDER-EVAL, the harness half (plan
``docs/agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md``,
"Auxiliary task compatibility and coexistence"). Only the HTTP boundary is fake: plugin
discovery, the Console settings writer, task routing and the plugin LLM facade are real, so
each request's ``model`` is the route the call actually took.
"""
import json

import httpx
import pytest

import hermes_yaml

from agent_runtime.console_suggestions.generation import generate_suggestion
from agent_runtime.console_suggestions.settings import SuggestionSettings, suggestion_home

_HEAD = {"provider": "custom", "default": "head-fixture", "base_url": "http://127.0.0.1:9999/v1",
         "api_mode": "chat_completions"}
_MESSAGES = [{"role": "user", "content": "continue"}, {"role": "assistant", "content": "explained"}]


@pytest.fixture
def head(tmp_path, monkeypatch):
    """A serving head whose stock ``next_prompt`` slot names its own route; HTTP is recorded."""
    from hermes_cli.plugins import _reset_plugin_managers_for_tests

    home = tmp_path / "head"
    home.mkdir()
    _write(home, {"model": dict(_HEAD),
                  "auxiliary": {"next_prompt": {"provider": "custom", "model": "stock-fixture", "timeout": 7},
                                "console_next_prompt": {"timeout": 19}},
                  "plugins": {"entries": {"eternia-harness": {"enabled": True}}}})
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-no-network")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    requests = []

    def send(client, request, **kwargs):
        assert request.url.host == "127.0.0.1", str(request.url)
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, request=request, json={
            "id": "fixture", "object": "chat.completion", "created": 1, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "next"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13}})

    monkeypatch.setattr(httpx.Client, "send", send)
    _reset_plugin_managers_for_tests()
    try:
        yield home, requests
    finally:
        _reset_plugin_managers_for_tests()


def _write(home, config):
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # JSON is YAML


def _raw(home):
    return hermes_yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))


def _console_route(home, override):
    settings = SuggestionSettings(home)
    settings.write({"expected_revision": settings.read()["settings_revision"], "auxiliary_override": override})


def _stock_route(home, route):
    """The operator edits the stock slot by hand (the Console never writes it)."""
    config = _raw(home)
    config["auxiliary"]["next_prompt"] = route
    _write(home, config)


def test_stock_and_console_routes_set_change_and_reset_independently(head):
    """Mutation: register the Console task with ``inherit_from="next_prompt"``
    (``console_suggestions/generation.py::register_suggestion_task``) -> the first and the reset
    calls go to ``stock-fixture`` / ``stock-two``, red."""
    from agent.auxiliary_client import _resolve_task_provider_model

    home, requests = head
    steps = []

    def suggest(label):
        with suggestion_home(home):
            generate_suggestion(_MESSAGES)
            stock = _resolve_task_provider_model("next_prompt")[1]
        steps.append((label, requests[-1]["model"], stock))

    suggest("inherited, stock override present")
    _console_route(home, {"provider": "custom", "model": "aux-one"})
    suggest("console override set")
    _console_route(home, {"provider": "custom", "model": "aux-two"})
    suggest("console override changed")
    _stock_route(home, {"provider": "custom", "model": "stock-two", "timeout": 7})
    suggest("stock override changed")
    _console_route(home, None)
    suggest("console override reset")
    _stock_route(home, {"timeout": 7})
    suggest("stock override reset")

    assert steps == [
        ("inherited, stock override present", "head-fixture", "stock-fixture"),
        ("console override set", "aux-one", "stock-fixture"),
        ("console override changed", "aux-two", "stock-fixture"),
        ("stock override changed", "aux-two", "stock-two"),
        ("console override reset", "head-fixture", "stock-two"),
        ("stock override reset", "head-fixture", None),
    ]
    config = _raw(home)
    # The Console writer never touched the stock slot, the head model or its own non-route keys.
    assert config["auxiliary"]["next_prompt"] == {"timeout": 7}
    assert config["auxiliary"]["console_next_prompt"] == {"timeout": 19}
    assert config["model"] == _HEAD
    assert len(requests) == len(steps)


def test_a_console_suggestion_call_wakes_no_turn_hook_producer(head, monkeypatch):
    """The stock producer runs from ``pre_llm_call`` / ``post_llm_call`` (catalog
    ``plugin-catalog/next-prompt.yaml``); a Console suggestion is one auxiliary request that fires
    neither, so it cannot set a second producer going. Mutation: have
    ``console_suggestions/generation.py::generate_suggestion`` call
    ``manager.invoke_hook("post_llm_call", ...)`` after its request -> red."""
    from hermes_cli.plugins_dispatch import PluginDispatchMixin

    home, requests = head
    fired = []
    real = PluginDispatchMixin.invoke_hook

    def record(self, hook_name, **kwargs):
        fired.append(hook_name)
        return real(self, hook_name, **kwargs)

    monkeypatch.setattr(PluginDispatchMixin, "invoke_hook", record)
    with suggestion_home(home):
        result = generate_suggestion(_MESSAGES)
        during = list(fired)
        # Positive control: the turn finalizer's own seam is what the recorder sees.
        from hermes_cli.lifecycle import invoke_hook
        invoke_hook("post_llm_call", session_id="control", platform="cli")
    assert result["text"] == "next"
    assert len(requests) == 1
    assert not {"pre_llm_call", "post_llm_call"} & set(during), during
    assert fired[len(during):] == ["post_llm_call"]
