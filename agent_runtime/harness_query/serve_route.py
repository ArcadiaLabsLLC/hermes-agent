"""Ask the RUNNING serve the query, over the loopback socket's argv lane.

Only the serve owns the resident-actor registry, so only it can say whether a
chat session is hot, busy or cold. A CLI one-shot that answered from its own
process would report ``unknown`` for every session while a live serve one
socket away knew the answer. This module carries the CLI's question to that
serve and returns the serve's own answer — no second transport: it is the
reference ``ServeSocketClient``, the same hello ``harness serve connect`` uses,
and the argv lane the serve already runs for its local console. The serve runs
``harness query … --direct``, i.e. the very core this process would have run.

When there is no live serve, or anything on the way fails, the caller reads
directly and the reply says why it did (``answered_by.serve_fallback``).
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "lanes"

__all__ = ["query_argv", "query_via_serve"]

CLIENT_NAME = "harness-query"


def query_argv(question: str, target: str | None, limit: int | None) -> list[str]:
    """The argv the serve runs: the direct form of the same question."""

    argv = ["harness", "query", question]
    if target:
        argv.append(target)
    if limit is not None:
        argv += ["--limit", str(int(limit))]
    return argv + ["--direct", "--json"]


def query_via_serve(
    question: str, target: str | None, limit: int | None, *, timeout_seconds: float = 15.0
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(payload, answered_by)`` from the live serve, or ``(None, why_not)``.

    The dial, hello and frame loop are the shared CLI route's
    (``agent_runtime.serve_socket.cli_route.relay_argv``); a query is a READ, so every
    outcome but a served exit 0 with a JSON body falls back to the direct read, by name.
    """

    from agent_runtime.serve_socket.cli_route import FallbackPolicy, relay_argv

    outcome = relay_argv(query_argv(question, target, limit), client=CLIENT_NAME,
                         dial_seconds=timeout_seconds, request_prefix="query",
                         refuse_self_dial=False)
    if outcome.runs_locally(FallbackPolicy.READ):
        return None, {"lane": "direct_read", "serve_fallback": outcome.reason}
    if outcome.code != 0:
        return None, {"lane": "direct_read", "serve_fallback": f"serve_exit_{outcome.code}"}
    try:
        payload = json.loads("\n".join(outcome.lines))
    except ValueError:
        return None, {"lane": "direct_read", "serve_fallback": "serve_reply_not_json"}
    return payload, {"lane": "serve", "pid": outcome.pid, "boot_id": outcome.boot_id}
