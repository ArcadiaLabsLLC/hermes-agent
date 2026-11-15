"""Which of an ``act`` monitor's listed actions its persona's chat cannot reach (row
``RT-LENS-ACT-PERSONA-LACKS-LISTED-TOOLS``).

Seen live 2026-11-14: a persona whose chat lane carried no file or terminal tools sealed an ``act``
monitor listing ``write_file`` and ``terminal``; every call answered "not available in this execution
context" before the act gate saw it, so the monitor could never act and nothing said why. An act turn
runs on a ``bounded`` chat, so the answer is that lane's: the persona's declared toolsets with the chat
capabilities added, the chat-lane cost policy applied (with the persona's
``chat_lane_restore_toolsets``), and the policy's single-tool drops removed — the same helpers the turn
resolves through (``chat_lane_scope``), never a copy.

``runtime.lens.get`` carries the answer as ``act_tools: null | {persona_id, missing: [tool], restore_hint}``
for an ``act`` monitor.
"""

from __future__ import annotations

import logging
from typing import Any

__layer__ = "lanes"

logger = logging.getLogger(__name__)

RESTORE_HINT = "agent_runtime.personas.<persona_id>.chat_lane_restore_toolsets"


def _persona(persona_id: str) -> Any | None:
    from ..agent_create.request import persona_roster

    return next((p for p in persona_roster() if p.id == persona_id), None)


def chat_lane_tools(persona: Any) -> frozenset[str]:
    """The tool names a ``bounded`` chat of ``persona`` carries."""

    from model_tools import get_toolset_for_tool
    from toolsets import resolve_toolset

    from ..chat_lane_scope import _augment_chat_capabilities
    from ..chat_lane_toolsets import chat_lane_tool_drops, scope_chat_lane_toolsets
    from ..config import chat_lane_restore_toolsets
    from ..persona_profiles import effective_toolsets

    restore = chat_lane_restore_toolsets(persona.id)
    kept = scope_chat_lane_toolsets(_augment_chat_capabilities(persona, list(effective_toolsets(persona))),
                                    restore=restore)
    tools = {tool for toolset in kept for tool in resolve_toolset(toolset)}
    dropped = {drop.subject for drop in chat_lane_tool_drops(restore=restore, persona_id=persona.id,
                                                             enabled_toolsets=kept,
                                                             toolset_for_tool=get_toolset_for_tool)}
    return frozenset(tools - dropped)


def act_tools(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    """For an ``act`` manifest: the listed actions its persona's chat lacks. None for any other level."""

    if not manifest or manifest["automation"]["level"] != "act":
        return None
    persona_id = manifest.get("persona_id")
    actions = list(manifest["automation"].get("actions", []))
    out = {"persona_id": persona_id, "missing": [], "restore_hint": RESTORE_HINT}
    if persona_id is None or not actions:
        return out
    try:
        persona = _persona(persona_id)
        if persona is None:
            return {**out, "missing": actions, "persona_missing": True}
        carried = chat_lane_tools(persona)
    except Exception:  # an answer that cannot be read is said, never a silent "all present"
        logger.warning("lens act tools: could not resolve persona %s", persona_id, exc_info=True)
        return {**out, "missing": None}
    return {**out, "missing": [tool for tool in actions if tool not in carried]}
