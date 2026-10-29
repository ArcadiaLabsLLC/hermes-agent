"""The game watch: is a handed-over game still running, and the record that survives a harness restart.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §3 decisions 13–15
(slice G1, row ``RT-GAME-PROCESS-WATCH``). A launcher that closes for a game (or suspends over one) hands
the harness a ``game`` = ``{session_id, canonical_game_id, mapping_id, title, pid, executable,
install_dir, started_at}``. The game RUNS while (a) the handed-over ``pid`` is alive with the creation
time recorded at receipt, or (b) a process of this user has ``executable`` as its executable or one
under ``install_dir`` — so a store bootstrapper that exits at once is covered by (b). Cross-platform
through ``psutil``.

* **Ended** = neither holds for :data:`END_MISSES` consecutive polls, and never inside the
  :data:`START_GRACE_SECONDS` after receipt.
* **On disk from receipt** — ``paths.launcher_supervision_games_dir()/<session_id>.json``, written
  atomically, ``last_seen_at`` refreshed every :data:`LAST_SEEN_REFRESH_SECONDS` while it runs. The
  record is the play-session handback's (§2): ``outcome`` is ``still_running`` while watched,
  ``exited`` once an end is observed (``ended_at`` set), ``lost`` when a booting harness finds the
  game gone (``ended_at`` stays ``null``, ``last_seen_at`` kept). Hermes computes no duration.
* **Resume** — :meth:`GameWatcher.resume` re-applies each still-running record's locators at boot.

The verdicts are pure (:func:`on_poll`); :class:`ProcessProbe` is the only code here that reads another
process, and tests substitute it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from .. import paths
from ..serde import safe_id, write_json_atomic

__layer__ = "lanes"

__all__ = [
    "END_MISSES",
    "GAME_RECEIPT",
    "LAST_SEEN_REFRESH_SECONDS",
    "POLL_SECONDS",
    "START_GRACE_SECONDS",
    "GameRecord",
    "GameWatcher",
    "Outcome",
    "ProcessProbe",
    "on_poll",
    "parse_game",
]

logger = logging.getLogger(__name__)

#: Decision 13: the poll cadence, the start grace, and decision 14's consecutive misses.
POLL_SECONDS = 5.0
START_GRACE_SECONDS = 60.0
END_MISSES = 2
#: Decision 15: how stale ``last_seen_at`` may grow while the game runs.
LAST_SEEN_REFRESH_SECONDS = 60.0
#: One receipt line per watch transition.
GAME_RECEIPT = "launcher_supervision event=%s session_id=%s game_id=%s outcome=%s"
_CREATE_TIME_TOLERANCE = 0.5


class Outcome:
    """The record's ``outcome`` words (§2)."""

    STILL_RUNNING = "still_running"
    EXITED = "exited"
    LOST = "lost"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True, slots=True)
class GameRecord:
    """One watched game: its locators, what the watch has seen, and the launcher to relaunch."""

    session_id: str
    game_id: str | None
    mapping_id: str | None
    title: str | None
    started_at: Any
    pid: int | None
    pid_create_time: float | None
    executable: str | None
    install_dir: str | None
    received_epoch: float
    last_seen_epoch: float
    outcome: str = Outcome.STILL_RUNNING
    ended_epoch: float | None = None
    exit_code: int | None = None
    misses: int = 0
    #: The verified beat that handed the game over: ``{pid, executable, window_visible, supervise}``.
    launcher: Mapping[str, Any] | None = None

    @property
    def active(self) -> bool:
        return self.outcome == Outcome.STILL_RUNNING

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": self.session_id,
            "game_id": self.game_id,
            "mapping_id": self.mapping_id,
            "title": self.title,
            "started_at": self.started_at,
            "pid": self.pid,
            "pid_create_time": self.pid_create_time,
            "executable": self.executable,
            "install_dir": self.install_dir,
            "received_epoch": self.received_epoch,
            "last_seen_epoch": self.last_seen_epoch,
            "last_seen_at": _iso(self.last_seen_epoch),
            "ended_epoch": self.ended_epoch,
            "ended_at": None if self.ended_epoch is None else _iso(self.ended_epoch),
            "exit_code": self.exit_code,
            "outcome": self.outcome,
            "misses": self.misses,
            "launcher": dict(self.launcher) if self.launcher is not None else None,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> GameRecord | None:
        session_id = safe_id(raw.get("session_id") or "")
        received, seen = raw.get("received_epoch"), raw.get("last_seen_epoch")
        if not session_id or not isinstance(received, (int, float)) or not isinstance(seen, (int, float)):
            return None
        pid = raw.get("pid")
        create_time = raw.get("pid_create_time")
        ended = raw.get("ended_epoch")
        launcher = raw.get("launcher")
        return cls(
            session_id=session_id, game_id=_text(raw.get("game_id")), mapping_id=_text(raw.get("mapping_id")),
            title=_text(raw.get("title")), started_at=raw.get("started_at"),
            pid=pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None,
            pid_create_time=float(create_time) if isinstance(create_time, (int, float)) else None,
            executable=_text(raw.get("executable")), install_dir=_text(raw.get("install_dir")),
            received_epoch=float(received), last_seen_epoch=float(seen),
            outcome=raw.get("outcome") if raw.get("outcome") in {Outcome.STILL_RUNNING, Outcome.EXITED,
                                                                 Outcome.LOST} else Outcome.LOST,
            ended_epoch=float(ended) if isinstance(ended, (int, float)) else None,
            exit_code=raw.get("exit_code") if isinstance(raw.get("exit_code"), int) else None,
            misses=int(raw.get("misses") or 0),
            launcher=launcher if isinstance(launcher, Mapping) else None,
        )


def parse_game(game: Mapping[str, Any], *, now: float, pid_create_time: float | None,
               launcher: Mapping[str, Any] | None) -> GameRecord | None:
    """A beat's ``game`` → a fresh record, or ``None`` when it has no session id or no locator."""

    session_id = safe_id(game.get("session_id") or "") if isinstance(game.get("session_id"), str) else ""
    pid = game.get("pid")
    pid = pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None
    executable, install_dir = _text(game.get("executable")), _text(game.get("install_dir"))
    if not session_id or (pid is None and executable is None and install_dir is None):
        return None
    return GameRecord(
        session_id=session_id, game_id=_text(game.get("canonical_game_id")),
        mapping_id=_text(game.get("mapping_id")), title=_text(game.get("title")),
        started_at=game.get("started_at"), pid=pid, pid_create_time=pid_create_time,
        executable=executable, install_dir=install_dir, received_epoch=now, last_seen_epoch=now,
        launcher=launcher,
    )


def on_poll(record: GameRecord, running: bool, now: float) -> tuple[GameRecord, bool]:
    """One poll's verdict: the updated record, and whether it must be written now. Pure."""

    if not record.active:
        return record, False
    if running:
        stale = now - record.last_seen_epoch >= LAST_SEEN_REFRESH_SECONDS
        fresh = replace(record, misses=0, last_seen_epoch=now if stale else record.last_seen_epoch)
        return fresh, stale or record.misses != 0
    if now - record.received_epoch < START_GRACE_SECONDS:
        return record, False
    misses = record.misses + 1
    if misses < END_MISSES:
        return replace(record, misses=misses), False
    return replace(record, misses=misses, outcome=Outcome.EXITED, ended_epoch=now), True


class ProcessProbe:
    """Reads other processes through ``psutil``; unreadable is "not this game"."""

    def create_time(self, pid: int) -> float | None:
        try:
            import psutil

            return float(psutil.Process(pid).create_time())
        except Exception:
            return None

    def running(self, record: GameRecord) -> bool:
        if record.pid is not None and self._pid_alive(record.pid, record.pid_create_time):
            return True
        if record.executable is None and record.install_dir is None:
            return False
        return self._any_user_process(record.executable, record.install_dir)

    def _pid_alive(self, pid: int, create_time: float | None) -> bool:
        try:
            import psutil

            process = psutil.Process(pid)
            if process.status() == psutil.STATUS_ZOMBIE:
                return False
            return create_time is None or abs(process.create_time() - create_time) <= _CREATE_TIME_TOLERANCE
        except Exception:
            return False

    def _any_user_process(self, executable: str | None, install_dir: str | None) -> bool:
        try:
            import psutil

            me = psutil.Process().username()
            processes = psutil.process_iter(["exe", "username", "status"])
        except Exception:
            return False
        folder = os.path.realpath(install_dir) if install_dir else None
        target = os.path.realpath(executable) if executable else None
        for process in processes:
            info = process.info
            exe = info.get("exe")
            if not exe or info.get("username") != me or info.get("status") == psutil.STATUS_ZOMBIE:
                continue
            real = os.path.realpath(exe)
            if target is not None and os.path.normcase(real) == os.path.normcase(target):
                return True
            if folder is not None and _inside_folder(real, folder):
                return True
        return False


def _inside_folder(path: str, folder: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath([path, folder])) == os.path.normcase(folder)
    except ValueError:  # different drives
        return False


def _record_path(session_id: str):
    return paths.launcher_supervision_games_dir() / f"{session_id}.json"


def _write_game_record(record: GameRecord) -> None:
    try:
        write_json_atomic(_record_path(record.session_id), record.to_json())
    except OSError as exc:
        logger.warning("launcher_supervision event=game_unwritten session_id=%s error=%s",
                       record.session_id, type(exc).__name__)


def load_records() -> list[GameRecord]:
    """Every game record on disk, oldest receipt first; an unreadable file is skipped and logged."""
    directory = paths.launcher_supervision_games_dir()
    records: list[GameRecord] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        try:
            record = GameRecord.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            record = None
        if record is None:
            logger.warning("launcher_supervision event=game_unreadable file=%s", path.name)
            continue
        records.append(record)
    return sorted(records, key=lambda record: record.received_epoch)


class GameWatcher:
    """Polls every active record; ``on_ended(record, still_watched)`` fires once per observed end."""

    def __init__(self, *, on_ended: Callable[[GameRecord, bool], None], probe: ProcessProbe | None = None,
                 clock: Callable[[], float] = time.time, poll_seconds: float = POLL_SECONDS) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, GameRecord] = {}
        self._on_ended = on_ended
        self._probe = probe or ProcessProbe()
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def watching(self) -> bool:
        with self._lock:
            return bool(self._records)

    def handed(self, game: Mapping[str, Any], *, launcher: Mapping[str, Any] | None) -> bool:
        """A beat's ``game``: watch it when a locator resolves now (decision 13); answer ``watching``."""

        pid = game.get("pid")
        create_time = self._probe.create_time(pid) if isinstance(pid, int) and not isinstance(pid, bool) else None
        record = parse_game(game, now=self._clock(), pid_create_time=create_time, launcher=launcher)
        if record is None:
            return False
        with self._lock:
            if record.session_id in self._records:
                return True
        if not self._probe.running(record):
            logger.info(GAME_RECEIPT, "game_unresolved", record.session_id, record.game_id or "-", "-")
            return False
        with self._lock:
            self._records[record.session_id] = record
        _write_game_record(record)
        logger.info(GAME_RECEIPT, "game_watching", record.session_id, record.game_id or "-", record.outcome)
        self._ensure_thread()
        return True

    def resume(self) -> list[GameRecord]:
        """Boot (decision 15): keep watching each record still running; close the others ``lost``.
        Returns the records now watched."""

        resumed: list[GameRecord] = []
        for record in load_records():
            if not record.active:
                continue
            if self._probe.running(record):
                with self._lock:
                    self._records[record.session_id] = record
                resumed.append(record)
                logger.info(GAME_RECEIPT, "game_resumed", record.session_id, record.game_id or "-", record.outcome)
                continue
            lost = replace(record, outcome=Outcome.LOST)
            _write_game_record(lost)
            logger.info(GAME_RECEIPT, "game_lost", lost.session_id, lost.game_id or "-", lost.outcome)
        if resumed:
            self._ensure_thread()
        return resumed

    def poll_once(self) -> None:
        with self._lock:
            records = list(self._records.values())
        for record in records:
            updated, write = on_poll(record, self._probe.running(record), self._clock())
            if write:
                _write_game_record(updated)
            with self._lock:
                if updated.active:
                    self._records[updated.session_id] = updated
                else:
                    self._records.pop(updated.session_id, None)
                still = bool(self._records)
            if not updated.active:
                logger.info(GAME_RECEIPT, "game_ended", updated.session_id, updated.game_id or "-", updated.outcome)
                self._on_ended(updated, still)

    def stop(self) -> None:
        self._stopped.set()

    def _run(self) -> None:
        while not self._stopped.wait(self._poll_seconds):
            self.poll_once()
            if not self.watching:
                with self._lock:
                    self._thread = None
                return

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None or self._stopped.is_set():
                return
            self._thread = threading.Thread(target=self._run, name="harness-game-watch", daemon=True)
        self._thread.start()
