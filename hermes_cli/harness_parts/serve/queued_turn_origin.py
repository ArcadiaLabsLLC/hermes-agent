"""Who sent a queued chat send, and where its turn answers when it runs.

Owner ruling 2026-10-10 (``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``
§ "Origin"): a send that queued behind a busy root runs later, with no serve request of its
own, yet must get what a direct run of the same send gets:

- the same app-function link (``ArgvLanes._bind_launcher_link``), so the same tool set: the
  sender's own Launcher connection when it is still attached and answers ``launcher.``
  requests, else the rule a gateway turn already uses (the stdio starter, else the most
  recent local socket connection that declared it answers), else none.

The origin is persisted on the queued entry (``chat_root_send_queue.ORIGIN_ARG``) as
``{"owner": <connection key> | "stdio" | None, "gateway": bool}``; ``owner`` is ``None`` for
a send that reached the door with no serve request (a one-shot CLI).
"""

from __future__ import annotations

import logging
from typing import Any

from agent_runtime.launcher_app_functions import (
    ORIGIN_LOCAL,
    ORIGIN_PAIRED_DEVICE,
    LauncherLink,
    answers_launcher_requests,
    refresh_app_function_tools,
)
from hermes_cli.harness_parts.serve.frames import _request_id, _request_sink
from hermes_cli.harness_parts.serve.manifest import _is_gateway

__layer__ = "lanes"

__all__ = ["queued_turn_link", "send_origin"]

logger = logging.getLogger(__name__)

def send_origin() -> dict[str, Any]:
    """The origin of the send running on this thread, from the serve request it arrived on."""

    if _request_id.get() is None:
        return {"owner": None, "gateway": False}
    sink = _request_sink.get()
    if sink is None:
        return {"owner": "stdio", "gateway": False}
    connection = getattr(sink, "_target", None)
    key = getattr(connection, "key", None)
    return {"owner": None if key is None else str(key), "gateway": bool(_is_gateway(connection))}


def _origin(entry: Any) -> dict[str, Any]:
    from agent_runtime.chat_root_send_queue import ORIGIN_ARG

    value = (getattr(entry, "args", None) or {}).get(ORIGIN_ARG)
    return value if isinstance(value, dict) else {}


def _live_sink(session: Any, owner: Any) -> Any:
    if owner == "stdio":
        frames = getattr(session, "frames", None)
        return None if getattr(frames, "detached", False) else frames
    lock, sinks = getattr(session, "connection_sinks_lock", None), getattr(session, "connection_sinks", None)
    if owner is None or lock is None or sinks is None:
        return None
    with lock:
        return sinks.get(str(owner))


def _fallback_sink(session: Any) -> Any:
    answerer = getattr(session, "_gateway_turn_launcher_sink", None)
    return answerer() if callable(answerer) else None


def queued_turn_link(session: Any, entry: Any) -> LauncherLink | None:
    """The link a direct run of this send would bind, refreshed as a direct turn refreshes it."""

    origin = _origin(entry)
    if not origin:
        return None
    if origin.get("gateway"):
        sink, kind = _fallback_sink(session), ORIGIN_PAIRED_DEVICE
    else:
        owner = origin.get("owner")
        sink, kind = _live_sink(session, owner), ORIGIN_LOCAL
        if sink is None:  # the sender is gone (or never had a connection): the gateway rule
            sink = _fallback_sink(session)
        elif not answers_launcher_requests(str(owner)):
            return None  # attached and not a Launcher: a direct run binds none either
    if sink is None:
        return None
    link = LauncherLink(sink, kind)
    try:
        refresh_app_function_tools(link)
    except Exception:  # a tool list must never cost the turn
        logger.warning("launcher app-function refresh failed for a queued turn", exc_info=True)
    return link
