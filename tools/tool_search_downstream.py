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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from tools.mcp_tool_schema import mcp_prefixed_tool_name, sanitize_mcp_name_component
from tools.tool_search_catalog import BRIDGE_TOOL_NAMES, TOOL_DESCRIBE_NAME

#: Top search hits that carry their full ``parameters`` schema, and its size bound.
_SEARCH_HIT_SCHEMA_TOP_N = 3
_SEARCH_HIT_SCHEMA_MAX_CHARS = 6000


def _chat_def_name(td: Any) -> Any:
    """A chat-shape tool-def's ``function.name`` (None when absent or not a dict)."""
    if not isinstance(td, dict):
        return None
    return (td.get("function") or {}).get("name")


def _is_registered_tool(name: str) -> bool:
    """Whether the live registry holds ``name``; a raising registry reads as unregistered."""
    try:
        from tools.registry import registry

        return registry.get_entry(name) is not None
    except Exception:
        return False


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
#: ``capture_screenshot`` left the set (lane h-prompt-tools, ruling R2, 2026-10-05): zero calls on
#: record, and ``screenshot_window`` is the verb the screenshot skill teaches; it rides the listing.
_MCP_NEVER_DEFER_VERBS = {
    "launcher_qa": (
        "mcp_launcher_qa_open_app_tab",
        "mcp_launcher_qa_screenshot_window",
        "mcp_launcher_qa_launch_or_attach",
    ),
}
_MCP_NEVER_DEFER = {
    server: frozenset(mcp_prefixed_tool_name(server, verb) for verb in verbs)
    for server, verbs in _MCP_NEVER_DEFER_VERBS.items()
}
_LAUNCHER_QA_CORE_TOOLS = _MCP_NEVER_DEFER["launcher_qa"]
#: Every promoted MCP tool under its registered name: the set whose wire text is briefed
#: (``tools.downstream_schema.promoted_brief``), since the server's own manual rides eagerly.
PROMOTED_MCP_TOOLS: frozenset[str] = frozenset().union(*_MCP_NEVER_DEFER.values())
_NEVER_DEFER_TOOLS = _BUILTIN_NEVER_DEFER | PROMOTED_MCP_TOOLS


def never_defer_tool_names(config=None) -> frozenset[str]:
    """Promotions plus this connection's host preferences and config extension.

    Config EXTENDS the set; nothing in config can remove a hardcoded name.
    """
    if config is None:
        from tools.tool_search import load_config_readonly

        config = load_config_readonly()  # no write on discovery
    from agent_runtime.launcher_app_functions import always_loaded_app_function_tools

    return (_NEVER_DEFER_TOOLS | always_loaded_app_function_tools() |
            frozenset(config.never_defer or ()))


logger = logging.getLogger("tools.tool_search")


#: The running turn's per-persona defer extension (lane h-prompt-tools S1). The chat lane
#: re-assembles its agent's eager list with these names deferred
#: (``agent_runtime.chat_lane_defer``); the bridge's reads — the search catalog, the
#: ``tool_call`` resolve and scope checks — load their config through
#: ``tools.tool_search.load_config_readonly``, which unions this set in, so a tool the
#: persona deferred is found and callable through the bridge exactly as a curated one is.
#: The assembly loader (``load_config``) never reads it: ``get_tool_definitions`` memoizes
#: its assembled list per toolset selection, and a persona's set must not reach that memo.
_TURN_DEFER_TOOLS: ContextVar[frozenset] = ContextVar("eternia_turn_defer_tools", default=frozenset())


@contextmanager
def scoped_turn_defer(names: Iterable[str] | None) -> Iterator[None]:
    """Bind ``names`` as this turn's defer extension for the bridge's config reads."""
    token = _TURN_DEFER_TOOLS.set(frozenset(str(n) for n in (names or ()) if str(n).strip()))
    try:
        yield
    finally:
        _TURN_DEFER_TOOLS.reset(token)


def with_turn_defer(config):
    """``config`` with the bound turn's defer extension unioned into ``defer_tools``.

    Deferring is never a grant: a name only matters if the session's own toolsets
    produced its definition, and the bridge's scope checks still require that."""
    extra = _TURN_DEFER_TOOLS.get()
    if not extra:
        return config
    return replace(config, defer_tools=frozenset(config.effective_defer_tools) | extra)


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
    "Invoke a deferred local tool with its own tool_call (calls: an array of ONE entry); "
    "a tool already in your tool list is called by name. Only connectors__ names may be "
    "batched in one tool_call."
)

#: Stamped on a search result that found an eager tool for a query.
DIRECT_CALL_RULE = (
    "Names under directly_available are already in your tool list: call them by name, "
    "not through tool_call."
)


# ── one door for a name the session already has (lane bridge-direct, 2026-10-08) ────
#
# Upstream's bridge refuses a ``tool_call`` that names a directly-listed tool and tells
# the model to call it by name. On the chat lane that correction costs a full provider
# round trip (a ~50K-token request, 4–16 s) for a call whose intent was unambiguous;
# Amelia turn ``agent-chat-send-db7a2d34`` (2026-10-08) paid it for
# ``launcher_generated_list`` while the same name sat in its eager list. Both vendors'
# native discovery dispatch a discovered tool by name through one door, so the fork
# admits an in-scope eager name through the bridge and keeps upstream's correction for
# the one case it is right about: an UNKNOWN name. Scope is the union the executor and
# the dispatcher already check — a name must be in the session's own definitions — so
# this grants nothing; it only stops refusing what the session already offers.


def directly_available_names(tool_defs) -> frozenset[str]:
    """The names in ``tool_defs`` the model may call by name: scoped, not deferrable, not a bridge tool.

    Read from the session's PRE-ASSEMBLY definitions, the same list the bridge's scope
    checks read, so an eager tool the session never produced is not admitted here either.
    """
    from tools.tool_search import is_deferrable_tool_name, load_config_readonly

    config = load_config_readonly()
    defer = config.effective_defer_tools
    names = set()
    for td in tool_defs or ():
        name = _chat_def_name(td)
        if not name or name in BRIDGE_TOOL_NAMES:
            continue
        if not is_deferrable_tool_name(name, defer, config=config):
            names.add(name)
    return frozenset(names)


def admit_direct_in_resolve(upstream):
    """``resolve_underlying_call`` that admits a registered eager name instead of refusing it.

    Upstream's answer stands for everything else: a connector batch, a multi-entry local
    batch, a bridge name, and an unknown name — the last keeps its "did you mean" correction,
    which is the one the model actually needs.
    """

    def resolve_underlying_call(args):
        name, raw_args, err = upstream(args)
        if err is None:
            return name, raw_args, err
        from tools.connectors import is_connector_name
        from tools.tool_search_validation import normalize_tool_call_entries

        entries, parse_err = normalize_tool_call_entries(args)
        if parse_err or len(entries) != 1:
            return name, raw_args, err
        candidate = entries[0]["name"]
        if is_connector_name(candidate) or not _is_registered_tool(candidate):
            return name, raw_args, err
        return candidate, entries[0]["arguments"], None

    resolve_underlying_call.__doc__ = (upstream.__doc__ or "") + "\n\nFork: a registered eager name is admitted, not refused (tool_search_downstream)."
    return resolve_underlying_call


def admit_direct_in_scope(upstream):
    """``scoped_deferrable_names`` widened to the names the bridge may reach: deferred OR eager, in scope.

    Both scope checks — ``model_tools._dispatch_bridge_tool`` and the executor's unwrap —
    read this one function, so the eager admission and the deferred admission cannot drift.
    """

    def scoped_deferrable_names(tool_defs):
        return frozenset(upstream(tool_defs)) | directly_available_names(tool_defs)

    scoped_deferrable_names.__doc__ = (upstream.__doc__ or "") + "\n\nFork: eager names in scope are included (tool_search_downstream)."
    return scoped_deferrable_names


def mark_direct_hits(upstream):
    """``dispatch_tool_search`` that also says which EAGER tools answer a query.

    Upstream's catalog holds deferrable tools only, so a search for a capability the
    session already has eagerly returned its deferred siblings and hid the one to call
    (``launcher generated list`` → inspect/edit/update, 2026-10-08). The eager subset is
    searched with the same scorer and reported under ``directly_available`` per query,
    beside the unchanged ``matches``; nothing is added to ``tools`` because those schemas
    are already on the wire.
    """

    def dispatch_tool_search(args, *, current_tool_defs, config=None, connector_search=None):
        raw = upstream(args, current_tool_defs=current_tool_defs, config=config,
                       connector_search=connector_search)
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return raw
        from tools.tool_search_catalog import build_catalog, search_catalog

        direct = directly_available_names(current_tool_defs)
        eager_defs = [td for td in current_tool_defs or () if _chat_def_name(td) in direct]
        if not eager_defs:
            return raw
        catalog = build_catalog(eager_defs)
        try:
            limit = max(1, min(int((args or {}).get("limit") or 5), 25))
        except (TypeError, ValueError):
            limit = 5
        marked = False
        for group in results:
            if not isinstance(group, dict):
                continue
            hits = search_catalog(catalog, str(group.get("query") or ""), limit=limit)
            if hits:
                group["directly_available"] = [hit.name for hit in hits]
                marked = True
        if marked:
            payload["direct_rule"] = DIRECT_CALL_RULE
        return json.dumps(payload, ensure_ascii=False)

    dispatch_tool_search.__doc__ = (upstream.__doc__ or "") + "\n\nFork: eager hits are reported as directly_available (tool_search_downstream)."
    return dispatch_tool_search


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
