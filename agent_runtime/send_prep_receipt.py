"""The ``send_prep_receipt``: where a chat turn's anchor -> ``request_sent`` time goes (h-prereq-window, 2026-10-06).

**The question this answers.** Live 2026-10-06 17:05 the warm turns of one chat took
0.55-1.0 s from the handler's anchor to the request leaving hermes; at 14:34 the same span read
0.38-0.71 s, and nothing on ``agent.log`` could say which phase grew (the turn record carries the
marks, the log did not). One line per turn, written the instant ``request_sent`` is marked, splits
the window into the turn's own phase marks (:data:`agent_runtime.mission_chat_phases.PHASE_ORDER`):
each ``<mark>_ms`` is that mark minus the previous mark the turn took, so a phase the turn skipped
(``tls_done`` on a pooled connection) folds into the next one rather than reading as ``0``.

Three fields say whether the window was this turn's work or a wait on something else:

* ``cpu_ms`` -- process CPU seconds spent over the window (every thread). Far under ``total_ms``
  means the turn waited (I/O, a lock, a starved machine); near or over it means the process was
  busy, its own work or a sibling thread's.
* ``title_threads`` -- live ``auto-title`` upgrade threads at ``request_sent`` (the turn-start
  title model call competing with the window).
* ``largest`` -- the phase with the most milliseconds.

h-prep-contention (2026-10-06): ``cpu_ms`` over ``total_ms`` (live 1828 over 1712) says a
sibling thread was busy, never WHICH. Three fields name it, from per-thread CPU clocks read at
the anchor and at ``request_sent`` (:class:`CpuAnchor`; a few microseconds a thread -- psutil's
``threads()`` walks every thread on the machine, 70-90 ms on Windows, and is not used):

* ``own_cpu_ms`` -- the thread(s) that took the anchor and marked ``request_sent``: the turn's own work;
* ``top_threads`` -- up to :data:`TOP_THREADS` OTHER threads alive at both ends, ``name:ms``, by
  CPU descending (``none`` when no other thread spent :data:`MIN_THREAD_MS`);
* ``unattributed_ms`` -- ``cpu_ms`` minus every thread read: threads that started or ended
  inside the window (a keep-warm ``Timer``) and threads Python did not start.

``turn`` is the client message id, the key ``chat_turn_accept_to_anchor`` and the turn record
carry. Observability is this log line, never a parity-envelope key. Fail-open: one ``INFO`` line
per turn, built from marks already taken.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Iterable

__layer__ = "policy"

logger = logging.getLogger(__name__)

SEND_PREP_RECEIPT = "send_prep_receipt"
#: The ``threading.Thread`` name ``agent.title_generator.maybe_auto_title`` gives its upgrade.
TITLE_THREAD_NAME = "auto-title"
_SENT = "request_sent"
#: How many competing threads ``top_threads`` names, and the floor a thread must reach.
TOP_THREADS = 3
MIN_THREAD_MS = 1.0


def _windows_thread_seconds() -> Any:
    import ctypes
    from ctypes import wintypes

    # PyDLL: the calls keep the GIL. A WinDLL call releases it, and with a busy sibling each
    # re-acquire waited out the switch interval (a 2-thread read took 30 ms beside a spinner).
    kernel32 = ctypes.PyDLL("kernel32")
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetThreadTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    def seconds(thread: threading.Thread) -> float | None:
        handle = kernel32.OpenThread(0x0800, False, int(thread.native_id or 0))  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            times = (wintypes.FILETIME * 4)()
            if not kernel32.GetThreadTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            kernel, user = times[2], times[3]
            return ((kernel.dwHighDateTime << 32 | kernel.dwLowDateTime)
                    + (user.dwHighDateTime << 32 | user.dwLowDateTime)) / 1e7
        finally:
            kernel32.CloseHandle(handle)

    return seconds


def _posix_thread_seconds(thread: threading.Thread) -> float | None:
    return time.clock_gettime(time.pthread_getcpuclockid(int(thread.ident or 0)))


def _thread_seconds_reader() -> Any:
    try:
        if sys.platform == "win32":
            return _windows_thread_seconds()
        if hasattr(time, "pthread_getcpuclockid"):
            return _posix_thread_seconds
    except Exception:
        logger.debug("per-thread CPU clocks unavailable", exc_info=True)
    return None


_THREAD_SECONDS = _thread_seconds_reader()


def thread_cpu_seconds() -> dict[int, tuple[str, float]] | None:
    """Every live Python thread's CPU seconds, ``ident -> (name, seconds)``; None without clocks."""

    if _THREAD_SECONDS is None:
        return None
    seen: dict[int, tuple[str, float]] = {}
    for thread in threading.enumerate():
        try:
            value = _THREAD_SECONDS(thread)
        except Exception:
            value = None
        if value is not None and thread.ident is not None:
            seen[thread.ident] = (thread.name, float(value))
    return seen


class CpuAnchor:
    """The near end of the receipt's CPU fields: process CPU, per-thread CPU, the anchoring thread."""

    __slots__ = ("process", "threads", "owner")

    def __init__(self) -> None:
        self.process = time.process_time()
        self.owner = threading.get_ident()
        try:
            self.threads = thread_cpu_seconds()
        except Exception:
            self.threads = None


def contention_fields(anchor: CpuAnchor | None, cpu_ms: float | None) -> dict[str, Any]:
    """``own_cpu_ms`` / ``top_threads`` / ``unattributed_ms`` for the window since ``anchor``."""

    after = thread_cpu_seconds() if anchor is not None and anchor.threads is not None else None
    if anchor is None or after is None:
        return {"own_cpu_ms": None, "top_threads": None, "unattributed_ms": None}
    own_idents = {anchor.owner, threading.get_ident()}
    own = 0.0
    others: list[tuple[float, str]] = []
    for ident, (name, seconds) in after.items():
        before = anchor.threads.get(ident)
        if before is None:
            continue
        spent = max(0.0, (seconds - before[1]) * 1000.0)
        if ident in own_idents:
            own += spent
        else:
            others.append((spent, name))
    others.sort(key=lambda item: -item[0])
    named = [f"{_thread_token(name)}:{int(ms)}" for ms, name in others[:TOP_THREADS] if ms >= MIN_THREAD_MS]
    read = own + sum(ms for ms, _name in others)
    return {
        "own_cpu_ms": int(own),
        "top_threads": ",".join(named) or "none",
        "unattributed_ms": None if cpu_ms is None else max(0, int(cpu_ms - read)),
    }


def _thread_token(name: str) -> str:
    return "".join("_" if ch.isspace() or ch in ",:=" else ch for ch in str(name)) or "unnamed"


def prep_segments(marks: dict[str, int], order: Iterable[str]) -> dict[str, int]:
    """Mark name -> ms since the previous mark taken, for every mark up to ``request_sent``."""

    segments: dict[str, int] = {}
    previous = 0
    for name in order:
        value = marks.get(name)
        if name == "request_received" or not isinstance(value, int):
            continue
        segments[name] = max(0, value - previous)
        previous = max(previous, value)
        if name == _SENT:
            break
    return segments


def title_threads_alive() -> int:
    return sum(1 for t in threading.enumerate() if t.name.startswith(TITLE_THREAD_NAME) and t.is_alive())


def send_prep_line(
    marks: dict[str, int], order: Iterable[str], *, turn: Any, anchored_at: Any, cpu_ms: float | None,
    title_threads: int | None, contention: dict[str, Any] | None = None,
) -> str:
    def fmt(value: Any) -> str:
        return "na" if value is None else str(value)

    segments = prep_segments(marks, order)
    largest = max(segments, key=segments.get) if segments else None
    parts = [
        SEND_PREP_RECEIPT, f"turn={turn or 'na'}", f"anchored_at={anchored_at or 'na'}",
        f"total_ms={fmt(marks.get(_SENT))}", f"cpu_ms={fmt(None if cpu_ms is None else int(cpu_ms))}",
        f"title_threads={fmt(title_threads)}", f"largest={largest or 'na'}",
    ]
    parts += [f"{key}={fmt(value)}" for key, value in (contention or {}).items()]
    parts += [f"{name}_ms={value}" for name, value in segments.items()]
    return " ".join(parts)


def emit_send_prep_receipt(
    marks: dict[str, int], order: Iterable[str], *, turn: Any, anchored_at: Any, anchor: CpuAnchor | None,
) -> str | None:
    """Log the turn's line. Never raises: an instrument is never why a request is late or lost."""

    try:
        cpu_ms = None if anchor is None else (time.process_time() - anchor.process) * 1000.0
        text = send_prep_line(marks, order, turn=turn, anchored_at=anchored_at, cpu_ms=cpu_ms,
                              title_threads=title_threads_alive(), contention=contention_fields(anchor, cpu_ms))
    except Exception:
        logger.debug("send_prep_receipt not built", exc_info=True)
        return None
    logger.info("%s", text)
    return text


__all__ = [
    "SEND_PREP_RECEIPT", "TITLE_THREAD_NAME", "TOP_THREADS", "CpuAnchor", "contention_fields",
    "emit_send_prep_receipt", "prep_segments", "send_prep_line", "thread_cpu_seconds",
]
