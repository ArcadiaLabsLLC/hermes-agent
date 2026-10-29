"""The wiring: one parent watch re-targeted per beat, the beat clock, and the receipts.

The serve owns one :class:`LauncherWatchdog` (``hermes_cli/harness_parts/serve/launcher_supervision.py``)
and feeds it beats and connection closes; the watchdog feeds :mod:`.policy` those plus pid exits and
clock ticks, and carries out each decision through the serve's :class:`SupervisionEffects` and the
:class:`~.relaunch.Relauncher`. Every decision logs ONE ``launcher_supervision`` receipt line
(decision 2 of the plan), and so does every relaunch, skipped relaunch and refused identity.

W2 adds three things here: a supervised beat is fed to the table only once its ``executable`` is the
file its pid runs (decision 8 — otherwise ``launcher_identity_mismatch``, answered and ignored); a
relaunch fires on a timer after its backoff and only while the serve is not ending (decision 9 —
:meth:`SupervisionEffects.may_relaunch`); and the budget is persisted to
``paths.launcher_supervision_state_path()`` so a harness restart does not reset it (decision 10).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from .. import parent_watch, paths
from ..serde import write_json_atomic
from .contract import LauncherBeat
from .policy import (TICK_SECONDS, Decision, RelaunchReason, SupervisionState, on_beat, on_connection_dropped,
                     on_pid_gone, on_tick)
from .relaunch import Relauncher, relaunch_argv

__layer__ = "lanes"

__all__ = ["RECEIPT", "LauncherWatchdog", "SupervisionEffects"]

logger = logging.getLogger(__name__)

#: The receipt line, one per decision.
RECEIPT = "launcher_supervision event=%s pid=%s launcher_state=%s drain=%s note_end=%s"
#: One per relaunch carried out or skipped, and per beat refused for its identity.
RELAUNCH_RECEIPT = "launcher_supervision event=%s reason=%s pid=%s new_pid=%s delay=%s"


class SupervisionEffects(Protocol):
    def note_end(self, word: str) -> None: ...

    def drain(self, word: str, pid: int | None) -> None: ...

    def may_relaunch(self) -> bool:
        """``False`` once anything is ending this runtime (a drain, a stop, the OS logging off)."""
        ...


def _load_relaunches() -> tuple[float, ...]:
    try:
        raw = json.loads(paths.launcher_supervision_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    values = raw.get("relaunches") if isinstance(raw, dict) else None
    return tuple(float(at) for at in values if isinstance(at, (int, float)) and not isinstance(at, bool)) \
        if isinstance(values, list) else ()


class LauncherWatchdog:
    """Owns the supervision state; every mutation goes through :mod:`.policy` under one lock."""

    def __init__(self, *, parent_pid: int | None, effects: SupervisionEffects,
                 tick_seconds: float = TICK_SECONDS, clock: Callable[[], float] = time.time,
                 poll_seconds: float | None = None, relauncher: Relauncher | None = None) -> None:
        self._lock = threading.Lock()
        self._state = SupervisionState(bound=parent_pid is not None, watched_pid=parent_pid,
                                       relaunches=_load_relaunches())
        self._effects = effects
        self._relauncher = relauncher or Relauncher()
        self._create_times: dict[int, float | None] = {}
        self._verified: tuple[int, str] | None = None
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
        """Feed one parsed beat; answers ``watching`` (no game watch before G1, so always False)."""
        if beat.supervise and (beat.pid, beat.executable) != self._verified:
            if not self._relauncher.same_executable(beat.pid, beat.executable):
                logger.warning(RELAUNCH_RECEIPT, "launcher_identity_mismatch", "-", beat.pid, "-", "-")
                return False
            self._verified = (beat.pid, beat.executable)
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
            self._state, decisions = on_pid_gone(self._state, pid, now=self._clock())
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
        created = self._create_times[pid] = parent_watch.process_create_time(pid)
        old, self._watch = self._watch, parent_watch.start_parent_watch(
            pid, lambda: self._pid_gone(pid), poll_seconds=self._poll_seconds, create_time=created)
        if old is not None:
            old.disarm()

    def _persist(self) -> None:
        state = self.state
        beat = state.last_beat
        try:
            write_json_atomic(paths.launcher_supervision_state_path(), {
                "version": 1,
                "relaunches": list(state.relaunches),
                "watched_pid": state.watched_pid,
                "last_beat": None if beat is None else {
                    "pid": beat.pid, "state": beat.state.value, "executable": beat.executable,
                    "window_visible": beat.window_visible, "supervise": beat.supervise},
            })
        except OSError as exc:
            logger.warning("launcher_supervision event=state_unwritten error=%s", type(exc).__name__)

    def _schedule_relaunch(self, reason: RelaunchReason, delay: float, beat: LauncherBeat | None) -> None:
        if beat is None:
            return
        timer = threading.Timer(delay, self._relaunch, args=(reason, beat))
        timer.name, timer.daemon = "harness-launcher-relaunch", True
        timer.start()

    def _relaunch(self, reason: RelaunchReason, beat: LauncherBeat) -> None:
        """The backoff elapsed: spawn the launcher the last beat named, unless this runtime is ending."""
        if self._stopped.is_set() or not self._effects.may_relaunch():
            logger.info(RELAUNCH_RECEIPT, "relaunch_skipped", reason.value, beat.pid, "-", "-")
            return
        argv = relaunch_argv(beat.executable, reason.value, start_hidden=not beat.window_visible)
        new_pid = self._relauncher.spawn(argv)
        logger.info(RELAUNCH_RECEIPT, "relaunched" if new_pid else "relaunch_unspawned", reason.value,
                    beat.pid, new_pid or "-", "-")

    def _apply(self, decisions: list[Decision]) -> None:
        if any(decision.relaunch is not None or decision.drain is not None for decision in decisions):
            self._persist()
        for decision in decisions:
            beat = self.state.last_beat
            logger.info(RECEIPT, decision.record.value, beat.pid if beat else self.state.watched_pid,
                        beat.state.value if beat else "-", decision.drain or "-", decision.note_end or "-")
            if decision.kill_pid is not None:
                killed = self._relauncher.kill(decision.kill_pid, self._create_times.get(decision.kill_pid))
                logger.info(RELAUNCH_RECEIPT, "killed" if killed else "kill_refused", "-", decision.kill_pid,
                            "-", "-")
            if decision.relaunch is not None:
                logger.info(RELAUNCH_RECEIPT, "relaunch_scheduled", decision.relaunch.value,
                            beat.pid if beat else "-", "-", decision.delay)
                self._schedule_relaunch(decision.relaunch, decision.delay, beat)
            if decision.retarget_pid is not None and not self._stopped.is_set():
                self._arm(decision.retarget_pid)
            if decision.note_end is not None:
                self._effects.note_end(decision.note_end)
            if decision.drain is not None:
                self.stop()
                self._effects.drain(decision.drain, beat.pid if beat else None)
