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
    token = _PERSONA_TURN_AGENT.set(agent)
    try:
        yield
    finally:
        _PERSONA_TURN_AGENT.reset(token)


def current_persona_turn_agent() -> Any:
    return _PERSONA_TURN_AGENT.get()
