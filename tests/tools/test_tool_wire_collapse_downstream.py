"""Every eager tool rides the wire collapsed (lane h-prompt-brief, owner ask 2026-10-05).

The persona chat lane's eager set (ruling R1 as the owner amended it: only the five
``browser_vault_*`` tools are deferred) is built from the REAL registry schemas and
assembled through upstream's ``assemble_tool_defs``; the wire is what the eternia-harness
``llm_request`` middleware (``tools.downstream_schema.brief_request_tools``) sends. Each
tool must reach the provider as one sentence plus its parameter schema, unchanged, and
``tool_describe`` must still serve the full text.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tools.downstream_schema import (
    BRIEF_DESCRIPTIONS,
    KEEP_FULL_WIRE_DESCRIPTIONS,
    ONE_LINE_MAX_CHARS,
    _first_sentence,
    brief_request_tools,
)

#: The recorded persona-chat lane's built-ins and fork plugin tools that stay eager under the
#: amended R1 (both personas carry the same set; ``process_manage``/``todo_list`` are curated
#: deferrals and the five vault tools are the persona defer).
_EAGER_BUILTINS = (
    "agent_chat_dispatches", "agent_chat_send", "browser_exec", "clarify", "delegate_task",
    "execute_code", "memory", "patch", "read_file", "search_files", "skill_manage", "skill_search",
    "skill_view", "skills_list", "terminal", "vision_analyze", "web_extract", "web_search",
    "write_file",
)
_VAULT = ("browser_vault_list", "browser_vault_unlock", "browser_vault_fill",
          "browser_vault_save_login", "browser_vault_enter_code")
_BRIDGE = ("tool_search", "tool_call", "tool_describe")


def _fn(entry):
    return entry["function"]


@pytest.fixture
def lane():
    """``(raw, eager, wire)``: the lane's registry definitions, the assembled eager list, and
    that list as the middleware puts it on the wire."""
    import tools.tool_search as ts
    from hermes_cli.plugins import discover_plugins
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    discover_plugins()
    raw = []
    for name in (*_EAGER_BUILTINS, *_VAULT, "process_manage", "todo_list"):
        entry = registry.get_entry(name)
        assert entry is not None, f"{name} is not registered - the lane fixture would prove nothing"
        raw.append({"type": "function", "function": {**entry.schema, "name": name}})
    base = ts.ToolSearchConfig.from_raw(None)
    config = replace(base, defer_tools=frozenset(base.effective_defer_tools) | frozenset(_VAULT))
    eager = ts.assemble_tool_defs(raw, context_length=272_000, config=config).tool_defs
    wired = brief_request_tools({"tools": eager})
    assert wired is not None, "the middleware rewrote nothing"
    return raw, eager, wired["tools"]


def test_the_lane_carries_exactly_the_amended_eager_set(lane):
    """Anti-vacuity: every tool the walk below checks is on the wire, the vault is not."""
    _raw, eager, wire = lane
    names = [_fn(t)["name"] for t in wire]
    assert names == [_fn(t)["name"] for t in eager]
    assert set(names) == {*_EAGER_BUILTINS, *_BRIDGE}, sorted(names)


def test_every_eager_tool_is_one_line_with_its_parameter_schema_unchanged(lane):
    """One sentence on one line (the KEEP_FULL tools excepted), parameters identical to the
    assembled definition's — types, required, enums and per-parameter prose."""
    _raw, eager, wire = lane
    offenders = []
    for before, after in zip(eager, wire):
        name, description = _fn(after)["name"], _fn(after)["description"]
        if _fn(after).get("parameters") != _fn(before).get("parameters"):
            offenders.append(f"{name}: parameter schema changed on the wire")
        if name in KEEP_FULL_WIRE_DESCRIPTIONS:
            continue
        if "\n" in description or len(description) > ONE_LINE_MAX_CHARS:
            offenders.append(f"{name}: not one line ({len(description)} chars)")
        elif _first_sentence(description) != description:
            offenders.append(f"{name}: more than one sentence: {description!r}")
    assert not offenders, "\n".join(offenders)


def test_the_kept_tools_ride_their_long_text(lane):
    _raw, eager, wire = lane
    by_name = {_fn(t)["name"]: _fn(t)["description"] for t in wire}
    before = {_fn(t)["name"]: _fn(t)["description"] for t in eager}
    assert by_name["terminal"] == BRIEF_DESCRIPTIONS["terminal"]
    assert by_name["clarify"] == BRIEF_DESCRIPTIONS["clarify"]
    assert by_name["tool_search"] == before["tool_search"], "the deferred listing must ride whole (R3)"
    assert by_name["tool_call"] == before["tool_call"]


def test_tool_describe_serves_the_full_description_of_every_collapsed_tool(lane):
    """The full text is one call away: the registry's (or the fork mirror's), never the line."""
    from tools.tool_full_descriptions import full_tool_description
    from tools.tool_search import dispatch_tool_describe

    raw, _eager, wire = lane
    names = [n for n in _EAGER_BUILTINS if n not in KEEP_FULL_WIRE_DESCRIPTIONS]
    described = {}
    for name in names:  # one name per call: describe caps a call's names
        result = json.loads(dispatch_tool_describe({"names": [name]}, current_tool_defs=raw))
        assert name in result.get("tools", {}), (name, result)
        described.update(result["tools"])
    line = {_fn(t)["name"]: _fn(t)["description"] for t in wire}
    registry_text = {_fn(t)["name"]: _fn(t)["description"] for t in raw}
    params = {_fn(t)["name"]: _fn(t)["parameters"] for t in raw}
    for name in names:
        full = full_tool_description(name) or registry_text[name]
        assert described[name]["description"] == full, name
        assert len(full) > len(line[name]), f"{name}: describe serves nothing beyond the wire line"
        assert described[name]["parameters"] == params[name], name


def test_a_collapsed_tool_is_still_called_directly(lane):
    """The collapse rewrites the description only: the name the model calls is the registry's,
    on the eager list (no bridge hop), and the call dispatches with its schema's arguments."""
    from tools.registry import registry

    _raw, _eager, wire = lane
    entry = next(_fn(t) for t in wire if _fn(t)["name"] == "skills_list")
    assert entry["description"] != registry.get_entry("skills_list").schema["description"]
    result = json.loads(registry.dispatch("skills_list", {}))
    assert "error" not in result, result
