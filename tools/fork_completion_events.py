"""Fork-owned ``completion_queue`` event types: one table row per type, read by every upstream drain.

``process_registry.completion_queue`` is upstream's; the fork puts its own event types on it (an MCP
server's job wake, ``tools/mcp_job_wake.py``; a promoted long tool call's finish,
``tools/long_tool_calls.py``). Each upstream consumer that must treat a fork type
differently from a process completion reads THIS table through one additive seam, so a new fork
type is a new row here and never another upstream hunk:

* ``gateway/run.py::_drain_gateway_watch_events`` keeps a registered type for injection (no
  per-process watcher owns it) — :func:`is_fork_completion_event`;
* ``gateway/run.py::_format_gateway_process_notification`` and
  ``tools/process_registry_notifications.py::format_process_notification`` render it —
  :func:`format_fork_completion_event`;
* ``tools/async_delegation.py::complete_event_delivery`` — the acknowledgement every CLI / TUI /
  quiet-mode drain already calls after delivering — settles it — :func:`settle_fork_completion_event`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from tools import long_tool_calls, mcp_job_wake

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForkCompletionEvent:
    """How the upstream drains treat one fork event type."""

    #: The ``[IMPORTANT: ...]`` text a drain injects for the event.
    format: Callable[[Mapping[str, Any]], str]
    #: The delivering drain is done with the event: retire whatever the fork holds for it.
    settle: Callable[[Mapping[str, Any]], bool]


FORK_COMPLETION_EVENTS: Mapping[str, ForkCompletionEvent] = {
    mcp_job_wake.EVENT_TYPE: ForkCompletionEvent(
        format=mcp_job_wake.format_job_finished, settle=mcp_job_wake.note_wake_settled,
    ),
    long_tool_calls.EVENT_TYPE: ForkCompletionEvent(
        format=long_tool_calls.format_tool_call_finished, settle=long_tool_calls.note_wake_settled,
    ),
}


def _row(evt: Any) -> Optional[ForkCompletionEvent]:
    if not isinstance(evt, Mapping):
        return None
    return FORK_COMPLETION_EVENTS.get(str(evt.get("type") or ""))


def is_fork_completion_event(evt_type: Any) -> bool:
    """A fork event type: kept by the gateway's drain for injection, never left to a process watcher."""
    return str(evt_type or "") in FORK_COMPLETION_EVENTS


def format_fork_completion_event(evt: Any) -> Optional[str]:
    """The injected text for a fork event; ``None`` for any other event (the upstream formatter's)."""
    row = _row(evt)
    return None if row is None else row.format(evt)


def settle_fork_completion_event(evt: Any) -> bool:
    """Retire a delivered fork event's state. Never raises; ``False`` for any other event."""
    row = _row(evt)
    if row is None:
        return False
    try:
        return bool(row.settle(evt))
    except Exception:
        logger.debug("fork completion settle failed for %r", evt.get("type"), exc_info=True)
        return False
