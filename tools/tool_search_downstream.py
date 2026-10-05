"""Fork-owned half of ``tools/tool_search.py``: the ``never_defer`` promotions, the
top-hit parameter schemas, and the always-present standalone ``tool_describe``
(RECORDED PARALLEL of upstream tool-search classify/describe — upstream-footprint-ledger
row ``tools/tool_search.py``).

Moved out of the upstream module by lane FOOTPRINT-DROP (2026-09-27); ``tool_search``
re-exports these names in one import line and calls them where the behaviour attaches.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from tools.mcp_tool_schema import mcp_prefixed_tool_name, sanitize_mcp_name_component
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
_BUILTIN_NEVER_DEFER = frozenset({"agent_chat_send", "agent_chat_dispatches", "skill_search"})

#: MCP promotions, keyed by the server that produces them and spelled as that server EXPOSES each
#: tool. The registered name is derived below by the registry's own naming function — never typed by
#: hand: the first spelling of this set was the bare ``mcp_launcher_qa_open_app_tab`` while the
#: registry holds ``mcp__launcher_qa__mcp_launcher_qa_open_app_tab``, so the promotion matched
#: nothing and its pin, typed the same way, proved nothing (lane h-defer, owner run 2026-10-05).
#: The launcher_qa core verbs ride eagerly: a "screenshot news" turn spent two of its four model
#: round trips on tool_search + tool_describe before ``open_app_tab`` (owner run 2026-10-04). They
#: exist only in a run ADMITTED the ``launcher_qa`` server, so naming them here un-hides them for
#: exactly the personas that use it and grants nothing to anyone else.
_MCP_NEVER_DEFER_VERBS = {
    "launcher_qa": (
        "mcp_launcher_qa_open_app_tab",
        "mcp_launcher_qa_screenshot_window",
        "mcp_launcher_qa_capture_screenshot",
        "mcp_launcher_qa_launch_or_attach",
    ),
}
_MCP_NEVER_DEFER = {
    server: frozenset(mcp_prefixed_tool_name(server, verb) for verb in verbs)
    for server, verbs in _MCP_NEVER_DEFER_VERBS.items()
}
_LAUNCHER_QA_CORE_TOOLS = _MCP_NEVER_DEFER["launcher_qa"]
_NEVER_DEFER_TOOLS = _BUILTIN_NEVER_DEFER.union(*_MCP_NEVER_DEFER.values())


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


logger = logging.getLogger("tools.tool_search")


@dataclass(frozen=True)
class UnmatchedNeverDefer:
    """A never-defer name that matches NO registered tool, so it un-hides nothing.

    ``source`` is ``"hardcoded"`` (this module's promotions) or ``"config"``
    (``tools.tool_search.never_defer``); ``registered_as`` is the one registered name whose
    MCP tail equals it — the bare-verb spelling that hid the launcher_qa promotion for a day.
    """

    name: str
    source: str
    registered_as: Optional[str] = None

    def message(self) -> str:
        hint = (f"; the registry spells it {self.registered_as!r} — list that name"
                if self.registered_as else "")
        return (f"tool_search never_defer ({self.source}) name {self.name!r} matches no "
                f"registered tool, so it keeps nothing eager{hint}")


def _registered_spelling(name: str, registered: frozenset) -> Optional[str]:
    """The single registered MCP name whose ``__<tool>`` tail is ``name``, else None."""
    tail = "__" + sanitize_mcp_name_component(name)
    hits = sorted(r for r in registered if r.endswith(tail))
    return hits[0] if len(hits) == 1 else None


def unmatched_never_defer(registry=None, config=None) -> Tuple[UnmatchedNeverDefer, ...]:
    """Every never-defer name that matches no registered tool, after registration.

    A hardcoded MCP promotion is checked only once its server registered SOMETHING in this
    process (a run that never admitted ``launcher_qa`` owes none of its names); a config name
    is always checked. The hardcoded built-in names are held by
    ``tests/tools/test_tool_search_downstream.py`` against the registration fixture instead:
    whether a plugin tool exists at runtime is the plugin's business, not a defect here.
    """
    if registry is None:
        from tools.registry import registry
    if config is None:
        from tools.tool_search import load_config_readonly

        config = load_config_readonly()
    registered = frozenset(registry.get_all_tool_names())
    found: List[UnmatchedNeverDefer] = []
    for server, promoted in sorted(_MCP_NEVER_DEFER.items()):
        if registry.get_tool_names_for_toolset(f"mcp-{server}"):
            found += [UnmatchedNeverDefer(n, "hardcoded", _registered_spelling(n, registered))
                      for n in sorted(promoted - registered)]
    found += [UnmatchedNeverDefer(n, "config", _registered_spelling(n, registered))
              for n in config.never_defer if n not in registered]
    return tuple(found)


_unmatched_warned: set = set()


def warn_unmatched_never_defer(registry=None, config=None) -> Tuple[UnmatchedNeverDefer, ...]:
    """Log each :class:`UnmatchedNeverDefer` once per process at WARNING; returns all of them.
    Runs on every tool-definitions recomputation, i.e. after each MCP registration change."""
    found = unmatched_never_defer(registry, config)
    for item in found:
        if item not in _unmatched_warned:
            _unmatched_warned.add(item)
            logger.warning(item.message())
    return found


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
