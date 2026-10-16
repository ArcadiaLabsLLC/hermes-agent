"""The managed local llama context-floor exemption — the fork's one owner of both seams.

Upstream rejects any window below ``MINIMUM_CONTEXT_LENGTH`` (64K), for the main model in
``agent/agent_init.py::_enforce_minimum_context`` and for the compression aux model in
``agent/conversation_compression.py::check_compression_model_feasibility``. A managed
``local-llama-hermes`` turn runs the sub-64K window the router actually loaded, pinned by the
adapter's read projection; each seam asks this module one question and keeps one ``or`` operand.

The door is a configurable floor upstream (PR #87515, global, read through the #125624 overlay);
until it lands this is the carry (``upstream-footprint-ledger.md`` rows for both files).
"""

from __future__ import annotations

from typing import Any, Callable

__layer__ = "lanes"

# The smallest window a managed local turn may run below the floor.
_MANAGED_LOCAL_MIN_CONTEXT = 4096


def managed_local_marker():
    """The managed local llama turn marker, read from its one owner (the adapter).

    A wheel without the adapter (the bundled phone) has no managed local turn: None, never imported.
    """
    from agent_runtime.loop_tool_lifecycles import shipped
    if not shipped("agent_runtime.local_llama_adapter"):
        return None
    import agent_runtime.local_llama_adapter as _lla
    return _lla.FLOOR_EXEMPTION_REQUESTED_PROVIDER


def allows_main_context(agent: Any, ctx: Any) -> bool:
    """True when the main model's sub-floor window ``ctx`` is a managed local turn's pinned window."""
    _marker = managed_local_marker()
    return (
        _marker is not None and agent.requested_provider == _marker and agent.provider == "custom"
        and isinstance(agent._config_context_length, int)
        and not isinstance(agent._config_context_length, bool)
        and agent._config_context_length >= _MANAGED_LOCAL_MIN_CONTEXT and ctx == agent._config_context_length
    )


def allows_aux_floor(
    agent: Any, aux_model: Any, aux_context: Any, aux_base_url: Any,
    inherits_main_route: Callable[[Any, Any, Any], bool],
) -> bool:
    """True when the compression aux model IS the managed local main model on its own route.

    ``inherits_main_route`` is upstream's ``_aux_inherits_main_route``, passed in by the seam.
    """
    _marker = managed_local_marker()
    return (
        _marker is not None
        and getattr(agent, "requested_provider", None) == _marker
        and getattr(agent, "provider", None) == "custom"
        and aux_model == agent.model
        and aux_context == agent.context_compressor.context_length
        and aux_context >= _MANAGED_LOCAL_MIN_CONTEXT
        and inherits_main_route(agent, aux_model, aux_base_url)
    )


__all__ = ["allows_aux_floor", "allows_main_context", "managed_local_marker"]
