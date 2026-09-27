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


_NEVER_DEFER_TOOLS = frozenset({"agent_chat_send", "agent_chat_dispatches"})


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
                "tool_describe before the first use of an unfamiliar tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact tool name to describe.",
                    },
                },
                "required": ["name"],
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
