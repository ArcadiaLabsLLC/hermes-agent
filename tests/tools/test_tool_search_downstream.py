"""Fork-owned tests moved out of ``tests/tools/test_tool_search.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import json

from tests.tools.test_tool_search import (  # noqa: F401 — upstream names the moved tests use
    _td,
)


class TestConfigParsing:
    def test_never_defer_config_parses_and_sanitizes(self):
        """The operator extension parses to a deduped, sorted tuple; junk
        shapes fall back to the empty extension rather than raising."""
        from tools.tool_search import ToolSearchConfig
        cfg = ToolSearchConfig.from_raw({
            "never_defer": ["my_mcp_tool", " ", "tool_search", "my_mcp_tool"],
        })
        assert cfg.never_defer == ("my_mcp_tool",), (
            f"never_defer must sanitize to ('my_mcp_tool',), got {cfg.never_defer!r}"
        )
        assert ToolSearchConfig.from_raw(None).never_defer == ()
        assert ToolSearchConfig.from_raw(True).never_defer == ()
        assert ToolSearchConfig.from_raw({}).never_defer == ()
        # Non-list shapes are ignored, never raised on.
        assert ToolSearchConfig.from_raw({"never_defer": "nope"}).never_defer == ()
        assert ToolSearchConfig.from_raw({"never_defer": {"a": 1}}).never_defer == ()
        assert ToolSearchConfig.from_raw({"never_defer": None}).never_defer == ()

    def test_never_defer_config_extends_never_shrinks(self):
        """Config EXTENDS the hardcoded promotions — it can never remove one."""
        from tools.registry import registry
        from tools.tool_search import (
            ToolSearchConfig, is_deferrable_tool_name, never_defer_tool_names,
        )

        hardcoded = {"agent_chat_send", "agent_chat_dispatches"}

        empty = never_defer_tool_names(ToolSearchConfig.from_raw({"never_defer": []}))
        assert hardcoded <= empty, (
            f"hardcoded promotions missing with an empty extension: {sorted(empty)}"
        )

        cfg = ToolSearchConfig.from_raw({"never_defer": ["extra_x"]})
        extended = never_defer_tool_names(cfg)
        assert hardcoded <= extended, (
            f"config extension dropped hardcoded promotions: {sorted(extended)}"
        )
        assert "extra_x" in extended

        # And the extension actually un-hides a really-registered MCP tool.
        def _handler(args, task_id=None, **kw):
            return json.dumps({"ok": True})

        registry.register(
            name="nd_extension_probe",
            handler=_handler,
            schema=_td("nd_extension_probe", "Probe tool.")["function"],
            toolset="mcp-nd-test",
        )
        assert is_deferrable_tool_name(
            "nd_extension_probe", config=ToolSearchConfig.from_raw(None))
        assert not is_deferrable_tool_name(
            "nd_extension_probe",
            config=ToolSearchConfig.from_raw({"never_defer": ["nd_extension_probe"]}),
        )


class TestClassification:
    def test_promoted_agent_chat_tools_never_defer(self):
        """Operator ruling 2026-08-23: agent-to-agent send is a first-class
        tool. It is promoted in tool_search's never-defer set — NOT added to
        toolsets._HERMES_CORE_TOOLS, which would grant it everywhere."""
        import tools.agent_chat_tool  # noqa: F401 — registration runs at import
        from tools.tool_search import ToolSearchConfig, is_deferrable_tool_name
        cfg = ToolSearchConfig.from_raw(None)
        for name in ("agent_chat_send", "agent_chat_dispatches"):
            assert not is_deferrable_tool_name(name, config=cfg), (
                f"Promoted tool '{name}' must NEVER be deferrable"
            )

    def test_other_agent_chat_tools_stay_deferrable(self):
        """The promotion's boundary: only send + dispatches ride eagerly."""
        import tools.agent_chat_tool  # noqa: F401
        from tools.registry import registry
        from tools.tool_search import ToolSearchConfig, is_deferrable_tool_name
        cfg = ToolSearchConfig.from_raw(None)
        for name in ("agent_chat_threads", "agent_chat_open", "agent_chat_log_path"):
            assert registry.get_entry(name) is not None, (
                f"'{name}' is not registered — this test would false-green"
            )
            assert is_deferrable_tool_name(name, config=cfg), (
                f"Read-side sibling '{name}' must stay deferred"
            )

    def test_never_defer_does_not_grant(self):
        """Un-hide, never grant. classify_tools only PARTITIONS the defs it is
        handed — a promoted name can never materialize in a lane that was not
        granted the toolset producing its def."""
        import tools.agent_chat_tool  # noqa: F401
        from tools.tool_search import ToolSearchConfig, classify_tools
        defs = [_td("terminal", "Run shell")]
        visible, deferrable = classify_tools(
            defs, config=ToolSearchConfig.from_raw(None))
        out_names = {(td.get("function") or {}).get("name") for td in visible + deferrable}
        assert out_names == {"terminal"}, (
            f"classify_tools materialized names it was never handed: {sorted(out_names)}"
        )


class TestBridgeDispatch:
    # Fork-retained (T6b): tool_describe serves the FULL docs for CORE tools.
    # Upstream's up-front non-deferrable rejection was deliberately NOT adopted,
    # so its test_tool_describe_rejects_non_deferrable has no counterpart here.
    def test_tool_describe_requires_name(self):
        from tools.tool_search import dispatch_tool_describe
        result = dispatch_tool_describe({}, current_tool_defs=[])
        assert "error" in json.loads(result)

    def test_tool_describe_serves_core_tool_full_docs(self):
        """T6b: tool_describe now serves the FULL docs for a core tool whose
        wire schema ships a brief. It reads the full text from the fork-owned
        mirror and the live (untrimmed) parameter schema off the registry."""
        from tools.registry import discover_builtin_tools
        discover_builtin_tools()
        from tools.tool_search import dispatch_tool_describe
        result = json.loads(
            dispatch_tool_describe({"name": "session_search"}, current_tool_defs=[_td("session_search", "brief", {"query": {"type": "string"}})])
        )
        assert "error" not in result
        # Full original text, not the trimmed brief.
        from tools.session_search_tool import FULL_SESSION_SEARCH_DESCRIPTION
        assert result["description"] == FULL_SESSION_SEARCH_DESCRIPTION
        assert "inspect that first" in result["description"]
        # Parameters are never trimmed — live schema is returned.
        assert result["parameters"].get("properties")

    def test_tool_describe_does_not_regrant_excluded_core_tool(self):
        from tools.tool_search import dispatch_tool_describe
        result = json.loads(dispatch_tool_describe({"name": "session_search"}, current_tool_defs=[]))
        assert "error" in result

    def test_tool_describe_unknown_tool_errors(self):
        from tools.tool_search import dispatch_tool_describe
        result = json.loads(
            dispatch_tool_describe({"name": "zzz_not_a_tool"}, current_tool_defs=[])
        )
        assert "error" in result

    def test_tool_describe_schema_is_fixed_and_tiny(self):
        from tools.tool_search import tool_describe_schema, TOOL_DESCRIBE_NAME
        schema = tool_describe_schema()
        fn = schema["function"]
        assert fn["name"] == TOOL_DESCRIBE_NAME
        assert list(fn["parameters"]["properties"]) == ["name"]
        assert fn["parameters"]["required"] == ["name"]

    def test_ensure_tool_describe_present_is_idempotent(self):
        from tools.tool_search import (
            ensure_tool_describe_present, TOOL_DESCRIBE_NAME,
        )
        base = [_td("terminal", "Run shell")]
        once = ensure_tool_describe_present(base)
        names = [(t.get("function") or {}).get("name") for t in once]
        assert names.count(TOOL_DESCRIBE_NAME) == 1
        twice = ensure_tool_describe_present(once)
        names2 = [(t.get("function") or {}).get("name") for t in twice]
        assert names2.count(TOOL_DESCRIBE_NAME) == 1
        # Never mutates the input list.
        assert TOOL_DESCRIBE_NAME not in [
            (t.get("function") or {}).get("name") for t in base
        ]
