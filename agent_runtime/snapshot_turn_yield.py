"""Snapshot builds stand aside for a live chat turn (h-chatperf, 2026-10-03).

**The defect.** ``harness serve`` runs the stream hub's core builds and the
operator's chat turns in ONE process, and a core build is 6-8 s of mostly
pure-Python work (``prompt_observability`` 3-4 s, ``agents_readiness`` 1.5-2.4 s
on the operator's Windows box). Cold turn ``1e4c06ba`` had two of them
(generations 4 and 5) running beside it end to end; warm turn ``15c73e0c`` had
generation 6 wrapped around its whole window. The only standing-aside that
existed was Stage 5's demote deferral, which covers one lane (``demote``), waits
at most 3.5 s, and can do nothing about a build that is ALREADY running when
the turn arrives. The owner's ruling: a build running during a live turn is a
bug, not a trade-off.

**The rule, one authority for every lane that builds a core.**

* Before a build LEADS, it waits while a chat turn is inside a latency-critical
  window (``turn_activity.hot_turn_windows``): its pre-admit assembly up to the
  published start row, and each provider call from dispatch to its return. Not the whole admitted turn:
  between those windows the stream lane's builds are what carry the turn's own
  start row and running-work state to the board (the serve's "a running turn
  publishes its own start" contract), so they must still happen during a turn.
* While it runs, it pauses at its yield points -- every section boundary of the
  frame build and every persona in its two per-persona walks -- whenever a hot
  window is open, and resumes when it closes.
* Both draw on ONE per-build budget, :data:`SNAPSHOT_TURN_YIELD_MAX_MS`. A turn
  can run for minutes (a tool call may take seven), and the board must not
  freeze behind it; past the budget the build finishes at full speed and says
  so on its receipt. The budget is sized to cover a cold first turn end to end.

**Why pausing is safe.** A paused build holds no lock a turn needs: at its
yield points it holds a context-local profile binding and its own SessionDB
connection, nothing else. Its watermark is read first and its pre-build input
fingerprint before that, so a pause can only make its core NEWER than its
offset -- the direction every 6-8 s build already lives with -- never older
(the MCF-Q1 direction). Callers that rode or will ride it simply wait longer.

**Exempt:** a build whose caller opted into ``accept_inflight`` -- the stream
hydrate, a client's first paint, which the demote deferral already refused to
hold behind a chat turn for the same reason.

**Cost.** One lock read per yield point; nothing at all when no turn is live.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The most one build may spend standing aside, across its pre-lead wait and
#: every in-build pause together. Cold turn 1e4c06ba ran 15.3 s end to end; this
#: covers a cold turn's provider wait without letting a minutes-long tool turn
#: freeze the board.
SNAPSHOT_TURN_YIELD_MAX_MS = 15_000

#: How often a waiting build re-reads the admitted count.
SNAPSHOT_TURN_YIELD_POLL_SECONDS = 0.025

#: One line per build that stood aside at all. Ids and timings only.
SNAPSHOT_BUILD_YIELDED_RECEIPT = (
    "snapshot_build_yielded caller=%s generation=%s waited_ms=%d pauses=%d "
    "budget_exhausted=%s bound_ms=%d pid=%d"
)


def _turns_admitted() -> int:
    """Turns inside a latency-critical window, unless this context IS a turn."""

    try:
        from .turn_activity import hot_turn_windows, inside_admitted_turn

        if inside_admitted_turn():
            return 0
        return int(hot_turn_windows())
    except Exception:  # pragma: no cover - the counter is this package's own
        return 0


class BuildYield:
    """One build's standing-aside budget and its accounting."""

    __slots__ = ("budget_s", "waited_s", "pauses", "exhausted", "_sleep", "_clock", "_admitted")

    def __init__(
        self,
        *,
        budget_ms: int = SNAPSHOT_TURN_YIELD_MAX_MS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        admitted: Callable[[], int] = _turns_admitted,
    ) -> None:
        self.budget_s = max(0.0, float(budget_ms) / 1000.0)
        self.waited_s = 0.0
        self.pauses = 0
        self.exhausted = False
        self._sleep = sleep
        self._clock = clock
        self._admitted = admitted

    @property
    def waited_ms(self) -> int:
        return int(self.waited_s * 1000)

    def stand_aside(self) -> None:
        """Wait while a turn is admitted, within what is left of the budget."""

        if self.exhausted or self._admitted() <= 0:
            return
        started = self._clock()
        deadline = started + max(0.0, self.budget_s - self.waited_s)
        self.pauses += 1
        while self._admitted() > 0:
            now = self._clock()
            if now >= deadline:
                self.exhausted = True
                break
            self._sleep(min(SNAPSHOT_TURN_YIELD_POLL_SECONDS, deadline - now))
        self.waited_s += max(0.0, self._clock() - started)


_ACTIVE: ContextVar[BuildYield | None] = ContextVar("hermes_snapshot_build_yield", default=None)


@contextmanager
def build_yield_scope(*, enabled: bool = True, **kwargs) -> Iterator[BuildYield | None]:
    """Make this thread's build honour :func:`snapshot_yield_point`."""

    if not enabled:
        yield None
        return
    state = BuildYield(**kwargs)
    token = _ACTIVE.set(state)
    try:
        yield state
    finally:
        _ACTIVE.reset(token)


def snapshot_yield_point() -> None:
    """Pause here while a chat turn is admitted, if this thread is a yielding build.

    A no-op anywhere else -- a direct ``SnapshotFrameBuild`` in a test, a
    one-shot CLI -- because only :func:`build_yield_scope` arms it.
    """

    state = _ACTIVE.get()
    if state is not None:
        state.stand_aside()


def log_build_yield(state: BuildYield | None, *, caller: str, generation: object) -> None:
    """The build's receipt, when it stood aside at all. Never raises."""

    if state is None or state.pauses == 0:
        return
    try:
        logger.info(
            SNAPSHOT_BUILD_YIELDED_RECEIPT,
            caller,
            "-" if generation is None else generation,
            state.waited_ms,
            state.pauses,
            str(state.exhausted).lower(),
            SNAPSHOT_TURN_YIELD_MAX_MS,
            os.getpid(),
        )
    except Exception:  # pragma: no cover - an instrument never fails a build
        pass


__all__ = [
    "BuildYield",
    "SNAPSHOT_TURN_YIELD_MAX_MS",
    "build_yield_scope",
    "log_build_yield",
    "snapshot_yield_point",
]
