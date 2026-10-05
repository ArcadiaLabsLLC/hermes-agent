"""Fork-owned tests moved out of ``tests/tools/test_tool_search.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from tests.tools.test_tool_search import (  # noqa: F401 — upstream names the moved tests use
    TestCatalogListing as _UpstreamCatalogListing,
    TestRegression_ToolsetScoping as _UpstreamToolsetScoping,
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


#: The verbs the launcher_qa MCP server exposes (raw MCP tool names), spelled independently of the
#: promotion so a respelled promotion cannot agree with its own pin by construction.
_LAUNCHER_QA_CORE_VERBS = (
    "mcp_launcher_qa_open_app_tab",
    "mcp_launcher_qa_screenshot_window",
    "mcp_launcher_qa_capture_screenshot",
    "mcp_launcher_qa_launch_or_attach",
)
_LAUNCHER_QA_CONTROL_VERB = "mcp_launcher_qa_click_button"


@pytest.fixture
def launcher_qa_registered():
    """The launcher_qa server's tools registered through the REAL MCP registration path into a
    fresh registry; yields the registered names exactly as the registry spells them."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from tools.mcp_tool import MCPServerTask
    from tools.mcp_tool_registration import _register_server_tools
    from tools.registry import ToolRegistry

    server = MCPServerTask("launcher_qa")
    server._tools = [SimpleNamespace(name=verb, description="launcher_qa verb.", inputSchema=None)
                     for verb in (*_LAUNCHER_QA_CORE_VERBS, _LAUNCHER_QA_CONTROL_VERB)]
    server.session = MagicMock()
    with patch("tools.registry.registry", ToolRegistry()):
        yield _register_server_tools("launcher_qa", server, {})


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

    def test_launcher_qa_core_verbs_never_defer(self, launcher_qa_registered):
        """A "screenshot news" turn spent two of four model round trips on
        tool_search + tool_describe before open_app_tab (owner run 2026-10-04):
        the four launcher_qa core verbs ride eagerly once the server is admitted.

        The names asked about are the ones the REAL MCP registration path produced
        (``_register_server_tools``), never typed here: the first version of this
        test registered the bare verbs by hand, matched the equally bare promotion,
        and stayed green while every real run still deferred the four (owner run
        2026-10-05). Positive control: a non-core verb of the SAME server, registered
        the same way, still defers — so the four are un-hidden by the promotion, not
        by a fixture that never reached the MCP deferral branch."""
        from tools.tool_search import ToolSearchConfig, is_deferrable_tool_name

        registered = launcher_qa_registered
        cfg = ToolSearchConfig.from_raw(None)
        by_verb = {verb: name for name in registered
                   for verb in (*_LAUNCHER_QA_CORE_VERBS, _LAUNCHER_QA_CONTROL_VERB)
                   if name.endswith(f"__{verb}")}
        assert set(by_verb) == {*_LAUNCHER_QA_CORE_VERBS, _LAUNCHER_QA_CONTROL_VERB}, (
            f"registration fixture did not produce every verb: {sorted(registered)}"
        )
        control = by_verb[_LAUNCHER_QA_CONTROL_VERB]
        assert is_deferrable_tool_name(control, config=cfg), (
            f"control '{control}' must defer — the fixture never reached the MCP branch"
        )
        core = [by_verb[verb] for verb in _LAUNCHER_QA_CORE_VERBS]
        deferred = [n for n in core if is_deferrable_tool_name(n, config=cfg)]
        assert deferred == [], (
            f"launcher_qa core verbs must never defer under their REGISTERED names; deferred={deferred}"
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
        """T6b: tool_describe serves the FULL docs for a core tool whose wire
        description is a brief: the registry keeps upstream's text (the brief is
        swapped in only on the wire, by the eternia-harness middleware), and the
        live (untrimmed) parameter schema comes back."""
        from tools.registry import discover_builtin_tools, registry
        discover_builtin_tools()
        from tools.downstream_schema import BRIEF_DESCRIPTIONS
        from tools.session_search_tool import SESSION_SEARCH_SCHEMA
        from tools.tool_search import dispatch_tool_describe
        schema = registry.get_entry("session_search").schema
        result = json.loads(
            dispatch_tool_describe({"names": ["session_search"]}, current_tool_defs=[{"type": "function", "function": schema}])
        )
        assert "errors" not in result
        described = result["tools"]["session_search"]
        # Full upstream text, not the wire brief.
        assert described["description"] == SESSION_SEARCH_SCHEMA["description"]
        assert described["description"] != BRIEF_DESCRIPTIONS["session_search"]
        assert "inspect that first" in described["description"]
        # Parameters are never trimmed — live schema is returned.
        assert described["parameters"].get("properties")

    def test_tool_describe_does_not_regrant_excluded_core_tool(self):
        from tools.tool_search import dispatch_tool_describe
        result = json.loads(dispatch_tool_describe({"names": ["session_search"]}, current_tool_defs=[]))
        assert "session_search" not in result.get("tools", {}) and result["not_found"] == ["session_search"]

    def test_tool_describe_unknown_tool_errors(self):
        from tools.tool_search import dispatch_tool_describe
        result = json.loads(
            dispatch_tool_describe({"names": "zzz_not_a_tool"}, current_tool_defs=[])  # a single string is one name
        )
        assert result["not_found"] == ["zzz_not_a_tool"] and not result.get("tools")

    def test_the_retired_single_name_spelling_describes_nothing(self):
        """RESOLVER 7c: the fork's single ``name`` argument is gone; upstream's list door answers
        with its own missing-argument error rather than a hit. Positive control: the same tool,
        asked through ``names``, is described."""
        from tools.tool_search import dispatch_tool_describe
        defs = [_td("terminal", "Run shell", {"command": {"type": "string"}})]
        retired = json.loads(dispatch_tool_describe({"name": "terminal"}, current_tool_defs=defs))
        assert "error" in retired and "tools" not in retired
        described = json.loads(dispatch_tool_describe({"names": ["terminal"]}, current_tool_defs=defs))
        assert "terminal" in described["tools"]

    def test_tool_describe_restates_the_one_entry_rule_for_local_tools(self):
        """Runtime-queue row (w5-rt): describe handed an agent three local names and it sent
        all three in one tool_call. The result now carries the rule at that moment."""
        from tools.tool_search import dispatch_tool_describe
        from tools.tool_search_downstream import LOCAL_CALL_RULE
        defs = [_td(n, "Read", {"x": {"type": "string"}}) for n in ("qa_a", "qa_b", "qa_c")]
        result = json.loads(dispatch_tool_describe({"names": ["qa_a", "qa_b", "qa_c"]}, current_tool_defs=defs))
        assert set(result["tools"]) == {"qa_a", "qa_b", "qa_c"}
        assert result["call_rule"] == LOCAL_CALL_RULE
        assert "ONE entry" in LOCAL_CALL_RULE and "connectors__" in LOCAL_CALL_RULE

    def test_the_call_rule_is_not_stamped_when_nothing_local_was_described(self):
        """Positive control's twin: a connector-only result may batch, and a miss names no tool."""
        from tools.tool_search_downstream import attach_local_call_rule
        connectors_only = {"tools": {"connectors__gmail__send": {}, "connectors__slack__post": {}}}
        attach_local_call_rule(connectors_only)
        assert "call_rule" not in connectors_only
        missed = {"tools": {}, "not_found": ["zzz"]}
        attach_local_call_rule(missed)
        assert "call_rule" not in missed
        mixed = {"tools": {"connectors__gmail__send": {}, "terminal": {}}}
        attach_local_call_rule(mixed)
        assert "call_rule" in mixed

    def test_tool_describe_schema_is_fixed_and_tiny(self):
        from tools.tool_search import tool_describe_schema, TOOL_DESCRIBE_NAME
        schema = tool_describe_schema()
        fn = schema["function"]
        assert fn["name"] == TOOL_DESCRIBE_NAME
        assert list(fn["parameters"]["properties"]) == ["names"]
        assert fn["parameters"]["required"] == ["names"]

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


class TestRegression_ToolsetScoping:
    """Fork tests of the inline search-hit schema; ``_register`` is upstream's."""

    _register = staticmethod(_UpstreamToolsetScoping._register)

    def test_search_hits_include_parameters_for_top_hits(self):
        from tools.tool_search import ToolSearchConfig, dispatch_tool_search
        from tools.tool_search_downstream import _SEARCH_HIT_SCHEMA_TOP_N

        props: Dict[str, Any] = {}
        defs: List[Dict[str, Any]] = []
        for i in range(6):
            name = f"mcp_inline_sch_{i}"
            self._register(name, "mcp-inline-sch")
            props[name] = {f"arg_{i}": {"type": "string", "description": f"argument {i}"}}
            defs.append(_td(name, "Inline schema probe tool.", props[name]))

        parsed = json.loads(dispatch_tool_search(
            {"queries": ["inline schema probe"], "limit": 6},
            current_tool_defs=defs,
            config=ToolSearchConfig.from_raw({"enabled": "on"}),
        ))
        matches = [{"name": name, **parsed["tools"][name]} for name in parsed["results"][0]["matches"]]
        assert len(matches) == 6, f"expected all 6 probes to match, got {len(matches)}"

        assert "parameters" in matches[0], (
            "top search hit carries no inline parameters schema — the model is "
            "forced back into a tool_describe round-trip"
        )
        assert matches[0]["parameters"]["properties"] == props[matches[0]["name"]], (
            "inline schema does not match the tool's registered parameters"
        )
        for m in matches[:_SEARCH_HIT_SCHEMA_TOP_N]:
            assert "parameters" in m, f"top hit '{m['name']}' is missing parameters"
        for m in matches[_SEARCH_HIT_SCHEMA_TOP_N:]:
            assert "parameters" not in m, (
                f"hit '{m['name']}' is past the top-{_SEARCH_HIT_SCHEMA_TOP_N} "
                "cutoff and must stay schema-less"
            )
    def test_search_hit_schema_cap_omits_oversized(self):
        from tools.tool_search import ToolSearchConfig, dispatch_tool_search
        from tools.tool_search_downstream import _SEARCH_HIT_SCHEMA_MAX_CHARS

        name = "mcp_oversized_sch_tool"
        self._register(name, "mcp-oversized-sch")
        big = {"blob": {"type": "string",
                        "description": "x" * (_SEARCH_HIT_SCHEMA_MAX_CHARS + 1000)}}
        defs = [_td(name, "Oversized schema probe.", big)]

        parsed = json.loads(dispatch_tool_search(
            {"queries": ["oversized schema probe"]},
            current_tool_defs=defs,
            config=ToolSearchConfig.from_raw({"enabled": "on"}),
        ))
        match = {"name": parsed["results"][0]["matches"][0], **parsed["tools"][parsed["results"][0]["matches"][0]]}
        assert match["name"] == name
        assert "parameters" not in match, (
            "an over-cap schema was inlined anyway — one pathological MCP tool "
            "can now blow up every search result"
        )
        # Name + description still survive, so tool_describe remains reachable.
        assert match["description"] == "Oversized schema probe."
    def test_bridge_description_licenses_skipping_describe(self):
        from tools.tool_search import assemble_tool_defs, ToolSearchConfig

        for i in range(5):
            self._register(f"mcp_desc_lic_{i}", "mcp-desc-lic")
        defs = [_td(f"mcp_desc_lic_{i}", "Deferred.") for i in range(5)]
        result = assemble_tool_defs(
            defs, context_length=200_000,
            config=ToolSearchConfig.from_raw({"enabled": "on"}),
        )
        assert result.activated
        search = next(t for t in result.tool_defs
                      if t["function"]["name"] == "tool_search")
        desc = search["function"]["description"]
        assert "full `parameters` schema" in desc, (
            "bridge description does not advertise inline schemas"
        )
        assert "invoke it directly with `tool_call`" in desc, (
            "bridge description does not license skipping tool_describe"
        )


class TestCatalogListing:
    """Fork test of the eager promotion; ``_register`` is upstream's."""

    _register = staticmethod(_UpstreamCatalogListing._register)

    def test_promoted_tools_ride_eagerly_and_drop_from_listing(self):
        """The promotion's whole point, end to end: agent_chat_send ships in
        the model-facing array next to the bridge trio, and vanishes from both
        the tier-1 listing and the tool_search catalog."""
        import tools.agent_chat_tool  # noqa: F401
        from tools.registry import registry
        from tools.tool_search import (
            ToolSearchConfig, assemble_tool_defs, dispatch_tool_search,
        )

        for i in range(30):
            self._register(f"mcp_x_{i}")

        raw = registry.get_schema("agent_chat_send") or {}
        fn = raw.get("function") if raw.get("type") == "function" else raw
        assert (fn or {}).get("name") == "agent_chat_send", (
            "registry did not yield a real agent_chat_send schema — the test "
            "would assert against a fabricated def"
        )
        send_def = {"type": "function", "function": fn}

        defs = [_td(f"mcp_x_{i}", "Deferred.") for i in range(30)] + [send_def]
        cfg = ToolSearchConfig.from_raw({"enabled": "on"})
        result = assemble_tool_defs(defs, context_length=200_000, config=cfg)

        assert result.activated
        names = {t["function"]["name"] for t in result.tool_defs}
        assert {"tool_search", "tool_describe", "tool_call"} <= names
        assert "agent_chat_send" in names, (
            "promoted tool did not ride eagerly in the assembled tools array"
        )
        assert result.deferred_count == 30, (
            f"expected 30 deferred (the MCP tools only), got {result.deferred_count} "
            "— the promoted tool is still being deferred"
        )

        search = next(t for t in result.tool_defs if t["function"]["name"] == "tool_search")
        assert "agent_chat_send" not in search["function"]["description"], (
            "promoted tool is still advertised in the tier-1 catalog listing"
        )

        parsed = json.loads(dispatch_tool_search(
            {"queries": ["agent chat send"], "limit": 10},
            current_tool_defs=defs, config=cfg,
        ))
        assert "agent_chat_send" not in set(parsed["results"][0]["matches"]), (
            "promoted tool is still searchable through the bridge catalog"
        )
