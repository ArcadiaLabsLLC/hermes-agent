"""The ``context_build_receipt``: where a chat turn's ``context_built`` span goes, part by part (r-turn, 2026-10-18).

``context_native_history_ms`` and the builder's own sub-stamps left ~7-9 ms of a warm turn's
``context_built`` unattributed (registry lookup, journal abandoned-id read, the revision hash, the
relay marker, the session model config, builder glue). Each part is an exclusive lap in
microseconds, because no single part is expected above the 5 ms bar. A log receipt only: no
durable timing key, no wire field. Observation fails open and never raises into the turn.
"""
from __future__ import annotations

import logging
from time import perf_counter_ns

__layer__ = "policy"

logger = logging.getLogger(__name__)

CONTEXT_BUILD_RECEIPT = "context_build_receipt"
CONTEXT_BUILD_PARTS = (
    "registry", "history_read", "abandoned_filter", "revision", "relay_marker", "model_config", "builder",
)


class ContextBuildLaps:
    """Exclusive wall-clock laps over one ``_build_context``; unknown or repeated parts are ignored."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self._started_ns = self._last_ns = perf_counter_ns()

    def lap(self, part: str) -> None:
        try:
            if part not in CONTEXT_BUILD_PARTS or part in self.values:
                return
            now = perf_counter_ns()
            self.values[part] = max(0, (now - self._last_ns) // 1000)
            self._last_ns = now
        except Exception:
            pass

    def emit(self, turn_id: object, *, source: str) -> None:
        """One INFO line; parts never reached are absent, never zero."""
        try:
            total_us = max(0, (perf_counter_ns() - self._started_ns) // 1000)
            parts = " ".join(f"{name}_us={self.values[name]}" for name in CONTEXT_BUILD_PARTS if name in self.values)
            logger.info("%s turn=%s source=%s total_us=%d %s", CONTEXT_BUILD_RECEIPT,
                        str(turn_id or "-")[:160], source, total_us, parts)
        except Exception:
            pass


__all__ = ["CONTEXT_BUILD_PARTS", "CONTEXT_BUILD_RECEIPT", "ContextBuildLaps"]
