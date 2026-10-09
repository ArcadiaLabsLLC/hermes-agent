"""The chat lane's per-persona defer: tools the persona never calls ride the bridge listing.

Lane h-prompt-tools S1 (``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md``).
The tool-search assembly upstream runs inside the agent constructor reads ONE config —
the profile's ``tools.tool_search`` — and the profile is shared by every persona bound to
it, so a supervisor's never-called tools (``delegate_task``, ``memory``, the browser
vault, ...) rode every first turn of every chat at ~5.9k tokens. The per-persona list is
``agent_runtime.personas.<id>.chat_lane_defer_tools`` (``config.knobs.chat_lane_defer_tools``,
carried on the chat-lane bundle and the run request); this module applies it through two
doors, both fork-only:

* **construction and every turn** — the tool form's one owner,
  :mod:`agent_runtime.chat_lane_tool_form` (:func:`apply_chat_lane_defer` from
  ``profile_runner.runner._default_agent_factory``, ``settle_turn_tool_form`` from the
  eternia-harness ``pre_llm_call`` hook): upstream's ``assemble_tool_defs`` over the lane's
  raw definitions with the persona's names deferred;
* **the bridge** — the run binds the same names for its turn
  (``tools.tool_search_downstream.scoped_turn_defer``), so ``tool_search`` finds them and
  ``tool_call`` resolves them as it does any curated deferred tool.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.chat_lane_tool_form import (  # noqa: F401 — re-exported
    AGENT_DEFER_ATTR,
    apply_chat_lane_defer,
)

__layer__ = "policy"


def turn_defer_tools(agent: Any) -> frozenset[str]:
    """The defer set a turn binds for the bridge (``tool_search_downstream.scoped_turn_defer``)."""

    return frozenset(getattr(agent, AGENT_DEFER_ATTR, None) or ())


__all__ = [
    "AGENT_DEFER_ATTR",
    "apply_chat_lane_defer",
    "turn_defer_tools",
]
