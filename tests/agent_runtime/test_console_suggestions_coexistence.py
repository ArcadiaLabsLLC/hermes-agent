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
    """Mutations: a Console reset that copies the stock slot's route
    (``console_suggestions/settings.py::SuggestionSettings.write``) -> the reset call goes to
    ``stock-two``, red; a dual read of ``auxiliary.next_prompt`` when the Console slot names no
    route (``agent/auxiliary_task_config.py::_task_config``) -> the first call goes to
    ``stock-fixture``, red."""
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


# The stock plugin's post_llm_call platform allowlist (``_UI_PLATFORMS`` in
# soymarketing/hermes-plugin-next-prompt at the catalog's pinned sha; recorded in
# ``docs/agent-runtime-harness/archive/console-next-prompt-2026-10-26.md``): empty, desktop, tui.
_STOCK_UI_PLATFORMS = ("", "desktop", "tui")


def _install_stock_standin(home, ledger):
    """A user plugin shaped like the external stock producer: it hooks ``post_llm_call`` behind
    the stock Desktop allowlist and records each suggestion it would draw."""
    plugin = home / "plugins" / "next-prompt-standin"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(json.dumps({"name": "next-prompt-standin"}), encoding="utf-8")
    (plugin / "__init__.py").write_text(
        "import json\n\n"
        f"_UI_PLATFORMS = {set(_STOCK_UI_PLATFORMS)!r}\n\n"
        "def register(ctx):\n"
        "    def _on_post_llm_call(platform=None, session_id=None, **kwargs):\n"
        "        if (platform or '') not in _UI_PLATFORMS:\n"
        "            return\n"
        f"        with open({str(ledger)!r}, 'a', encoding='utf-8') as out:\n"
        "            out.write(json.dumps({'platform': platform, 'session_id': session_id}) + '\\n')\n"
        "    ctx.register_hook('post_llm_call', _on_post_llm_call)\n",
        encoding="utf-8")
    config = _raw(home)
    config["plugins"]["enabled"] = ["eternia-harness", "next-prompt-standin"]
    _write(home, config)


def _drawn(ledger):
    if not ledger.exists():
        return []
    return [json.loads(line)["platform"] for line in ledger.read_text(encoding="utf-8").splitlines()]


def _completions(requests):
    """Model requests the fake served; a turn's own model-metadata probe (``{"name": ...}``) is not one."""
    return sum("messages" in body for body in requests)


def _turn(platform):
    """One real turn through ``run_conversation`` and its finalizer; only the model client is fake."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from run_agent import AIAgent

    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="explained", tool_calls=None),
                                 finish_reason="stop")], model="head-fixture", usage=None)
    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI", return_value=client),
        patch("agent.model_metadata.fetch_model_metadata", return_value={}),
        patch("agent.title_generator.maybe_auto_title", lambda *a, **k: None),
    ):
        agent = AIAgent(api_key="fixture-no-network", base_url="http://127.0.0.1:9999/v1", model="head-fixture",
                        quiet_mode=True, skip_context_files=True, skip_memory=True, platform=platform)
        agent._cached_system_prompt = "You are helpful."
        agent.skip_background_review = True
        result = agent.run_conversation("continue")
    assert result["final_response"] == "explained"
    assert client.chat.completions.create.call_count == 1
    return result["messages"]


def test_a_console_turn_with_the_stock_plugin_installed_draws_one_suggestion(head):
    """The plan leaves the stock plugin's allowlist alone and asks that one Console turn get one
    producer (``console-next-prompt-completion-2026-10-27.md``, "Do not install or enable the
    stock Desktop plugin"). A Console turn runs on ``persona_runtime.PERSONA_CHAT_SCRATCH_SOURCE``,
    which the stock allowlist does not admit, so its finalizer wakes the stand-in for nothing and
    the Console producer's one request is the turn's only suggestion. Positive control: the same
    turn on ``desktop`` draws the stand-in's. Mutations: ``tool`` added to the stand-in's
    allowlist (``_STOCK_UI_PLATFORMS``) -> two producers, red; ``PERSONA_CHAT_SCRATCH_SOURCE`` set
    to ``desktop`` (``agent_runtime/persona_runtime.py``) -> two producers, red."""
    from agent_runtime.persona_runtime import PERSONA_CHAT_SCRATCH_SOURCE

    home, requests = head
    ledger = home / "standin-drawn.jsonl"
    _install_stock_standin(home, ledger)
    with suggestion_home(home):
        messages = _turn(PERSONA_CHAT_SCRATCH_SOURCE)
        assert generate_suggestion(messages)["text"] == "next"
    assert (_completions(requests), _drawn(ledger)) == (1, [])

    with suggestion_home(home):
        _turn("desktop")
    assert (_completions(requests), _drawn(ledger)) == (1, ["desktop"])
