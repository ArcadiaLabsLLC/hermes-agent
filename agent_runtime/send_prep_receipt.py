"""The ``send_prep_receipt``: where a chat turn's anchor -> ``request_sent`` time goes (h-prereq-window, 2026-10-06).

**The question this answers.** Live 2026-10-06 17:05 the warm turns of one chat took
0.55-1.0 s from the handler's anchor to the request leaving hermes; at 14:34 the same span read
0.38-0.71 s, and nothing on ``agent.log`` could say which phase grew (the turn record carries the
marks, the log did not). One line per turn, written the instant ``request_sent`` is marked, splits
the window into the turn's own phase marks (:data:`agent_runtime.mission_chat_phases.PHASE_ORDER`):
each ``<mark>_ms`` is that mark minus the previous mark the turn took, so a phase the turn skipped
(``tls_done`` on a pooled connection) folds into the next one rather than reading as ``0``.

Three fields say whether the window was this turn's work or a wait on something else:

* ``cpu_ms`` -- process CPU seconds spent over the window (every thread). Far under ``total_ms``
  means the turn waited (I/O, a lock, a starved machine); near or over it means the process was
  busy, its own work or a sibling thread's.
* ``title_threads`` -- live ``auto-title`` upgrade threads at ``request_sent`` (the turn-start
  title model call competing with the window).
* ``largest`` -- the phase with the most milliseconds.

``turn`` is the client message id, the key ``chat_turn_accept_to_anchor`` and the turn record
carry. Observability is this log line, never a parity-envelope key. Fail-open: one ``INFO`` line
per turn, built from marks already taken.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

__layer__ = "policy"

logger = logging.getLogger(__name__)

SEND_PREP_RECEIPT = "send_prep_receipt"
#: The ``threading.Thread`` name ``agent.title_generator.maybe_auto_title`` gives its upgrade.
TITLE_THREAD_NAME = "auto-title"
_SENT = "request_sent"


def prep_segments(marks: dict[str, int], order: Iterable[str]) -> dict[str, int]:
    """Mark name -> ms since the previous mark taken, for every mark up to ``request_sent``."""

    segments: dict[str, int] = {}
    previous = 0
    for name in order:
        value = marks.get(name)
        if name == "request_received" or not isinstance(value, int):
            continue
        segments[name] = max(0, value - previous)
        previous = max(previous, value)
        if name == _SENT:
            break
    return segments


def title_threads_alive() -> int:
    return sum(1 for t in threading.enumerate() if t.name.startswith(TITLE_THREAD_NAME) and t.is_alive())


def send_prep_line(
    marks: dict[str, int], order: Iterable[str], *, turn: Any, anchored_at: Any, cpu_ms: float | None,
    title_threads: int | None,
) -> str:
    def fmt(value: Any) -> str:
        return "na" if value is None else str(value)

    segments = prep_segments(marks, order)
    largest = max(segments, key=segments.get) if segments else None
    parts = [
        SEND_PREP_RECEIPT, f"turn={turn or 'na'}", f"anchored_at={anchored_at or 'na'}",
        f"total_ms={fmt(marks.get(_SENT))}", f"cpu_ms={fmt(None if cpu_ms is None else int(cpu_ms))}",
        f"title_threads={fmt(title_threads)}", f"largest={largest or 'na'}",
    ]
    parts += [f"{name}_ms={value}" for name, value in segments.items()]
    return " ".join(parts)


def emit_send_prep_receipt(
    marks: dict[str, int], order: Iterable[str], *, turn: Any, anchored_at: Any, cpu_ms: float | None,
) -> str | None:
    """Log the turn's line. Never raises: an instrument is never why a request is late or lost."""

    try:
        text = send_prep_line(marks, order, turn=turn, anchored_at=anchored_at, cpu_ms=cpu_ms,
                              title_threads=title_threads_alive())
    except Exception:
        logger.debug("send_prep_receipt not built", exc_info=True)
        return None
    logger.info("%s", text)
    return text


__all__ = ["SEND_PREP_RECEIPT", "TITLE_THREAD_NAME", "emit_send_prep_receipt", "prep_segments", "send_prep_line"]
