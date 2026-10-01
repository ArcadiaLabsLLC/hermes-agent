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
import uuid
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


#: The frames that end one request: its ``exit``, or an ``error`` (parse
#: failure, handler exit, refusal). ``stderr`` frames share the id and do not.
_TERMINAL_EVENTS = frozenset({"exit", "error"})


def _terminal(frame: dict[str, Any], lines: list[str]) -> tuple[list[str], int | None, str | None]:
    error = frame.get("error")
    if error:
        return lines, None, str(error)
    return lines, int(frame.get("code") or 0), None


def _read_reply(connection: Any, rid: str) -> tuple[list[str], int | None, str | None]:
    """Collect this request's ``line`` frames up to its terminal frame."""

    lines: list[str] = []
    while True:
        frame = connection.read_frame()
        if frame is None:
            return lines, None, "serve_closed_connection"
        if frame.get("id") != rid:
            continue
        if frame.get("event") == "line":
            lines.append(str(frame.get("line") or ""))
        elif frame.get("event") in _TERMINAL_EVENTS:
            return _terminal(frame, lines)


def query_via_serve(
    question: str, target: str | None, limit: int | None, *, timeout_seconds: float = 15.0
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(payload, answered_by)`` from the live serve, or ``(None, why_not)``."""

    from agent_runtime import paths
    from agent_runtime.serve_auth import read_token
    from agent_runtime.serve_socket.client import ServeSocketClient
    from agent_runtime.serve_socket.target import resolve_socket_target

    store_root = paths.store_root()
    target_row = resolve_socket_target(store_root)
    if target_row is None:
        return None, {"lane": "direct_read", "serve_fallback": "no_live_serve_socket"}
    token = read_token(store_root)
    if not token:
        return None, {"lane": "direct_read", "serve_fallback": "no_auth_token"}
    connection = ServeSocketClient(target_row.host, target_row.port, timeout_seconds=timeout_seconds)
    rid = f"query-{uuid.uuid4().hex[:12]}"
    try:
        connection.connect()
        # No client_build: computing the stamp shells out to git (2.9 s measured
        # 2026-10-01) and a read needs no build comparison — the serve answers
        # ``None`` (not comparable) for a client that names none.
        hello = connection.hello(token=token, client=CLIENT_NAME)
        if not isinstance(hello, dict) or hello.get("event") != "hello_ok":
            return None, {"lane": "direct_read", "serve_fallback": "hello_rejected"}
        connection.send({"id": rid, "argv": query_argv(question, target, limit)})
        lines, code, error = _read_reply(connection, rid)
    except Exception as exc:  # noqa: BLE001 - any transport failure falls back, by name
        return None, {"lane": "direct_read", "serve_fallback": f"transport_failed:{type(exc).__name__}"}
    finally:
        connection.close()
    if error is not None or code != 0:
        return None, {"lane": "direct_read", "serve_fallback": error or f"serve_exit_{code}"}
    try:
        payload = json.loads("\n".join(lines))
    except ValueError:
        return None, {"lane": "direct_read", "serve_fallback": "serve_reply_not_json"}
    return payload, {"lane": "serve", "pid": target_row.pid, "boot_id": target_row.boot_id}
