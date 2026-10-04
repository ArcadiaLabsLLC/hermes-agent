"""Fork-owned half of ``tools/tool_search.py``: the ``never_defer`` promotions, the
top-hit parameter schemas, and the always-present standalone ``tool_describe``
(RECORDED PARALLEL of upstream tool-search classify/describe — upstream-footprint-ledger
row ``tools/tool_search.py``).

Moved out of the upstream module by lane FOOTPRINT-DROP (2026-09-27); ``tool_search``
re-exports these names in one import line and calls them where the behaviour attaches.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from tools.tool_search_catalog import BRIDGE_TOOL_NAMES, TOOL_DESCRIBE_NAME

#: Top search hits that carry their full ``parameters`` schema, and its size bound.
_SEARCH_HIT_SCHEMA_TOP_N = 3
_SEARCH_HIT_SCHEMA_MAX_CHARS = 6000


def parse_never_defer(never_defer_raw) -> tuple[str, ...]:
    """The config's ``never_defer`` list: stripped, non-empty, never a bridge name, sorted."""
    never_defer_names: set[str] = set()
    if isinstance(never_defer_raw, (list, tuple)):
        for item in never_defer_raw:
            try:
                cleaned = str(item).strip()
            except Exception:
                continue
            if not cleaned or cleaned in BRIDGE_TOOL_NAMES:
                continue
            never_defer_names.add(cleaned)
    return tuple(sorted(never_defer_names))


def attach_hit_parameters(record: Dict[str, Any], index: int, params) -> None:
    """Inline a top hit's ``parameters`` so the model can call it without a describe round."""
    if index >= _SEARCH_HIT_SCHEMA_TOP_N:
        return
    params = params or {}
    try:
        if len(json.dumps(params, ensure_ascii=False)) <= _SEARCH_HIT_SCHEMA_MAX_CHARS:
            record["parameters"] = params
    except (TypeError, ValueError):
        pass


#: Fork tools that stay in the direct tool list. ``skill_search`` is the eternia-harness plugin's tool
#: (toolset ``skills``); upstream defers every plugin tool, and it used to stay eager only by being
#: named in upstream's core list in ``toolsets.py`` (moved here, lane h11-fp 2026-09-29).
#: The launcher_qa core verbs ride eagerly too: a "screenshot news" turn spent two of its four
#: model round trips on tool_search + tool_describe before ``open_app_tab`` (owner run
#: 2026-10-04). They exist only in a run ADMITTED the ``launcher_qa`` server, so naming them
#: here un-hides them for exactly the personas that use it and grants nothing to anyone else.
_LAUNCHER_QA_CORE_TOOLS = frozenset({
    "mcp_launcher_qa_open_app_tab",
    "mcp_launcher_qa_screenshot_window",
    "mcp_launcher_qa_capture_screenshot",
    "mcp_launcher_qa_launch_or_attach",
})
_NEVER_DEFER_TOOLS = frozenset({"agent_chat_send", "agent_chat_dispatches", "skill_search"}) | _LAUNCHER_QA_CORE_TOOLS


def never_defer_tool_names(config=None) -> frozenset[str]:
    """Hardcoded promotions unioned with the operator's config extension.

    Config EXTENDS the set; nothing in config can remove a hardcoded name.
    """
    if config is None:
        from tools.tool_search import load_config_readonly

        config = load_config_readonly()  # no write on discovery
    if not config.never_defer:
        return _NEVER_DEFER_TOOLS
    return _NEVER_DEFER_TOOLS | frozenset(config.never_defer)


#: The ``tool_call`` shape restated where the agent first holds several names: a
#: ``tool_describe`` result. The bridge's own ``tool_call`` schema says it too, but an
#: agent handed three names by describe still sent all three in one call (owner
#: screenshot 2026-10-01, ``events.81417412.jsonl`` line 17549) and lost a round trip.
LOCAL_CALL_RULE = (
    "Invoke each local tool with its own tool_call (calls: an array of ONE entry); "
    "only connectors__ names may be batched in one tool_call."
)


def attach_local_call_rule(result: Dict[str, Any]) -> None:
    """Stamp :data:`LOCAL_CALL_RULE` on a describe result that described a local tool."""
    from tools.connectors import is_connector_name

    if any(not is_connector_name(name) for name in result.get("tools") or {}):
        result["call_rule"] = LOCAL_CALL_RULE


def tool_describe_schema() -> Dict[str, Any]:
    """Return the fixed, always-available ``tool_describe`` schema.

    Injected into every resolved lane by ``model_tools`` independent of
    tool-search deferral so the model can always pull a brief-trimmed tool's
    full documentation. Bridge dispatch in ``model_tools.handle_function_call``
    routes it (``is_bridge_tool`` already recognizes the name), and
    ``dispatch_tool_describe`` serves the full registry-held docs + live
    parameter schema.
    """
    return {
        "type": "function",
        "function": {
            "name": TOOL_DESCRIBE_NAME,
            "description": (
                "Load a tool's full documentation and parameter reference by "
                "name. Tool descriptions in this list are brief; call "
                "tool_describe before the first use of an unfamiliar tool. "
                + LOCAL_CALL_RULE
            ),
            # Upstream's describe argument (the bridge's ``names``; a single string is one name), so
            # ``dispatch_tool_describe`` answers it through upstream's own list door (RESOLVER 7c,
            # recorded-parallels sheet; the fork's single ``name`` spelling is gone).
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact tool names to describe. A single string is accepted and treated as one name.",
                    },
                },
                "required": ["names"],
            },
        },
    }


def ensure_tool_describe_present(tool_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure ``tool_describe`` is in the model-facing tool list.

    No-op when it is already present (e.g. tool-search deferral already injected
    the full bridge trio, which includes ``tool_describe``). Otherwise appends
    the fixed standalone schema. Returns a new list; never mutates the input.
    """
    for td in tool_defs:
        if (td.get("function") or {}).get("name") == TOOL_DESCRIBE_NAME:
            return tool_defs
    return list(tool_defs) + [tool_describe_schema()]
