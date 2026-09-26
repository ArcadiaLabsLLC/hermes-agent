"""Upstream documentation evolves independently of the fork's wire budget."""


def test_a_briefed_builtin_keeps_upstream_text_in_the_registry():
    """No built-in is briefed at registration (``terminal`` left 2026-09-26, lane PF-1):
    the registry holds upstream's live text for ``tool_describe``, the wire gets the brief."""
    from tools.registry import discover_builtin_tools, registry
    from tools.terminal_tool import TERMINAL_SCHEMA
    from tools.tool_full_descriptions import full_tool_description

    discover_builtin_tools()
    registered = registry.get_entry("terminal").schema
    assert registered["description"] == TERMINAL_SCHEMA["description"]
    assert registered["description"] != BRIEF_DESCRIPTIONS["terminal"]
    assert full_tool_description("terminal") is None  # tool_describe serves the registry text
    wire = brief_request_tools({"tools": [{"type": "function", "function": registered}]})
    assert wire["tools"][0]["function"]["description"] == BRIEF_DESCRIPTIONS["terminal"]
    assert wire["tools"][0]["function"]["parameters"] is registered["parameters"]


# --- the wire middleware (lane MOVE-A, 2026-09-24) ---------------------------

import importlib.util
from pathlib import Path

from tools.downstream_schema import BRIEF_DESCRIPTIONS, brief_request_tools

_PARAMS = {"type": "object", "properties": {"questions": {"type": "array"}}}
_FULL = "Upstream's full clarify documentation."


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chat_completions_shape_gets_the_brief_and_keeps_parameters():
    request = {"model": "m", "tools": [
        {"type": "function", "function": {"name": "clarify", "description": _FULL, "parameters": _PARAMS}},
        {"type": "function", "function": {"name": "custom_plugin", "description": "keep", "parameters": {}}},
    ]}
    out = brief_request_tools(request)
    assert out["tools"][0]["function"]["description"] == BRIEF_DESCRIPTIONS["clarify"]
    assert out["tools"][0]["function"]["parameters"] is _PARAMS
    assert out["tools"][1]["function"]["description"] == "keep"
    assert request["tools"][0]["function"]["description"] == _FULL  # input not mutated
    assert out["model"] == "m"


def test_responses_shape_gets_the_brief():
    request = {"tools": [{"type": "function", "name": "session_search", "description": _FULL,
                          "parameters": _PARAMS, "strict": False}]}
    tool = brief_request_tools(request)["tools"][0]
    assert tool["description"] == BRIEF_DESCRIPTIONS["session_search"]
    assert tool["strict"] is False and tool["parameters"] is _PARAMS


def test_anthropic_shape_gets_the_brief_and_keeps_cache_control():
    request = {"tools": [{"name": "write_file", "description": _FULL, "input_schema": _PARAMS,
                          "cache_control": {"type": "ephemeral"}}]}
    tool = brief_request_tools(request)["tools"][0]
    assert tool["description"] == BRIEF_DESCRIPTIONS["write_file"]
    assert tool["cache_control"] == {"type": "ephemeral"}


def test_no_rewrite_returns_none():
    assert brief_request_tools({"messages": []}) is None
    already = {"tools": [{"name": "clarify", "description": BRIEF_DESCRIPTIONS["clarify"]}]}
    assert brief_request_tools(already) is None


def test_clarify_brief_follows_the_question_cap():
    from tools.clarify_tool import MAX_QUESTIONS

    assert f"1-{MAX_QUESTIONS}" in BRIEF_DESCRIPTIONS["clarify"]


def test_execute_code_brief_keeps_limits_and_defers_helpers():
    brief = BRIEF_DESCRIPTIONS["execute_code"]
    for needle in ("5-min", "50KB", "50-call", "from hermes_tools import", "tool_describe"):
        assert needle in brief
    assert "json_parse" not in brief
    from tools.code_execution_tool import build_execute_code_schema

    full = build_execute_code_schema()["description"]
    for helper in ("json_parse", "shell_quote", "retry"):
        assert helper in full


def test_plugin_registers_the_middleware_and_returns_the_rewrite():
    plugin = _plugin()
    registered = []

    class _Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def register_middleware(self, kind, callback):
            registered.append((kind, callback))

    plugin.register(_Ctx())
    assert [kind for kind, _ in registered].count("llm_request") == 1
    callback = dict(registered)["llm_request"]
    request = {"tools": [{"name": "clarify", "description": _FULL, "input_schema": _PARAMS}]}
    result = callback(request=request, session_id="s", api_mode="anthropic_messages")
    assert result["request"]["tools"][0]["description"] == BRIEF_DESCRIPTIONS["clarify"]
    assert callback(request={"messages": []}) is None
