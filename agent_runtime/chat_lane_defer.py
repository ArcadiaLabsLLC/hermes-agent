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
before the next provider request (``tool_blocks.reprune_turn_agent``) -- run by the
eternia-harness ``pre_llm_call`` hook AFTER upstream's between-turns refresh and BEFORE the
turn's first request is assembled, so turn 1 and turn 2 ship one form (lane h-cache-hit).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.chat_lane_tool_form import (  # noqa: F401 — re-exported
    _EFFECTIVE_ATTR,
    AGENT_DEFER_ATTR,
    apply_chat_lane_defer,
)

__layer__ = "policy"


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
