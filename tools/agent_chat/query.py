"""``harness_query`` — the in-turn, read-only harness lookup (HQ1).

Answers the four questions an agent keeps asking before it acts — the roster,
one instance (with the MCP servers it resolves as configured/admitted now), an
instance's chat sessions with their hot/busy/cold state, and whether a live QA
session exists — from ONE core, :mod:`agent_runtime.harness_query`, which the
``hermes harness query`` verb answers from too. In-process: no subprocess, no
snapshot, no mint, a few hundred bytes to a few KB per answer. A turn running in
the serve reads the serve's own resident-actor registry, so its runtime states
are observed; any other process says ``unknown`` and names itself as observer.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.harness_query import QUESTIONS, answer

__layer__ = "lanes"

__all__ = ["HARNESS_QUERY_SCHEMA", "harness_query"]

HARNESS_QUERY_SCHEMA = {
    "name": "harness_query",
    "description": (
        "Read-only harness lookup, cheap enough for every turn. question=roster (persona instances), "
        "instance (one instance + the MCP servers it resolves as configured/admitted now), sessions "
        "(an instance's chat sessions with hot/busy/cold runtime_state), live_qa (live or resumable QA "
        "sessions by exact id, with a verdict). Use this instead of `hermes harness snapshot`; cite the "
        "ids it returns."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            # The core's own question names: the tool and the verb cannot drift.
            "question": {"type": "string", "enum": list(QUESTIONS)},
            "instance": {"type": "string", "description": "Persona-instance id or persona id (instance, sessions)."},
            "limit": {"type": "integer", "description": "Most sessions to return (default 10, max 50)."},
        },
        "required": ["question"],
    },
}


def harness_query(question: Any = None, *, instance: Any = None, limit: Any = None) -> str:
    """One core answer as JSON; an unknown or missing question is a typed refusal."""

    return json.dumps(answer(str(question or ""), instance=instance, limit=limit), default=str)
