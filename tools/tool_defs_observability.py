"""Fork-owned half of ``model_tools.get_tool_definitions``: the per-thread memo hit/miss
counters the init-phase receipts read (``agent_runtime/init_observability.py``), and the
standalone ``tool_describe`` injection (CARRY per PAR-DESIGN 7b: bridge dispatch precedes
every hook).

Moved out of ``model_tools.py`` by lane FOOTPRINT-DROP (2026-09-27); the upstream module
keeps one import, two counter bumps and one injection call. The counters retire with an
init-phase widening PR, the injection with a tool-filter/injection hook PR.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("model_tools")

_tool_defs_counters = threading.local()


def bump_tool_defs_counter(name: str) -> None:
    setattr(_tool_defs_counters, name, getattr(_tool_defs_counters, name, 0) + 1)


def ensure_plugin_tools_discovered() -> bool:
    """Discover plugins for the ACTIVE home before a schema recomputation walks the registry.

    ``model_tools`` discovers once at import, but plugin managers are per resolved home: a
    process that later serves another profile (or re-homes) found its plugin tools only when
    something inside the walk lazily discovered them, so the first tool list of that home
    lacked ``skill_search`` and the second had it (h10b-fix, owner 2026-09-29). Idempotent;
    runs only on a memo miss (never on the hit path: an idempotent call still resolves the home).

    Returns True when this call changed the registry generation — a first discovery registers
    the plugin's tools — so the caller re-keys its memo AFTER it; keyed before, the first list
    of a home was stored under a generation that no longer exists and built a second time.
    """
    try:
        from hermes_cli.plugins import discover_plugins
        from tools.registry import registry

        before = registry._generation
        discover_plugins()
        return registry._generation != before
    except Exception as exc:  # pragma: no cover — never break tool loading
        logger.debug("plugin discovery before tool definitions failed: %s", exc)
        return False


def tool_defs_cache_hits_this_thread() -> int:
    """This thread's cumulative ``get_tool_definitions`` memo HITS."""

    return int(getattr(_tool_defs_counters, "hits", 0))


def tool_defs_cache_misses_this_thread() -> int:
    """This thread's cumulative ``get_tool_definitions`` memo MISSES.

    A miss is a real schema recomputation: the registry walk, the per-tool
    schema filter and the ``check_fn`` sweep behind ``registry.get_definitions``.
    """

    return int(getattr(_tool_defs_counters, "misses", 0))


def with_tool_describe(filtered_tools, skip_tool_search_assembly: bool):
    """``filtered_tools`` with the standalone ``tool_describe`` present, unless the
    tool-search assembly is skipped or the list is empty; a failure leaves it as it was."""
    if skip_tool_search_assembly or not filtered_tools:
        return filtered_tools
    try:
        from tools.tool_search_downstream import ensure_tool_describe_present

        return ensure_tool_describe_present(filtered_tools)
    except Exception as exc:
        logger.warning("tool_describe injection skipped: %s", exc)
        return filtered_tools
