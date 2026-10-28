"""Watch the process that owns this runtime; say when it is gone.

Bundled Hermes belongs to its Launcher. The Launcher passes its own PID as
``harness serve --parent-pid <pid>``; serve arms :func:`start_parent_watch`
with it and drains when the owner exits — including a crash, which runs no
stop verb. Without the flag nothing is watched until a launcher beats (full
Hermes is a service that outlives any one Launcher).

**Amended 2026-10-28 (the bundled-lifetime rule, owner ruling 2026-10-27):**
embedded-hermes D1's "crashing leaves no bundled Hermes running" no longer
binds the harness to ONE pid. A launcher that sends ``launcher_beat`` names
its pid on every beat, and ``agent_runtime.launcher_supervision`` re-targets
this watch to it (disarm the old :class:`ParentWatch`, arm a new one), so a
relaunched launcher is the owner from its first beat. The watch still only
says "gone"; what that MEANS — Quit, crash, closed for a game — is the
supervision table's (plan ``launcher-mutual-supervision-2026-10-27`` §3).

Windows opens a ``SYNCHRONIZE`` handle at arm time and waits on it, so a PID
reused after the owner died is never mistaken for the owner. POSIX polls
``os.kill(pid, 0)`` (and ``os.getppid()``, which changes the moment a direct
parent dies), and a watch armed with the pid's ``create_time`` also reads a
live pid whose creation time differs as gone — the pid was reused.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

__layer__ = "policy"

__all__ = ["PARENT_POLL_SECONDS", "ParentWatch", "process_alive", "process_create_time", "start_parent_watch"]

#: How often the POSIX poll looks, and how often the Windows wait re-checks ``stop``.
PARENT_POLL_SECONDS = 1.0

_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x0
_WAIT_TIMEOUT = 0x102


def process_alive(pid: int) -> bool:
    """One observation: is ``pid`` a live process now? (A zombie counts as alive on POSIX.)"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = _open_sync(pid)
        if handle is None:
            return False
        try:
            return _wait(handle, 0) == _WAIT_TIMEOUT
        finally:
            _close(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_create_time(pid: int) -> float | None:
    """The OS creation time of ``pid`` now, or ``None`` when it cannot be read (gone, denied)."""
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _kernel32():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    return kernel32


def _open_sync(pid: int):
    handle = _kernel32().OpenProcess(_SYNCHRONIZE, 0, pid)
    return handle or None


def _wait(handle, milliseconds: int) -> int:
    return int(_kernel32().WaitForSingleObject(handle, milliseconds))


def _close(handle) -> None:
    try:
        _kernel32().CloseHandle(handle)
    except Exception:  # pragma: no cover - best effort
        pass


class ParentWatch:
    """A daemon thread that calls ``on_gone`` once, when ``pid`` exits (or is already gone)."""

    def __init__(self, pid: int, on_gone: Callable[[], None], *,
                 poll_seconds: float = PARENT_POLL_SECONDS, create_time: float | None = None) -> None:
        self.pid = pid
        self.on_gone = on_gone
        self.poll_seconds = poll_seconds
        #: POSIX: the creation time the pid had when this watch was armed (``None``: not checked).
        self.create_time = create_time
        self.stop = threading.Event()
        self.fired = threading.Event()
        self._handle = _open_sync(pid) if sys.platform == "win32" and pid > 0 else None
        self._was_child = sys.platform != "win32" and os.getppid() == pid
        self._thread = threading.Thread(target=self._run, name="harness-serve-parent-watch", daemon=True)

    def start(self) -> ParentWatch:
        self._thread.start()
        return self

    def _gone(self) -> bool:
        if sys.platform == "win32":
            if self._handle is None:  # could not open it: gone already (or never ours)
                return True
            return _wait(self._handle, int(self.poll_seconds * 1000)) == _WAIT_OBJECT_0
        # A direct parent that died may linger as a zombie ``kill(0)`` still finds; being
        # reparented away from it is the earlier, certain signal.
        return (not process_alive(self.pid) or (self._was_child and os.getppid() != self.pid)
                or self._reused())

    def _reused(self) -> bool:
        if self.create_time is None:
            return False
        now = process_create_time(self.pid)
        return now is not None and abs(now - self.create_time) > 0.01

    def disarm(self) -> None:
        """Stop watching without firing (a re-target): ``on_gone`` is never called after this."""
        self.stop.set()

    def _run(self) -> None:
        try:
            while not self.stop.is_set():
                if self._gone():
                    if not self.stop.is_set():
                        self.fired.set()
                        self.on_gone()
                    return
                if sys.platform != "win32":
                    self.stop.wait(self.poll_seconds)
        finally:
            if self._handle is not None:
                _close(self._handle)
                self._handle = None


def start_parent_watch(pid: int, on_gone: Callable[[], None], *,
                       poll_seconds: float | None = None, create_time: float | None = None) -> ParentWatch:
    """Arm and start a watch. ``poll_seconds`` defaults to :data:`PARENT_POLL_SECONDS`, read now."""
    return ParentWatch(pid, on_gone, create_time=create_time,
                       poll_seconds=PARENT_POLL_SECONDS if poll_seconds is None else poll_seconds).start()
