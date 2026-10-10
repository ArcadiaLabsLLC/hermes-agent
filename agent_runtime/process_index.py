"""The hermes half of the Launcher's machine-wide process index (D1.09).

The Launcher's hygiene sweep reaps a Hermes-shaped orphan that NO store names
and spares any process some store names. It reads one directory per user
account (``EterniaLauncher/lib/core/services/hermes/runtime/hygiene/
mission_process_index_io.dart``): ``%LOCALAPPDATA%\\EterniaLauncher\\process_index``,
else ``$HOME/.eternia_launcher/process_index``; one ``<pid>.json`` per process,
``{pid, started_at_ticks?, store_root, purpose, recorded_by_pid?}`` in that key
order, compact, as ``jsonEncode(MissionProcessIndexEntry.toJson())`` writes it
(the byte format is pinned by ``tests/fixtures/process_index/``, a copy of the
Launcher's ``test/fixtures/process_index/``).

hermes children that can outlive the serve were invisible to it. This module is
the ONE writer of hermes' entries: a spawn site calls :func:`record_child`
after the child exists and :func:`forget_child` when it has ended. Identity is
pid + start, ``started_at_ticks`` in the serve register's unit
(``serve_registry.default_process_probe().start_time``: centiseconds since the
epoch on Windows/macOS, ``/proc`` clock ticks on Linux -- the Launcher's
``missionServeObservedStart``). A forget removes only an entry THIS process
recorded for that identity, never another writer's. Nothing here raises: a
spawn must never fail because a note could not be kept. The serve itself is
not written here (the Launcher knows it by its own register).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

__layer__ = "stores"

#: The Launcher's ``MissionProcessPurpose.hermesChild`` wire word.
PURPOSE_HERMES_CHILD = "hermes_child"

_LOCK = threading.Lock()
_RECORDED: dict[int, int | None] = {}


@dataclass(frozen=True, slots=True)
class Entry:
    pid: int
    store_root: str
    purpose: str
    started_at_ticks: int | None = None
    recorded_by_pid: int | None = None

    def to_json_text(self) -> str:
        """The Launcher's ``jsonEncode(toJson())`` bytes: key order, null keys omitted, compact."""
        payload: dict[str, object] = {"pid": self.pid}
        if self.started_at_ticks is not None:
            payload["started_at_ticks"] = self.started_at_ticks
        payload["store_root"] = self.store_root
        payload["purpose"] = self.purpose
        if self.recorded_by_pid is not None:
            payload["recorded_by_pid"] = self.recorded_by_pid
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def resolve_index_directory(environment: Mapping[str, str]) -> Path | None:
    """The Launcher's ``LocalMissionProcessIndex.defaultRoot`` rule, over ``environment``."""
    local_app_data = str(environment.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return Path(local_app_data) / "EterniaLauncher" / "process_index"
    home = str(environment.get("HOME") or "").strip()
    if home:
        return Path(home) / ".eternia_launcher" / "process_index"
    return None


def index_directory() -> Path | None:
    """This account's index directory, or None when neither variable resolves."""
    return resolve_index_directory(os.environ)


def process_start_ticks(pid: int) -> int | None:
    """``started_at_ticks`` for ``pid`` in the serve register's unit, or None."""
    try:
        from agent_runtime.serve_registry import default_process_probe

        value = default_process_probe().start_time(int(pid))
    except Exception:
        return None
    return None if value is None else int(value)


def _store_root_text() -> str:
    try:
        from agent_runtime import paths

        return str(paths.store_root())
    except Exception:  # unknown store reads as SOME OTHER store's: the sparing direction
        return ""


def record_child(pid: int | None, *, purpose: str = PURPOSE_HERMES_CHILD, started_at_ticks: int | None = None,
                 store_root: str | None = None) -> Entry | None:
    """Write ``<pid>.json`` atomically; the entry, or None when nothing was written. Never raises."""
    try:
        directory = index_directory()
        if directory is None or not isinstance(pid, int) or pid <= 0:  # a pid-less handle: nothing to name
            return None
        ticks = started_at_ticks if started_at_ticks is not None else process_start_ticks(pid)
        entry = Entry(
            pid=int(pid), store_root=_store_root_text() if store_root is None else store_root,
            purpose=purpose, started_at_ticks=ticks, recorded_by_pid=os.getpid(),
        )
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{entry.pid}.json"
        staged = directory / f".{entry.pid}.{os.getpid()}.{threading.get_ident()}.tmp"
        staged.write_text(entry.to_json_text(), encoding="utf-8")
        os.replace(staged, target)
        with _LOCK:
            _RECORDED[entry.pid] = entry.started_at_ticks
        return entry
    except Exception:
        return None


def forget_child(pid: int | None) -> bool:
    """Unlink the entry THIS process recorded for ``pid``, if it still names that identity. Never raises."""
    try:
        if not isinstance(pid, int):
            return False
        with _LOCK:
            if int(pid) not in _RECORDED:
                return False
            ticks = _RECORDED.pop(int(pid))
        directory = index_directory()
        if directory is None:
            return False
        target = directory / f"{int(pid)}.json"
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            current = None
        if isinstance(current, dict) and (
            current.get("recorded_by_pid") != os.getpid() or current.get("started_at_ticks") != ticks
        ):
            return False  # rewritten since: a newer process, or another writer, owns the pid now
        target.unlink()
        return True
    except Exception:
        return False


def reset_for_tests() -> None:
    with _LOCK:
        _RECORDED.clear()


__all__ = [
    "Entry", "PURPOSE_HERMES_CHILD", "forget_child", "index_directory", "process_start_ticks",
    "record_child", "reset_for_tests", "resolve_index_directory",
]
