"""The chat lane's per-persona defer: tools the persona never calls ride the bridge listing.

Lane h-prompt-tools S1 (``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md``).
The tool-search assembly upstream runs inside the agent constructor reads ONE config —
the profile's ``tools.tool_search`` — and the profile is shared by every persona bound to
it, so a supervisor's never-called tools (``delegate_task``, ``memory``, the browser
vault, ...) rode every first turn of every chat at ~5.9k tokens. The per-persona list is
``agent_runtime.personas.<id>.chat_lane_defer_tools`` (``config.knobs.chat_lane_defer_tools``,
carried on the chat-lane bundle and the run request); this module applies it through two
doors, both fork-only:

* **construction** — :func:`apply_chat_lane_defer` re-runs upstream's
  ``assemble_tool_defs`` on the lane's raw tool definitions with the profile's config
  plus the persona's names (``assemble_tool_defs`` is idempotent and takes ``config=``),
  and publishes the result as the agent's ``tools`` / ``valid_tool_names``
  (``profile_runner.runner._default_agent_factory``, before the run's block is pruned);
* **the bridge** — the run binds the same names for its turn
  (``tools.tool_search_downstream.scoped_turn_defer``), so ``tool_search`` finds them and
  ``tool_call`` resolves them as it does any curated deferred tool.

A tool-set refresh mid-session (``tools.mcp_tool_agent``) re-derives ``agent.tools`` from
the profile-wide assembly; :func:`reapply_chat_lane_defer` restores the persona's form
before the next provider request (``tool_blocks.reprune_turn_agent``).
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


def reapply_chat_lane_defer(agent: Any) -> bool:
    """Restore the persona's form when a refresh brought a deferred tool back eager."""

    names = getattr(agent, AGENT_DEFER_ATTR, None)
    effective = getattr(agent, _EFFECTIVE_ATTR, None)
    if not names or not effective:
        return False
    eager = set(getattr(agent, "valid_tool_names", None) or ())
    if not (eager & set(effective)):
        return False
    return apply_chat_lane_defer(agent, names)


def turn_defer_tools(agent: Any) -> frozenset[str]:
    """The defer set a turn binds for the bridge (``tool_search_downstream.scoped_turn_defer``)."""

    return frozenset(getattr(agent, AGENT_DEFER_ATTR, None) or ())


__all__ = [
    "AGENT_DEFER_ATTR",
    "apply_chat_lane_defer",
    "reapply_chat_lane_defer",
    "turn_defer_tools",
]
