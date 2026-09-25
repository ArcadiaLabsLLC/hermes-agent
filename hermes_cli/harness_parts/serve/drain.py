"""Drain bookkeeping: the ``_DrainState`` record and the deadline policy.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from hermes_cli.harness_parts.serve.constants import (
    _DRAIN_DEADLINE_FLOOR_SECONDS,
    _DRAIN_DEADLINE_MAX_SECONDS,
)

__layer__ = "lanes"

__all__ = [
    "_DrainState",
    "_drain_deadline_seconds",
]


class _DrainState:
    """One drain in progress, and everything its terminal frame must account for.

    The counters are the point. A `drain_complete` that only said "done" would
    be a frame with the right NAME and no evidence — it could not distinguish a
    drain that let three turns land from one that refused them all, which is
    the difference between a safe restart and lost work.
    """

    __slots__ = (
        "started_monotonic",
        "deadline_seconds",
        "refused",
        "completed",
        "deadline_holds",
        "lock",
    )

    def __init__(self, deadline_seconds: float):
        self.started_monotonic = time.monotonic()
        self.deadline_seconds = deadline_seconds
        self.refused = 0
        self.completed = 0
        #: How many times the deadline expired and was NOT allowed to end the
        #: process because a chat turn was still in flight. Counted because
        #: "this restart is taking a while" and "this restart has been held
        #: open by recording safety four times" are different operator facts.
        self.deadline_holds = 0
        self.lock = threading.Lock()

    def note_refused(self) -> int:
        with self.lock:
            self.refused += 1
            return self.refused

    def note_completed(self) -> None:
        with self.lock:
            self.completed += 1

    def note_deadline_held(self) -> int:
        with self.lock:
            self.deadline_holds += 1
            return self.deadline_holds

    def counters(self) -> dict[str, Any]:
        with self.lock:
            return {
                "requests_refused": self.refused,
                "requests_completed": self.completed,
                "deadline_holds": self.deadline_holds,
            }

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)


def _drain_deadline_seconds(
    raw: Any, default: float, *, minimum: float = _DRAIN_DEADLINE_FLOOR_SECONDS
) -> float:
    """The EFFECTIVE deadline: the client's ask, floored by the server's.

    A client may lengthen a drain (up to the hard ceiling) and may not shorten
    it below the floor the caller passes for its TRANSPORT: the sanity floor on
    stdio (unchanged — that asker owns the process), the socket minimum on the
    socket lane. The floor is a parameter rather than a constant read in here
    precisely so the two lanes can differ and so the loop's own tests can run a
    drain in milliseconds; it is a SERVER-side parameter either way, and no
    field a client sends can lower it.
    """

    floor = max(0.0, float(minimum))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return max(floor, float(default))
    return max(floor, min(float(raw), _DRAIN_DEADLINE_MAX_SECONDS))
