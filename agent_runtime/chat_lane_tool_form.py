"""The chat lane's tool form: one owner of a persona chat actor's ``tools``.

Plan ``docs/agent-runtime-harness/planned/tool-form-one-owner-2026-10-08.md``. The
per-persona defer's construction door (:func:`apply_chat_lane_defer`) lives here; the
turn's bridge binding stays in :mod:`agent_runtime.chat_lane_defer`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Iterable

from agent_runtime.tool_blocks import _tool_name as _def_name

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The agent attribute that carries the persona's defer set from construction to its turns.
AGENT_DEFER_ATTR = "_chat_lane_defer_tools"
#: The names the re-assembly actually took off the eager list (a never-defer promotion, or a
#: name the lane never produced, is not one): the drift :func:`reapply_chat_lane_defer` watches.
_EFFECTIVE_ATTR = "_chat_lane_defer_effective"


def apply_chat_lane_defer(agent: Any, defer_tools: Iterable[str] | None) -> bool:
    """Re-assemble ``agent.tools`` with ``defer_tools`` deferred; True when it changed.

    The incoming list is the lane's RAW definitions (assembly skipped) plus every
    definition the constructor appended outside ``get_tool_definitions`` (memory
    provider / context-engine tools), so the listing names every deferred tool — the
    curated ones the constructor already deferred included. Never raises: a fault
    leaves the constructor's list, which is the profile-wide form, not a broken one.
    """

    names = frozenset(str(n).strip() for n in (defer_tools or ()) if str(n).strip())
    setattr(agent, AGENT_DEFER_ATTR, names)
    if not names or not getattr(agent, "tools", None):
        return False
    try:
        import model_tools
        from tools.tool_search import BRIDGE_TOOL_NAMES, assemble_tool_defs, load_config
        from tools.tool_search_downstream import ensure_tool_describe_present

        base = load_config()
        if base.enabled == "off":
            return False
        raw = model_tools.get_tool_definitions(
            enabled_toolsets=getattr(agent, "enabled_toolsets", None),
            disabled_toolsets=getattr(agent, "disabled_toolsets", None),
            quiet_mode=True,
            skip_tool_search_assembly=True,
        ) or []
        raw_names = {_def_name(td) for td in raw}
        extras = [
            td for td in agent.tools
            if _def_name(td) not in raw_names and _def_name(td) not in BRIDGE_TOOL_NAMES
        ]
        compressor = getattr(agent, "context_compressor", None)
        context_length = int(getattr(compressor, "context_length", 0) or 0) or None
        assembly = assemble_tool_defs(
            list(raw) + extras,
            context_length=context_length,
            config=replace(base, defer_tools=frozenset(base.effective_defer_tools) | names),
        )
        tools = ensure_tool_describe_present(assembly.tool_defs)
    except Exception:  # pragma: no cover - a defer is a cost cut; never fail construction over it
        logger.warning("chat-lane defer skipped; the profile-wide tool list stands", exc_info=True)
        return False
    agent.tools = tools
    agent.valid_tool_names = {_def_name(td) for td in tools if _def_name(td)}
    setattr(agent, _EFFECTIVE_ATTR, frozenset(names & raw_names) - agent.valid_tool_names)
    # The executor caches the bridge's reachable set per agent; it was computed (if at all)
    # without the persona's names.
    if hasattr(agent, "_tool_search_scope_cache"):
        agent._tool_search_scope_cache = None
    return True


__all__ = [
    "AGENT_DEFER_ATTR",
    "apply_chat_lane_defer",
]
