"""Cold plugin discovery, contextual output and persona routing isolation."""
from agent_runtime.console_suggestions.generation import generate_suggestion
from agent_runtime.console_suggestions.settings import suggestion_home


def test_cold_manager_registers_task_and_uses_facade_without_persona(tmp_path, monkeypatch):
    from agent.plugin_llm import PluginLlm, PluginLlmCompleteResult
    from hermes_cli.plugins import _reset_plugin_managers_for_tests
    from agent.auxiliary_client import _read_main_field, scoped_runtime_main
    from hermes_cli.config_read_scope import readonly_config_scope

    home = tmp_path / "head"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: openai\n  default: head-model\nplugins:\n  entries:\n    eternia-harness:\n      enabled: true\n", encoding="utf-8")
    seen = []
    def complete(self, **kwargs):
        seen.append(kwargs)
        return PluginLlmCompleteResult(text="[foo] を説明して", provider="openai", model="head-model", agent_id="plugin")
    monkeypatch.setattr(PluginLlm, "complete", complete)
    _reset_plugin_managers_for_tests()
    try:
        with scoped_runtime_main({"model": "persona-model", "provider": "persona-provider"}), readonly_config_scope({"model": {"default": "persona-model"}}):
            with suggestion_home(home):
                result = generate_suggestion([{"role": "user", "content": "[foo]"}, {"role": "assistant", "content": "説明"}])
                assert _read_main_field("model", readonly=True) == "head-model"
        assert result["text"] == "[foo] を説明して"
        assert seen[0]["task"] == "console_next_prompt"
        assert not {"provider", "model", "timeout", "response_format"} & seen[0].keys()
        assert seen[0]["messages"][-2] == {"role": "assistant", "content": "説明"}
        assert seen[0]["messages"][-1]["role"] == "system"
        assert "latest user message" in seen[0]["messages"][-1]["content"]
    finally:
        _reset_plugin_managers_for_tests()


def test_real_facade_inherits_route_and_reports_actual_usage(tmp_path, monkeypatch):
    """Only the HTTP boundary is fake; discovery, task routing and facade are real."""
    import json
    import httpx
    from hermes_cli.plugins import _reset_plugin_managers_for_tests
    from agent_runtime.console_suggestions.settings import SuggestionSettings

    home = tmp_path / "head"
    home.mkdir()
    config = {"model": {"provider": "custom", "default": "head-fixture", "base_url": "http://127.0.0.1:9999/v1", "api_mode": "chat_completions"},
              "plugins": {"entries": {"eternia-harness": {"enabled": True}}}}
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-no-network")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    requests = []
    def send(client, request, **kwargs):
        assert request.url.host == "127.0.0.1", str(request.url)
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, request=request, json={"id": "fixture", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "好"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13}})
    monkeypatch.setattr(httpx.Client, "send", send)
    _reset_plugin_managers_for_tests()
    try:
        with suggestion_home(home):
            messages = [{"role": "user", "content": "继续"}, {"role": "assistant", "content": "说明"}]
            first = generate_suggestion(messages)
            assert first["model"] == "head-fixture" and first["provider"] == "custom"
            assert first["text"] == "好" and first["usage"]["total_tokens"] == 13
            settings = SuggestionSettings(home)
            settings.write({"expected_revision": settings.read()["settings_revision"], "auxiliary_override": {"provider": "custom", "model": "aux-fixture"}})
            assert generate_suggestion(messages)["model"] == "aux-fixture"
            settings.write({"expected_revision": settings.read()["settings_revision"], "auxiliary_override": None})
            assert generate_suggestion(messages)["model"] == "head-fixture"
            from hermes_cli.config import read_user_config_raw
            assert read_user_config_raw()["model"] == config["model"]
        assert [request["model"] for request in requests] == ["head-fixture", "aux-fixture", "head-fixture"]
        assert all("response_format" not in request for request in requests)
    finally:
        _reset_plugin_managers_for_tests()


def test_bundle_carries_pinned_upstream_notice(tmp_path):
    from scripts.bundle_licenses import copy_first_party_licence
    info = tmp_path / "hermes_agent.dist-info"
    info.mkdir()
    copy_first_party_licence(tmp_path)
    notice = (info / "licenses" / "next-prompt.txt").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 soymarketing" in notice
    assert "Permission is hereby granted" in notice
