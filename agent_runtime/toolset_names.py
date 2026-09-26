"""Toolset NAMES of a declaration, composites expanded (moved out of ``toolsets.py``, lane PF-3).

Reads only upstream's public ``toolsets.TOOLSETS`` dict — no registry import.
"""

from __future__ import annotations

from typing import List, Set

from toolsets import TOOLSETS

__layer__ = "models"


def expand_toolset_names(names) -> List[str]:
    """Replace a composite toolset with its member toolset NAMES, recursively.

    A composite here is a ``TOOLSETS`` entry that has ``includes`` and no direct
    ``tools`` of its own (``harness_core``, ``safe``, ``hermes-gateway``). Leaf
    toolsets, composites that DO carry their own tools (``debugging``),
    registry-only names (``agent_chat``, ``board``, ``mcp-*``) and unknown names
    pass through unchanged.

    Order-preserving and deduped: the first appearance of a name wins, and a
    cycle or diamond contributes its members once.

    Static by construction — it reads only the ``TOOLSETS`` dict and never
    touches the tool registry, so a caller can answer "which toolsets does this
    persona declare" without importing ``model_tools`` (S0a A6a). Callers that
    need the TOOL names still resolve through ``resolve_toolset``.

    Why names and not tools: the bounded chat lane's cost policy
    (``agent_runtime.chat_lane_toolsets.scope_chat_lane_toolsets``) drops by
    toolset NAME, so a declaration left as ``["harness_core"]`` would slip past
    a policy that removes ``browser``.
    """

    out: List[str] = []
    seen: Set[str] = set()

    def _walk(name: str, visiting: Set[str]) -> None:
        text = str(name or "").strip()
        if not text or text in seen:
            return
        definition = TOOLSETS.get(text)
        includes = list(definition.get("includes", []) or []) if definition else []
        tools = list(definition.get("tools", []) or []) if definition else []
        if not definition or not includes or tools or text in visiting:
            seen.add(text)
            out.append(text)
            return
        for member in includes:
            _walk(member, visiting | {text})

    for entry in names or []:
        _walk(entry, set())
    return out
