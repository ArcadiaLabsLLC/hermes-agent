"""Fork half of ``test_compaction_prompt_rebuild`` (h10b-fix, owner 2026-09-29).

Persisted plugin sections must restore from the prompt core actually builds (the profile
line sits between the container and ``Conversation started:``), and a stored prompt with no
container renders fresh — so a first build and the compaction re-render carry the same bytes.
"""

from types import SimpleNamespace
from unittest.mock import patch

from agent.system_prompt import (
    _restore_plugin_prompt_sections,
    build_system_prompt,
    invalidate_system_prompt,
)
from hermes_cli.plugins_dispatch import RenderedPluginSystemPromptSection

_SECTION = RenderedPluginSystemPromptSection(
    id="fork.test-section", content="FORK SECTION BODY", position="after_memory", plugin="fork-test")


def _agent(**over):
    base = dict(
        _cached_system_prompt=None, _cached_system_prompt_static=None, _memory_store=None,
        _memory_manager=None, provider="", model="gpt-4o", platform="cli", _memory_enabled=False,
        _user_profile_enabled=False, load_soul_identity=False, skip_context_files=True,
        valid_tool_names={"terminal"}, _task_completion_guidance=False,
        _parallel_tool_call_guidance=False, _tool_use_enforcement=False, _execution_guidance=False,
        _environment_probe=False, _bot_mode_protocol=False, _kanban_worker_guidance="",
        pass_session_id=False, session_id="s1", _emit_status=lambda *a, **k: None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _build(agent, sections=(_SECTION,)):
    with patch("agent.prompt_builder.load_soul_md", return_value=""), \
         patch("agent.prompt_builder.build_environment_hints", return_value="ENV"), \
         patch("agent.system_prompt.resolve_context_cwd", return_value=None), \
         patch("hermes_cli.plugins.render_system_prompt_sections", return_value=list(sections)):
        return build_system_prompt(agent)


def test_a_built_prompt_restores_its_own_plugin_sections():
    prompt = _build(_agent())
    assert "FORK SECTION BODY" in prompt
    assert _restore_plugin_prompt_sections(prompt) == (
        RenderedPluginSystemPromptSection(id=_SECTION.id, content=_SECTION.content,
                                          position="after_memory", plugin="persisted-prompt"),)


def test_a_prompt_without_a_container_restores_nothing():
    """Positive control for the restore: the same builder with no sections -> nothing to recover."""
    assert _restore_plugin_prompt_sections(_build(_agent(), sections=())) == ()


def test_first_build_over_a_container_less_prompt_matches_the_compaction_rebuild():
    agent = _agent(_cached_system_prompt="OLD PROMPT")
    first = _build(agent)
    invalidate_system_prompt(agent)
    assert _build(agent) == first
    assert "FORK SECTION BODY" in first
