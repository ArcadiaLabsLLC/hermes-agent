"""The persona agent of the turn running in this context, for plugin middleware.

``profile_runner`` binds the agent it built around ``run_conversation``. The eternia-harness
plugin's ``llm_request`` / ``llm_execution`` middleware run synchronously in that turn's
thread, so they read the binding instead of the middleware context having to carry the
agent (upstream's context names the request, never the agent). Unbound = not a persona
turn, and every reader passes through.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

__layer__ = "policy"

_PERSONA_TURN_AGENT: ContextVar[Any] = ContextVar("eternia_persona_turn_agent", default=None)


@contextmanager
def bind_persona_turn_agent(agent: Any) -> Iterator[None]:
    agent._hermes_turn_wire_tool_receipt = None
    token = _PERSONA_TURN_AGENT.set(agent)
    try:
        yield
    finally:
        _PERSONA_TURN_AGENT.reset(token)


def current_persona_turn_agent() -> Any:
    return _PERSONA_TURN_AGENT.get()


def capture_final_request_tools(request: Any) -> None:
    """First dispatched request's counts/order, captured after the fork's rewrites."""
    import json
    agent = current_persona_turn_agent()
    if agent is None or getattr(agent, "_hermes_turn_wire_tool_receipt", None) is not None:
        return
    if not isinstance(request, dict) or not isinstance(request.get("tools"), list):
        return
    tools = request["tools"]
    # The middleware runs AFTER the transport built the request (``agent/turn_api_request.py``:
    # ``_build_api_kwargs``, then ``apply_llm_request_middleware``), so a provider-reserved name
    # is already aliased here (``hermes_tool_search`` on OpenAI/xAI Responses, xAI chat). The
    # names stay the wire's; the transport's ``{alias: name}`` rides beside them so a reader can
    # join the wire to the surface (``tool_surface.unaliased_wire_names``).
    aliases = _wire_aliases(agent)
    names = []
    chars = {}
    listing_chars = 0
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(function.get("name") or "")
        if not name:
            continue
        names.append(name)
        chars[name] = len(json.dumps(tool, ensure_ascii=False, separators=(",", ":"), default=str))
        if aliases.get(name, name) == "tool_search":
            _, _, listing = str(function.get("description") or "").partition("\n\n")
            listing_chars = len(listing)
    agent._hermes_turn_wire_tool_receipt = {
        "names": names, "per_tool_chars": chars, "listing_chars": listing_chars,
        "bridge_aliases": {alias: real for alias, real in aliases.items() if alias in names},
        "json_bytes": len(json.dumps(tools, ensure_ascii=False, default=str).encode("utf-8")),
    }


def _wire_aliases(agent: Any) -> dict[str, str]:
    """The ``{alias: name}`` map the agent's transport recorded for the request it just built."""

    try:
        transport = (getattr(agent, "_transport_cache", None) or {}).get(getattr(agent, "api_mode", None))
        aliases = getattr(transport, "_last_wire_aliases", None)
    except Exception:  # noqa: BLE001 - a receipt never fails a request
        return {}
    return {str(k): str(v) for k, v in aliases.items()} if isinstance(aliases, dict) else {}
