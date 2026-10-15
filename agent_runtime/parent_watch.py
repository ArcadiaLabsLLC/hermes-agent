"""Watch the process that owns this runtime; say when it is gone.

Bundled Hermes belongs to its Launcher (embedded-hermes D1: "crashing leaves no
bundled Hermes running"). The Launcher passes its own PID as
``harness serve --parent-pid <pid>``; serve arms :func:`start_parent_watch`
with it and drains when the owner exits — including a crash, which runs no
stop verb. Without the flag nothing is watched (full Hermes is a service that
outlives any one Launcher).

Windows opens a ``SYNCHRONIZE`` handle at arm time and waits on it, so a PID
reused after the owner died is never mistaken for the owner. POSIX polls
``os.kill(pid, 0)`` (and ``os.getppid()``, which changes the moment a direct
parent dies).
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

__layer__ = "policy"

__all__ = ["PARENT_POLL_SECONDS", "ParentWatch", "process_alive", "start_parent_watch"]

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
                 poll_seconds: float = PARENT_POLL_SECONDS) -> None:
        self.pid = pid
        self.on_gone = on_gone
        self.poll_seconds = poll_seconds
        self.stop = threading.Event()
        self.fired = threading.Event()
        self._handle = _open_sync(pid) if sys.platform == "win32" and pid > 0 else None
        self._was_child = sys.platform != "win32" and os.getppid() == pid
        self._thread = threading.Thread(target=self._run, name="harness-serve-parent-watch", daemon=True)

    def start(self) -> "ParentWatch":
        self._thread.start()
        return self

    def _gone(self) -> bool:
        if sys.platform == "win32":
            if self._handle is None:  # could not open it: gone already (or never ours)
                return True
            return _wait(self._handle, int(self.poll_seconds * 1000)) == _WAIT_OBJECT_0
        # A direct parent that died may linger as a zombie ``kill(0)`` still finds; being
        # reparented away from it is the earlier, certain signal.
        return not process_alive(self.pid) or (self._was_child and os.getppid() != self.pid)

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
                       poll_seconds: float | None = None) -> ParentWatch:
    """Arm and start a watch. ``poll_seconds`` defaults to :data:`PARENT_POLL_SECONDS`, read now."""
    return ParentWatch(pid, on_gone,
                       poll_seconds=PARENT_POLL_SECONDS if poll_seconds is None else poll_seconds).start()
