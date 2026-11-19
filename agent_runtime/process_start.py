"""When a process started, read without ``psutil``: the identity a turn reservation records.

A chat-turn reservation records its owner as ``(pid, start time)`` so a later boot can tell a
dead owner from a live one even when the pid has been reused
(:mod:`agent_runtime.chat_turn_reservations`). Desktop installs read the start time from
``psutil``. The bundled phone ships none — its ``psutil`` is the fork's stand-in
(:mod:`agent_runtime.psutil_stand_in`), whose process table is always empty — so every accept
there was refused (``RT-PHONE-TURN-RESERVATION-NEEDS-PROCESS-IDENTITY``, seen live on the Android
emulator). This module answers the same question from what each platform offers:

* a real ``psutil`` when one is importable: ``Process(pid).create_time()``, unchanged;
* Linux and Android: ``/proc/<pid>/stat``'s start ticks over ``SC_CLK_TCK`` plus ``/proc/stat``'s
  ``btime`` — psutil's own formula, so the two agree to the float. An Android app may be denied
  ``/proc/stat``; the start is then the boot-relative seconds alone, still one value per
  process incarnation and still compared only against itself on the same device;
* macOS and iOS: ``sysctl(KERN_PROC_PID)``'s ``p_starttime``, which is what psutil reads there;
* this process, when none of those answers: the wall time this module first answered for it,
  kept for the process's life, so a later process that reuses the pid reads a different value.

:func:`process_started` raises :class:`ProcessGone` only when the platform PROVES the pid has no
process, and answers ``None`` when it cannot tell — so a stale-owner check settles a receipt
only on proof, never on missing evidence.
"""

from __future__ import annotations

import os
import sys
import threading
import time

__layer__ = "models"

__all__ = ["ProcessGone", "process_started"]

#: The attribute :mod:`agent_runtime.psutil_stand_in` sets on its module (``STAND_IN_MARKER``,
#: read by value here because that module sits in a higher layer).
_PSUTIL_STAND_IN_MARKER = "__hermes_psutil_stand_in__"

_OWN_LOCK = threading.Lock()
#: pid -> the start this process answered for itself (keyed by pid so a fork re-reads).
_own: dict[int, float] = {}


class ProcessGone(Exception):
    """The platform proved no process holds this pid."""


def process_started(pid: int) -> float | None:
    """The epoch seconds ``pid`` started at; ``None`` when it cannot be read. Raises :class:`ProcessGone`."""
    pid = int(pid)
    if pid == os.getpid():
        with _OWN_LOCK:
            if pid not in _own:
                started = _read_started(pid)
                # MUTATION: return None here and test_own_identity_survives_no_platform_read reddens.
                _own[pid] = started if started is not None else time.time()
            return _own[pid]
    return _read_started(pid)


def _read_started(pid: int) -> float | None:
    psutil = _real_psutil()
    if psutil is not None:
        try:
            return psutil.Process(pid).create_time()
        except psutil.NoSuchProcess as exc:
            raise ProcessGone(pid) from exc
        except psutil.Error:
            return None
    if os.path.exists("/proc/self/stat"):
        return _proc_started(pid)
    if sys.platform in ("darwin", "ios"):
        return _sysctl_started(pid)
    return None


def _real_psutil():
    try:
        import psutil
    except ImportError:
        return None
    return None if getattr(psutil, _PSUTIL_STAND_IN_MARKER, False) else psutil


def _proc_started(pid: int) -> float | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            stat = handle.read().decode("ascii", "replace")
    except FileNotFoundError as exc:
        raise ProcessGone(pid) from exc
    except OSError:
        return None
    try:
        # Field 22 (starttime); the command name (field 2) may hold spaces and parentheses.
        ticks = int(stat.rpartition(")")[2].split()[19])
        hertz = os.sysconf("SC_CLK_TCK")
    except (IndexError, ValueError, OSError):
        return None
    return ticks / hertz + _boot_time()


def _boot_time() -> float:
    """``/proc/stat``'s ``btime``, as psutil reads it; 0.0 where it is denied (an Android app)."""
    try:
        with open("/proc/stat", "rb") as handle:
            for line in handle:
                if line.startswith(b"btime"):
                    return float(line.split()[1])
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def _sysctl_started(pid: int) -> float | None:
    """``kinfo_proc.kp_proc.p_starttime`` (Darwin): the first ``struct timeval`` of the record."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 4)(1, 14, 1, pid)  # CTL_KERN, KERN_PROC, KERN_PROC_PID
        buffer = ctypes.create_string_buffer(1024)  # sizeof(struct kinfo_proc) is 648 on 64-bit
        size = ctypes.c_size_t(ctypes.sizeof(buffer))
        if libc.sysctl(mib, 4, buffer, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
            return None
    except (OSError, AttributeError):
        return None
    if size.value == 0:  # the kernel answers an empty record for a pid with no process
        raise ProcessGone(pid)
    seconds = ctypes.c_int64.from_buffer(buffer, 0).value
    micros = ctypes.c_int32.from_buffer(buffer, 8).value
    return seconds + micros / 1_000_000
