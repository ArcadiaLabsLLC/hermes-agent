"""Progress across snapshots: how long since a build's progress signal last moved.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §1 (``liveness``,
``progress_signal``, ``seconds_since_progress``), §5 (detected: CPU time across two
consecutive scans). A projection is a point in time; "stalled" is a fact about TWO points,
so the serve process keeps one small memo per source: the last value of the signal (an
agent build's ``total_output_chars``, a detected build's cumulative CPU seconds) and when it
last changed. The memo is bounded by the work it was asked about — :meth:`prune` drops every
key the latest pass did not observe — so finished work cannot accumulate in it.
"""

from __future__ import annotations

import threading
from typing import Hashable

from agent_runtime.builds.vocabulary import (
    DEFAULT_STALL_SECONDS,
    LIVENESS_LIVE,
    LIVENESS_STALLED,
)

__layer__ = "stores"

#: A row is ``stalling`` once quiet for this share of ``stall_seconds`` (running_work's word).
STALLING_FRACTION = 0.5


class ProgressTracker:
    """``key -> (last value, when it last changed)``; thread-safe, pruned per pass."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[Hashable, tuple[object, float]] = {}

    def observe(self, key: Hashable, value: object, now: float) -> float:
        """Record ``value`` for ``key``; return seconds since it last CHANGED (0 on first sight)."""

        with self._lock:
            held = self._seen.get(key)
            if held is None or held[0] != value:
                self._seen[key] = (value, now)
                return 0.0
            return max(0.0, now - held[1])

    def prune(self, keep: set[Hashable], prefix: str) -> None:
        """Drop every key of this ``prefix`` family the latest pass did not observe."""

        with self._lock:
            for key in [k for k in self._seen if isinstance(k, tuple) and k[:1] == (prefix,) and k not in keep]:
                del self._seen[key]

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


#: The serve process's one tracker (a CLI snapshot builds once and has no "since").
PROGRESS = ProgressTracker()


def liveness_for(quiet_seconds: float | None, *, stall_seconds: float = DEFAULT_STALL_SECONDS) -> tuple[str, bool]:
    """``(liveness, stalling)`` for a quiet time: stalled at the threshold, stalling at half."""

    if quiet_seconds is None:
        return LIVENESS_LIVE, False
    if quiet_seconds >= stall_seconds:
        return LIVENESS_STALLED, False
    return LIVENESS_LIVE, quiet_seconds >= stall_seconds * STALLING_FRACTION
