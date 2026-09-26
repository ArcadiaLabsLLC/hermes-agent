"""The child-process pipe pumps: ONE owner for draining a pipe and releasing its reader.

Program §3.1d helper owner (``agent_runtime/subprocess_pumps``), created by lane
2B-C for ``tools/agent_chat_dispatch``; ``persona_chat_actor_prewarm`` and
``persona_prewarm`` fold their ``_drain`` copies in their own lanes. ``sink`` is
anything with ``append(text)`` — the dispatch lane passes a tail-keeping bound
(``tools/agent_chat_dispatch/child.py::_BoundedTail``), and it is handed ONE
LINE per call, because that bound keeps a single chunk whole and the child's
payload is a single line.

WHY A PUMP NEVER BLOCKS IN ``read`` (lane Q-RUNTIME, 2026-09-25). The first
shape was ``for line in iter(stream.readline, "")`` plus a release that closed
the stream to unblock it. On Windows that close does not unblock anything: the
buffered reader's ``close`` waits on the lock the blocked ``readline`` holds,
so a grandchild holding the pipe open ("go run the suite") parked the
SUPERVISOR until the grandchild exited, and the dispatch's completion was never
recorded meanwhile. So a pump now asks whether bytes are WAITING before it
reads — ``select`` on POSIX, ``PeekNamedPipe`` on Windows, where ``select``
cannot poll a pipe — reads only what is there, and checks its own stop flag
between polls. Nothing ever closes a handle under a blocked reader: a pump
closes its OWN stream when it ends, on its own thread.

The mechanism is the one upstream's ``tools/environments/base_output.py``
drain uses (``_drain_fd_select`` / ``_drain_fd_windows``). It is not imported:
those names are private, drain stdout only, and end on a bound tied to the
process exiting, where these pumps end on an explicit release.
"""

from __future__ import annotations

import codecs
import io
import os
import threading
from typing import Any

__layer__ = "policy"

__all__ = ["drain", "release_pumps"]

#: How long one readiness poll waits before the stop flag is looked at again.
#: It is also the bound on how late a release is honoured.
_POLL_SECONDS = 0.05

#: The most bytes one ``os.read`` takes. Only ever as many as are WAITING, so
#: the read cannot block.
_READ_CHUNK = 65536

#: The pump's decode, matching the ``Popen(text=True, encoding="utf-8",
#: errors="replace")`` stream it replaces reads on, universal newlines included.
_ENCODING = "utf-8"
_ERRORS = "replace"


class _Pump(threading.Thread):
    """A daemon pump with a stop flag the release sets; see :func:`drain`."""

    def __init__(self, stream, sink: Any) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._sink = sink
        self.stop = threading.Event()

    def run(self) -> None:
        try:
            fd = _fileno(self._stream)
            if fd is None:
                _pump_lines(self._stream, self._sink)
            else:
                _pump_fd(fd, self._sink, self.stop)
        except Exception:  # pragma: no cover - pipe torn down under us
            pass
        finally:
            try:
                self._stream.close()
            except Exception:
                pass


def drain(stream, sink: Any) -> threading.Thread:
    """Consume a child pipe for its WHOLE lifetime on a daemon thread.

    Both pipes get one of these, always. A stderr pipe nobody reads fills its OS
    buffer and wedges the child mid-write — a hang that looks exactly like a slow
    turn, and the standing reason this repo requires draining both streams
    rather than only the one being parsed.
    """

    pump = _Pump(stream, sink)
    pump.start()
    return pump


def release_pumps(proc, threads) -> None:
    """Join the pumps, then stop them if a survivor still holds the pipe.

    EOF only arrives when every writer has closed. A grandchild that inherited
    the pipe — which is exactly what "go run the suite" spawns — or a tree
    member that survived the kill keeps it open, so a plain join leaks two
    daemon threads PER DISPATCH, permanently, inside a process that is meant to
    run for days.

    The forced arm sets each pump's stop flag; the pump sees it at its next
    poll, flushes what it read, and closes its own stream. Nothing here touches
    a stream, so this can never wait on a reader. Best effort by contract: a
    thread that still will not budge is one leak, not a growing one, and never
    a failed dispatch. ``proc`` is kept for the callers' symmetry; the pumps
    own their streams.
    """

    del proc
    for thread in threads:
        thread.join(timeout=10)
    if not any(thread.is_alive() for thread in threads):
        return
    for thread in threads:
        stop = getattr(thread, "stop", None)
        if isinstance(stop, threading.Event):
            stop.set()
    for thread in threads:
        thread.join(timeout=2)


def _fileno(stream) -> int | None:
    """The stream's OS descriptor, or None for an in-memory stand-in."""

    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return None
    return fd if isinstance(fd, int) and fd >= 0 else None


def _pump_lines(stream, sink: Any) -> None:
    """A stream with no descriptor cannot be polled; read it to EOF."""

    for line in iter(stream.readline, ""):
        if not line:
            break
        sink.append(line)


def _pump_fd(fd: int, sink: Any, stop: threading.Event) -> None:
    """Read ``fd`` only when bytes are waiting, one sink line at a time, until EOF or ``stop``."""

    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder(_ENCODING)(errors=_ERRORS), translate=True
    )
    waiting = _waiting_windows(fd) if os.name == "nt" else _waiting_posix(fd)
    partial = ""
    try:
        while not stop.is_set():
            count = waiting()
            if count is None:
                break  # EOF: every writer closed
            if count == 0:
                stop.wait(_POLL_SECONDS)
                continue
            chunk = os.read(fd, min(count, _READ_CHUNK))
            if not chunk:
                break
            partial = _emit_lines(partial + decoder.decode(chunk), sink)
    except (OSError, ValueError):
        pass  # descriptor gone: keep what was captured
    tail = partial
    try:
        tail += decoder.decode(b"", final=True)
    except Exception:  # pragma: no cover - a final flush never raises in practice
        pass
    if tail:
        sink.append(tail)


def _emit_lines(text: str, sink: Any) -> str:
    """Append every complete line of ``text``; return the unterminated rest."""

    start = 0
    while True:
        end = text.find("\n", start)
        if end < 0:
            return text[start:]
        sink.append(text[start : end + 1])
        start = end + 1


def _waiting_posix(fd: int):
    """``select`` readiness: 0 when nothing is waiting, else a read size that cannot block."""

    import select

    def waiting() -> int | None:
        ready, _, _ = select.select([fd], [], [], _POLL_SECONDS)
        # Readable means one read will not block; at EOF it returns b"", which
        # the caller reads as the end.
        return _READ_CHUNK if ready else 0

    return waiting


def _waiting_windows(fd: int):
    """``PeekNamedPipe`` readiness: None at EOF (broken pipe), else bytes waiting."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
    ]
    peek.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    available = wintypes.DWORD(0)

    def waiting() -> int | None:
        if not peek(handle, None, 0, None, ctypes.byref(available), None):
            return None  # ERROR_BROKEN_PIPE: every writer closed
        return int(available.value)

    return waiting
