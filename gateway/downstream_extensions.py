"""Fork gateway policy and queue visibility, separate from upstream dispatch."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from gateway.platforms.base import MessageEvent
import os
import asyncio
import logging
from pathlib import Path
logger = logging.getLogger("gateway.run")
import time
from hermes_cli.config import cfg_get

def _needs_risk_assessor_warning(config: dict) -> bool:
    """Does this gateway run with manual approvals and no automated assessor?

    Startup heads-up (#30882): a gateway in manual approval mode with no
    automated risk assessor (tirith disabled AND no ``auxiliary.approval``
    model) can only gate dangerous commands / execute_code scripts via live
    in-chat approval, and those actions now fail closed rather than silently
    auto-running.

    Pulled out of ``GatewayRunner.__init__`` as a pure predicate so the
    condition is reachable from a unit test — the decision is unchanged.
    ``security.tirith_enabled`` is resolved through
    :mod:`hermes_cli.tirith_config`, the single authority for its default and
    its ``TIRITH_ENABLED`` override; reading it off the raw config with
    ``cfg_get`` (as this did) could not see the override, so a gateway whose
    operator had disabled scanning that way never got this heads-up.
    """
    from hermes_cli.tirith_config import tirith_enabled

    mode = str(
        cfg_get(config, "approvals", "mode", default="manual") or "manual"
    ).strip().lower()
    if mode != "manual":
        return False
    if tirith_enabled(config):
        return False
    return not cfg_get(config, "auxiliary", "approval", default=None)

class DownstreamGatewayMixin:
    async def _handle_queue_status_command(self, event: MessageEvent) -> str:
        """Handle /queue-status command with active-run and queue visibility."""
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
        session_entry = await self.async_session_store.get_or_create_session(source)
        session_key = session_entry.session_key
        adapter = self.adapters.get(source.platform) if source else None
        pending_slot = getattr(adapter, "_pending_messages", {}) if adapter is not None else {}
        current_pending_slot = 1 if session_key in pending_slot else 0
        overflow_depth = len((getattr(self, "_queued_events", None) or {}).get(session_key, []))
        explicit_queue_depth = self._queue_depth(session_key, adapter=adapter)

        running_agents = getattr(self, "_running_agents", {}) or {}
        running_started = getattr(self, "_running_agents_ts", {}) or {}
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
        for platform_adapter in (getattr(self, "adapters", {}) or {}).values():
            total_pending_slots += len(getattr(platform_adapter, "_pending_messages", {}) or {})
        total_overflow_depth = sum(
            len(items) for items in (getattr(self, "_queued_events", None) or {}).values()
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

        adapters = getattr(self, "adapters", {}) or {}
        if adapters:
            for platform in sorted(adapters.keys(), key=lambda p: getattr(p, "value", str(p))):
                name = getattr(platform, "value", str(platform))
                lines.append(f"- {name}: connected")
        else:
            lines.append("- none: connected=0")

        failed_platforms = getattr(self, "_failed_platforms", {}) or {}
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
