"""``/queue-status`` (alias ``/qstatus``), answered through upstream's ``pre_gateway_dispatch``.

The eternia-harness plugin registers :func:`answer_queue_status`. The hook fires once per
inbound gateway event BEFORE auth and before the busy intercept, with ``event``,
``gateway`` and ``session_store`` — so the command answers on the busy path too, without
a ``CommandDef`` or a gateway handler (lane DOORS-A 2026-09-24; it used to be a
``DownstreamGatewayMixin`` method named in upstream's ``_PLAIN_COMMANDS``). Authorization
is checked here, since the hook runs first; an unauthorized sender falls through to the
normal pipeline, which refuses it as before.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

#: The command and its alias, without the leading slash.
QUEUE_STATUS_COMMANDS = frozenset({"queue-status", "qstatus"})


def _command_name(text: Any) -> str:
    """``queue-status`` for ``/queue-status@bot extra``; "" when the text is not a slash command."""

    head = str(text or "").strip().split(maxsplit=1)
    if not head or not head[0].startswith("/"):
        return ""
    return head[0][1:].split("@", 1)[0].lower()


async def queue_status_report(gateway: Any, event: Any) -> str:
    """The /queue-status report: active-run and queue visibility for the sender's session."""
    from gateway.run import _AGENT_PENDING_SENTINEL
    from tools.process_registry import format_uptime_short

    source = event.source
    # Must go through the awaited facade, not the raw sync store: this is
    # loop-side code and `session_store.get_or_create_session()` does
    # blocking SQLite work that would stall every other gateway turn.
    # Formerly enforced by the AST guard in tests/gateway/test_async_session_store.py,
    # which arrived with the 2026-07-31 upstream merge and was deleted by upstream's
    # 2026-09 test purge (UNCOVERED now); this fork-owned handler was the single
    # violation it found.
    session_entry = await gateway.async_session_store.get_or_create_session(source)
    session_key = session_entry.session_key
    adapter = gateway.adapters.get(source.platform) if source else None
    pending_slot = getattr(adapter, "_pending_messages", {}) if adapter is not None else {}
    current_pending_slot = 1 if session_key in pending_slot else 0
    overflow_depth = len((getattr(gateway, "_queued_events", None) or {}).get(session_key, []))
    explicit_queue_depth = gateway._queue_depth(session_key, adapter=adapter)

    running_agents = getattr(gateway, "_running_agents", {}) or {}
    running_started = getattr(gateway, "_running_agents_ts", {}) or {}
    current_agent = running_agents.get(session_key)
    is_running = session_key in running_agents
    if not is_running:
        state = "idle"
    elif current_agent is _AGENT_PENDING_SENTINEL:
        state = "starting"
    else:
        state = "running"
    start_ts = float(running_started.get(session_key, 0) or 0)
    running_age = (
        format_uptime_short(max(0, int(time.time() - start_ts)))
        if start_ts and is_running
        else "0s"
    )

    total_pending_slots = 0
    for platform_adapter in (getattr(gateway, "adapters", {}) or {}).values():
        total_pending_slots += len(getattr(platform_adapter, "_pending_messages", {}) or {})
    total_overflow_depth = sum(
        len(items) for items in (getattr(gateway, "_queued_events", None) or {}).values()
    )

    lines = [
        "🧭 Gateway queue/status",
        "",
        f"Active agents: {len(running_agents)}",
        f"Current session: {state}",
        f"Running age: {running_age}",
        f"Pending follow-up slot: {current_pending_slot}",
        f"Explicit /queue depth: {explicit_queue_depth}",
        f"Overflow queue depth: {overflow_depth}",
        f"All pending slots: {total_pending_slots}",
        f"All overflow queued: {total_overflow_depth}",
        "",
        "Platforms:",
    ]

    adapters = getattr(gateway, "adapters", {}) or {}
    if adapters:
        for platform in sorted(adapters.keys(), key=lambda p: getattr(p, "value", str(p))):
            name = getattr(platform, "value", str(platform))
            lines.append(f"- {name}: connected")
    else:
        lines.append("- none: connected=0")

    failed_platforms = getattr(gateway, "_failed_platforms", {}) or {}
    for platform, info in sorted(
        failed_platforms.items(),
        key=lambda item: getattr(item[0], "value", str(item[0])),
    ):
        name = getattr(platform, "value", str(platform))
        paused = bool(info.get("paused")) if isinstance(info, dict) else False
        attempts = info.get("attempts", 0) if isinstance(info, dict) else 0
        state_text = "paused" if paused else "retrying"
        lines.append(f"- {name}: {state_text} (attempts={attempts})")

    return "\n".join(lines)


async def answer_queue_status(event: Any = None, gateway: Any = None, **_kwargs: Any) -> dict | None:
    """``pre_gateway_dispatch`` hook: answer ``/queue-status`` and skip normal dispatch."""

    if event is None or gateway is None or _command_name(getattr(event, "text", "")) not in QUEUE_STATUS_COMMANDS:
        return None
    source = getattr(event, "source", None)
    if source is None or not gateway._is_user_authorized_for_source(source):
        return None
    adapter = gateway._delivery_adapter_for(source)
    if adapter is None:
        return None
    report = await queue_status_report(gateway, event)
    await gateway._send_busy_reply(event, adapter, report, plain_anchor=True)
    return {"action": "skip", "reason": "queue-status answered by eternia-harness"}
