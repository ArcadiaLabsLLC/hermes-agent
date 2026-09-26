"""Lane PF-2: the prompt and the CLI start ride the eternia-harness plugin.

* The execution-guidance Safety sentence is rewritten on the wire by the plugin's
  ``llm_request`` middleware (upstream's ``agent/prompt_builder.py`` keeps its own).
* The Windows-native tooling hint is the ``eternia-harness.windows-tooling`` section.
* The CLI's durable delegation-completion restore is an ``on_session_start`` hook.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

from agent.prompt_builder import execution_guidance_text
from agent_runtime import prompt_guidance
from agent_runtime.prompt_guidance import SAFETY_SENTENCE, UPSTREAM_SAFETY_SENTENCE, WINDOWS_NATIVE_TOOLING_HINT

_UPSTREAM_PHRASE = "if the next step has side effects"


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_pf2_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _system_text() -> str:
    return "You are Hermes.\n\n" + execution_guidance_text() + "\n\nMore prompt."


def _requests(system: str) -> dict:
    """The system slot of each api mode's provider kwargs."""
    return {
        "chat_completions": {"model": "gpt", "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": "hi"}]},
        "anthropic_messages": {"model": "claude", "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": "hi"}]},
        "codex_responses": {"model": "gpt-5", "instructions": system,
                            "input": [{"role": "user", "content": "hi"}]},
    }


def _wire_system(request: dict, mode: str) -> str:
    if mode == "chat_completions":
        return request["messages"][0]["content"]
    if mode == "anthropic_messages":
        return request["system"][0]["text"]
    return request["instructions"]


@pytest.fixture(autouse=True)
def _reset_miss_warning(monkeypatch):
    monkeypatch.setattr(prompt_guidance, "_miss_warned", False)


class TestSafetySentenceOnTheWire:
    def test_core_prompt_still_carries_upstreams_sentence(self):
        assert UPSTREAM_SAFETY_SENTENCE in execution_guidance_text()

    @pytest.mark.parametrize("mode", ["chat_completions", "anthropic_messages", "codex_responses"])
    def test_upstream_llm_request_door_puts_the_fork_sentence_on_the_wire(self, mode):
        from hermes_cli.middleware import apply_llm_request_middleware
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
        request = _requests(_system_text())[mode]
        result = apply_llm_request_middleware(
            request, session_id="s", platform="cli", model="m", provider="p", api_mode=mode)
        wire = _wire_system(result.payload, mode)
        assert SAFETY_SENTENCE in wire
        assert _UPSTREAM_PHRASE not in wire
        assert wire.count("- Safety:") == 1
        # upstream hands every callback the same original: it is never mutated
        assert UPSTREAM_SAFETY_SENTENCE in _wire_system(request, mode)

    def test_rewrite_is_byte_stable_across_turns(self):
        request = _requests(_system_text())["codex_responses"]
        first = _plugin().brief_tool_descriptions(request)["request"]
        second = _plugin().brief_tool_descriptions(request)["request"]
        assert first["instructions"] == second["instructions"]

    def test_positive_control_a_prompt_without_the_block_is_untouched(self):
        request = _requests("You are Hermes.")["chat_completions"]
        assert prompt_guidance.rewrite_request_safety_sentence(request) is None

    def test_sentinel_miss_warns_once_and_leaves_the_text(self, caplog):
        reworded = _system_text().replace(UPSTREAM_SAFETY_SENTENCE, "- Safety: upstream reworded this.\n")
        request = _requests(reworded)["chat_completions"]
        with caplog.at_level(logging.WARNING, logger=prompt_guidance.logger.name):
            assert prompt_guidance.rewrite_request_safety_sentence(request) is None
            assert prompt_guidance.rewrite_request_safety_sentence(request) is None
        warnings = [r for r in caplog.records if "Safety sentence was not found" in r.getMessage()]
        assert len(warnings) == 1


class TestWindowsToolingSection:
    def _section(self, monkeypatch, *, platform="win32", wsl=False, backend=None, tools="read_file,terminal"):
        import sys

        import hermes_constants

        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(hermes_constants, "is_wsl", lambda: wsl)
        if backend is None:
            monkeypatch.delenv("TERMINAL_ENV", raising=False)
        else:
            monkeypatch.setenv("TERMINAL_ENV", backend)
        return _plugin().render_windows_tooling({"tool_names": tools})

    def test_present_on_native_windows_with_a_local_backend(self, monkeypatch):
        assert self._section(monkeypatch) == WINDOWS_NATIVE_TOOLING_HINT
        assert self._section(monkeypatch, backend="local") == WINDOWS_NATIVE_TOOLING_HINT

    @pytest.mark.parametrize("kwargs", [{"platform": "linux"}, {"platform": "darwin"}, {"wsl": True},
                                        {"backend": "docker"}, {"backend": "ssh"},
                                        {"tools": "read_file"}, {"tools": ""}])
    def test_absent_elsewhere(self, monkeypatch, kwargs):
        assert self._section(monkeypatch, **kwargs) == ""

    def test_registered_as_an_after_memory_section(self):
        from hermes_cli.plugins import discover_plugins, get_plugin_manager

        discover_plugins()
        section = get_plugin_manager()._system_prompt_sections.get("eternia-harness.windows-tooling")
        assert section is not None and section.plugin == "eternia-harness"
        assert section.position == "after_memory"


class TestCliCompletionRestore:
    @pytest.fixture
    def restores(self, monkeypatch):
        from tools.process_registry import process_registry

        calls: list[int] = []
        monkeypatch.setattr(process_registry, "restore_durable_completions", lambda: calls.append(1) or 0)
        return calls

    def test_registered_on_session_start(self):
        registered: list[tuple[str, object]] = []

        class _Ctx:
            def register_hook(self, name, callback):
                registered.append((name, callback))

            def __getattr__(self, name):
                return lambda *a, **k: None

        module = _plugin()
        module.register(_Ctx())
        assert ("on_session_start", module.restore_cli_durable_completions) in registered

    def test_once_per_process_across_two_cli_sessions(self, restores):
        module = _plugin()
        module.restore_cli_durable_completions(session_id="a", model="m", platform="cli")
        module.restore_cli_durable_completions(session_id="b", model="m", platform="cli")
        assert restores == [1]

    @pytest.mark.parametrize("platform", ["telegram", "discord", "tui", "", None])
    def test_gateway_and_other_sessions_never_trigger_it(self, restores, platform):
        module = _plugin()
        module.restore_cli_durable_completions(session_id="a", model="m", platform=platform)
        assert restores == []
        # positive control: the same module restores for the CLI
        module.restore_cli_durable_completions(session_id="a", model="m", platform="cli")
        assert restores == [1]

    def test_fires_through_upstreams_hook_at_the_first_prompt_build(self, restores):
        from hermes_cli.lifecycle import invoke_hook
        from hermes_cli.plugins import discover_plugins, get_plugin_manager

        discover_plugins()
        callbacks = get_plugin_manager().iter_hook_callbacks("on_session_start")
        assert any(getattr(cb, "__name__", "") == "restore_cli_durable_completions" for cb in callbacks)
        invoke_hook("on_session_start", session_id="x", model="m", platform="telegram")
        assert restores == []
