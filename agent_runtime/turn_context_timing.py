"""Exclusive turn-context laps, logged once without consuming durable timing keys.

Only persona-chat turns are observed. The receipt contains their existing turn ID
and numeric wall times; no prompts, tools, credentials or extra persistence.
Failed builds report completed parts and an unfinished interval, never fake zeros.
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from functools import wraps
from time import perf_counter_ns
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)
TURN_CONTEXT_PARTS = (
    "runtime_restore", "mcp_refresh", "state_history_prompt", "session_row",
    "compaction", "hooks", "memory", "title", "sidecar", "persist", "return",
)
_TURN_ID = re.compile(r"[A-Za-z0-9_:.-]{1,160}\Z")


class TurnContextLaps:
    """One build's bounded wall-clock partition; observation always fails open."""

    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.values: dict[str, int] = {}
        self._elapsed_ms = 0
        self._broken = False
        self._finished = False
        try:
            self._started_ns = perf_counter_ns()
        except Exception:
            self._broken = True

    def _close(self, part: str, now: int) -> None:
        elapsed = (now - self._started_ns) // 1_000_000
        if elapsed < self._elapsed_ms:
            raise ValueError("non-monotonic context clock")
        self.values[part] = elapsed - self._elapsed_ms
        self._elapsed_ms = elapsed

    def lap(self, part: str) -> None:
        if self._broken or self._finished or part not in TURN_CONTEXT_PARTS or part in self.values:
            return
        try:
            self._close(part, perf_counter_ns())
        except Exception:
            self._broken = True

    def finish(self, completed: bool) -> None:
        if self._broken or self._finished:
            return
        self._finished = True
        try:
            now = perf_counter_ns()
            if completed:
                self._close("return", now)
            total = (now - self._started_ns) // 1_000_000
            unfinished = total - self._elapsed_ms
            if unfinished < 0:
                return
            parts = " ".join(f"{name}_ms={value}" for name, value in self.values.items())
            logger.info(
                "turn_context_receipt turn=%s status=%s total_ms=%d unfinished_ms=%d %s",
                self.turn_id, "completed" if completed else "failed", total, unfinished, parts,
            )
        except Exception:
            pass


_ACTIVE_LAPS: ContextVar[TurnContextLaps | None] = ContextVar("turn_context_laps", default=None)


def note_turn_context_part(part: str) -> None:
    """Close a fixed part of the current build, without any per-lap callback."""
    try:
        laps = _ACTIVE_LAPS.get()
        if laps is not None:
            laps.lap(part)
    except Exception:
        pass


def trace_turn_context(function):
    """Preserve the wrapped build, including its exception, return and signature."""
    @wraps(function)
    def observed(*args: Any, **kwargs: Any):
        laps = None
        try:
            agent = args[0] if args else kwargs.get("agent")
            turn_id = getattr(agent, "_persona_chat_turn_id", None)
            if isinstance(turn_id, str) and _TURN_ID.fullmatch(turn_id):
                laps = TurnContextLaps(turn_id)
        except Exception:
            pass
        try:
            token = _ACTIVE_LAPS.set(laps)
        except Exception:
            return function(*args, **kwargs)
        completed = False
        try:
            result = function(*args, **kwargs)
            completed = True
            return result
        finally:
            try:
                if laps is not None:
                    laps.finish(completed)
            except Exception:
                pass
            try:
                _ACTIVE_LAPS.reset(token)
            except Exception:
                pass

    return observed
