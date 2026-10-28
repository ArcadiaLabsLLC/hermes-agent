"""The wiring: one parent watch re-targeted per beat, the beat clock, and the receipts.

The serve owns one :class:`LauncherWatchdog` (``hermes_cli/harness_parts/serve/launcher_supervision.py``)
and feeds it beats and connection closes; the watchdog feeds :mod:`.policy` those plus pid exits and
clock ticks, and carries out each decision through the serve's :class:`SupervisionEffects`. Every
decision logs ONE ``launcher_supervision`` receipt line (decision 2 of the plan).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from .. import parent_watch
from .contract import LauncherBeat
from .policy import TICK_SECONDS, Decision, SupervisionState, on_beat, on_connection_dropped, on_pid_gone, on_tick

__layer__ = "lanes"

__all__ = ["RECEIPT", "LauncherWatchdog", "SupervisionEffects"]

logger = logging.getLogger(__name__)

#: The receipt line, one per decision.
RECEIPT = "launcher_supervision event=%s pid=%s launcher_state=%s drain=%s note_end=%s"


class SupervisionEffects(Protocol):
    def note_end(self, word: str) -> None: ...

    def drain(self, word: str, pid: int | None) -> None: ...


class LauncherWatchdog:
    """Owns the supervision state; every mutation goes through :mod:`.policy` under one lock."""

    def __init__(self, *, parent_pid: int | None, effects: SupervisionEffects,
                 tick_seconds: float = TICK_SECONDS, clock: Callable[[], float] = time.time,
                 poll_seconds: float | None = None) -> None:
        self._lock = threading.Lock()
        self._state = SupervisionState(bound=parent_pid is not None, watched_pid=parent_pid)
        self._effects = effects
        self._tick_seconds = tick_seconds
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._watch: Any = None
        self._beat_connection: Any = None
        self._stopped = threading.Event()
        self._ticker: threading.Thread | None = None

    @property
    def state(self) -> SupervisionState:
        with self._lock:
            return self._state

    def start(self) -> LauncherWatchdog:
        """Arm the initial watch on ``--parent-pid`` (nothing without it until a beat names a pid)."""
        if self._state.watched_pid is not None:
            self._arm(self._state.watched_pid)
        return self

    def beat(self, beat: LauncherBeat, *, connection: Any = None) -> bool:
        """Feed one parsed beat; answers ``watching`` (W1 watches no game, so always False)."""
        with self._lock:
            self._state, decisions = on_beat(self._state, beat)
            self._beat_connection = connection
        self._apply(decisions)
        self._ensure_ticker()
        return False

    def connection_closed(self, connection: Any) -> None:
        """The connection that last beat closed; any other connection's close is not ours."""
        with self._lock:
            if connection is None or connection is not self._beat_connection:
                return
            self._beat_connection = None
            self._state, decisions = on_connection_dropped(self._state)
        self._apply(decisions)

    def stop(self) -> None:
        self._stopped.set()
        watch = self._watch
        if watch is not None:
            watch.disarm()

    def _pid_gone(self, pid: int) -> None:
        with self._lock:
            self._state, decisions = on_pid_gone(self._state, pid)
        self._apply(decisions)

    def _tick(self) -> None:
        while not self._stopped.wait(self._tick_seconds):
            with self._lock:
                self._state, decisions = on_tick(self._state, self._clock())
            self._apply(decisions)

    def _ensure_ticker(self) -> None:
        with self._lock:
            if self._ticker is not None or self._stopped.is_set():
                return
            self._ticker = threading.Thread(target=self._tick, name="harness-launcher-beat-clock", daemon=True)
        self._ticker.start()

    def _arm(self, pid: int) -> None:
        old, self._watch = self._watch, parent_watch.start_parent_watch(
            pid, lambda: self._pid_gone(pid), poll_seconds=self._poll_seconds,
            create_time=parent_watch.process_create_time(pid))
        if old is not None:
            old.disarm()

    def _apply(self, decisions: list[Decision]) -> None:
        for decision in decisions:
            beat = self.state.last_beat
            logger.info(RECEIPT, decision.record.value, beat.pid if beat else self.state.watched_pid,
                        beat.state.value if beat else "-", decision.drain or "-", decision.note_end or "-")
            if decision.retarget_pid is not None and not self._stopped.is_set():
                self._arm(decision.retarget_pid)
            if decision.note_end is not None:
                self._effects.note_end(decision.note_end)
            if decision.drain is not None:
                self.stop()
                self._effects.drain(decision.drain, beat.pid if beat else None)
