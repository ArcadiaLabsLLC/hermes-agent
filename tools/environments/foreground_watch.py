"""Read-only observation of the foreground commands in flight in THIS process.

A foreground ``terminal`` call blocks its tool thread inside
``BaseEnvironment.execute`` until the command exits or its deadline fires. The
only things that knew it was running were that wait loop and the OS: no
operator surface could say which command, which pid, how long, how close to
its timeout, or whether it had printed anything lately — so a silent build
looked identical to a hung one (hermes ``runtime-queue.md`` RW2/RW3, owner
screenshot 2026-10-01).

``BaseEnvironment.execute`` publishes each spawned foreground command here and
retracts it when the wait ends; readers take a :class:`ForegroundCommand`
snapshot. Nothing here signals, waits on or mutates a process — cancelling is
the owning turn's interrupt seam, never this module.

``seconds_since_output`` is OBSERVED, not reported: the output collector keeps
no arrival stamps, so each :func:`snapshot` compares the collector's running
character count with the count it saw last and moves the stamp when it grew.
Its resolution is therefore the reader's own sampling interval, and the value
is a lower bound on silence only to within that interval.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

__all__ = ["ForegroundCommand", "publish", "retract", "snapshot"]

#: Upper bound on the tail a snapshot carries. Readers bound again for their
#: own wire; this only stops a snapshot from copying a 50 KB capture window.
_TAIL_CHARS = 4096


@dataclass(frozen=True)
class ForegroundCommand:
    """One in-flight foreground command, as of the snapshot that produced it."""

    key: int
    pid: int | None
    command: str
    started_at: float
    timeout_seconds: float | None
    owner_tid: int | None
    elapsed_seconds: float
    output_chars: int
    seconds_since_output: float
    tail: str


class _Entry:
    __slots__ = ("pid", "command", "started_at", "started_mono", "timeout", "owner_tid", "output",
                 "seen_chars", "last_output_mono")

    def __init__(self, *, pid: Any, command: str, timeout: Any, owner_tid: Any, output: Any) -> None:
        now = time.monotonic()
        self.pid = pid if isinstance(pid, int) else None
        self.command = str(command or "")
        self.started_at = time.time()
        self.started_mono = now
        try:
            self.timeout = float(timeout) if timeout is not None else None
        except (TypeError, ValueError):
            self.timeout = None
        self.owner_tid = owner_tid if isinstance(owner_tid, int) else None
        self.output = output
        self.seen_chars = 0
        self.last_output_mono = now


_lock = threading.Lock()
_entries: dict[int, _Entry] = {}


def publish(key: int, *, pid: Any, command: str, timeout: Any, owner_tid: Any, output: Any) -> None:
    """Record a spawned foreground command. Never raises into the command's own path."""

    try:
        entry = _Entry(pid=pid, command=command, timeout=timeout, owner_tid=owner_tid, output=output)
    except Exception:
        return
    with _lock:
        _entries[key] = entry


def retract(key: int) -> None:
    with _lock:
        _entries.pop(key, None)


def _chars(output: Any) -> int:
    try:
        return int(output.total_chars)
    except Exception:
        return 0


def _tail(output: Any) -> str:
    try:
        rendered = output.render()
    except Exception:
        return ""
    return rendered[-_TAIL_CHARS:] if isinstance(rendered, str) else ""


def snapshot(*, owner_tid: int | None = None) -> list[ForegroundCommand]:
    """Every in-flight foreground command (or the one ``owner_tid`` is waiting on).

    Oldest first. Reading advances each entry's observed-output stamp — the only
    write this module makes, and to its own bookkeeping.
    """

    now = time.monotonic()
    with _lock:
        items = [
            (key, entry) for key, entry in _entries.items()
            if owner_tid is None or entry.owner_tid == owner_tid
        ]
        observed = []
        for key, entry in items:
            chars = _chars(entry.output)
            if chars != entry.seen_chars:
                entry.seen_chars = chars
                entry.last_output_mono = now
            observed.append((key, entry, chars))
    commands = [
        ForegroundCommand(
            key=key,
            pid=entry.pid,
            command=entry.command,
            started_at=entry.started_at,
            timeout_seconds=entry.timeout,
            owner_tid=entry.owner_tid,
            elapsed_seconds=round(max(0.0, now - entry.started_mono), 1),
            output_chars=chars,
            seconds_since_output=round(max(0.0, now - entry.last_output_mono), 1),
            tail=_tail(entry.output),
        )
        for key, entry, chars in observed
    ]
    return sorted(commands, key=lambda item: item.started_at)
