"""Toolset NAMES of a declaration, composites expanded (moved out of ``toolsets.py``, lane PF-3).

Reads only upstream's public ``toolsets.TOOLSETS`` dict — no registry import — except
:func:`unknown_toolset_names`, which reaches the registry only for a name the static
tables do not know, and never through ``model_tools``.
"""

from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from toolsets import TOOLSETS

from agent_runtime.harness_toolset import ensure_harness_core

__layer__ = "models"

ensure_harness_core()  # the fork's composite is expanded here without the plugin loaded


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


#: Toolsets named by this prefix are MCP servers, registered per run by admission
#: (``mcp_admission``) — absent from every static table by design, so never "unknown".
MCP_TOOLSET_PREFIX = "mcp-"


def unknown_toolset_names(names: Iterable[str]) -> Tuple[str, ...]:
    """The names in ``names`` no toolset authority knows, in order, deduped.

    Known means: a ``toolsets.TOOLSETS`` key, a builtin toolset in the committed
    manifest (``tools.toolset_manifest`` — ``agent_chat``, ``board`` and
    ``browser-cdp`` are registry-only and live there, not in ``TOOLSETS``), an
    ``mcp-*`` name (admission's domain), or a toolset a loaded PLUGIN registered.

    Cheap on the common path: the plugin registry is consulted only for a name
    both static tables miss, so a clean declaration never discovers plugins. When
    it is consulted it is through ``hermes_cli.plugins.discover_plugins()`` (the
    same idempotent door ``tool_visibility`` uses), never ``import model_tools`` —
    the declaration read stays registrar-free (S0a A6a).
    """

    pending: List[str] = []
    for name in names or ():
        text = str(name or "").strip()
        if text and text not in pending and text not in TOOLSETS and not text.startswith(MCP_TOOLSET_PREFIX):
            pending.append(text)
    if not pending:
        return ()
    from tools.toolset_manifest import builtin_toolset_names

    builtin = set(builtin_toolset_names())
    pending = [name for name in pending if name not in builtin]
    if not pending:
        return ()
    try:
        from hermes_cli.plugins import discover_plugins
        from tools.registry import registry

        discover_plugins()
        registered = {str(name) for name in registry.get_registered_toolset_names()}
    except Exception:  # pragma: no cover - a plugin fault must not break a declaration read
        registered = set()
    return tuple(name for name in pending if name not in registered)
