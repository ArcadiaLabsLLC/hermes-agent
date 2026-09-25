"""The frame lane's I/O primitives: the poll response cache, the request contextvars,
the frame writer, the per-line stdout/stderr proxy, the safe sink and the deferred reply.
"""

from __future__ import annotations

import contextvars
import io
import json
import threading
from typing import Any, TextIO

from hermes_cli.harness_parts.serve.constants import (
    _READ_CACHE_MAX_AGE_SECONDS,
)

__layer__ = "stores"

__all__ = [
    "_FrameWriter",
    "_LineFrameProxy",
    "_PollResponseCache",
    "_PollResponseCacheEntry",
    "_SafeSink",
    "_emit_deferred_reply",
    "_request_id",
    "_request_sink",
    "current_serve_request_id",
]


class _PollResponseCacheEntry:
    __slots__ = ("fingerprint", "lines", "code", "built_monotonic")

    def __init__(
        self, fingerprint: tuple, lines: list[str], code: int, built_monotonic: float
    ):
        self.fingerprint = fingerprint
        self.lines = lines
        self.code = code
        self.built_monotonic = built_monotonic


class _PollResponseCache:
    """Per-serve-loop stdout-payload replay cache for the read-only polls.

    Keyed by :func:`_runtime_state_fingerprint` and bounded by
    ``_READ_CACHE_MAX_AGE_SECONDS``. It caches RESPONSE BYTES — it is not the
    serve core cache (``<store_root>/serve_read_model/``), which is why it is not
    named for it. (It was not the retired ``agent_runtime/read_model.py`` either;
    that module went at Stage 6, 2026-08-22.)
    """

    def __init__(self, max_age_seconds: float = _READ_CACHE_MAX_AGE_SECONDS):
        self._entries: dict[str, _PollResponseCacheEntry] = {}
        self._lock = threading.Lock()
        self._max_age = max_age_seconds

    def get(
        self, key: str, fingerprint: tuple | None, now_monotonic: float
    ) -> _PollResponseCacheEntry | None:
        if fingerprint is None:
            return None
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or entry.fingerprint != fingerprint:
            return None
        if now_monotonic - entry.built_monotonic > self._max_age:
            return None
        return entry

    def put(
        self,
        key: str,
        fingerprint: tuple | None,
        lines: list[str],
        code: int,
        now_monotonic: float,
    ) -> None:
        # Only successful builds are worth replaying; a failed build must
        # re-run so the error stays live, not fossilized.
        if fingerprint is None or code != 0:
            return
        with self._lock:
            self._entries[key] = _PollResponseCacheEntry(
                fingerprint, lines, code, now_monotonic
            )

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harness_serve_request_id", default=None
)

#: WHERE this request's frames go. Bound by ``_run`` alongside the request id,
#: for the same span and in the same pool-worker context.
#:
#: A durable service answers more than one transport, and a handler's ``print``
#: belongs to the client that asked — not to whoever owns stdout. Unset (the
#: default) means stdout, which is every stdio request and every thread a
#: handler spawns for itself, so the stdio lane is byte-identical to the
#: pre-socket loop: same proxy, same frames, same order.
_request_sink: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "harness_serve_request_sink", default=None
)


def current_serve_request_id() -> str | None:
    """The serve frame-protocol request id bound to THIS context, or None.

    ``_run`` binds it for exactly the span of one serve-dispatched request, in
    the pool-worker context that dispatches to the command handler — so a
    non-None answer is DIRECT provenance that the current work arrived as a
    serve frame request. Every other lane reads None: a one-shot CLI turn, the
    delivery drain's forged turns, background threads.

    This is the honest "did this turn arrive via serve" fact, and the only one.
    Two proxies have already been retired for impersonating it (both live
    2026-08-09 findings): ``persona_chat_runtime_registry() is not None`` is
    really "the hot-sessions CACHE is enabled" (default off, so every live
    serve read False), and ``delivery_drain_is_live()`` is really "a delivery
    consumer exists" — a serve whose drain died is still a serve. Provenance
    questions read THIS; capability questions read the drain.
    """

    return _request_id.get()


class _FrameWriter:
    """Sole owner of the real stdout; one lock keeps frames atomic.

    ``detachable`` is the service lane's one concession (L-h item 1) and it is
    OFF by default, which is what keeps every non-``--service`` serve
    byte-identical: with it off there is no ``detach()`` call site and the
    ``BrokenPipeError`` branch below is unreachable, so a write to a dead pipe
    raises exactly where it always did. With it on, the writer can be told its
    audience has gone — the starter closed our stdin and walked away — after
    which frames are DROPPED rather than raised. A durable service must not die
    of the observer leaving; that is the whole finding.
    """

    def __init__(self, stream: TextIO, *, detachable: bool = False):
        self._stream: TextIO | None = stream
        self._lock = threading.Lock()
        self._detachable = bool(detachable)

    def detach(self) -> None:
        """Swap the starter's pipe for a null sink. Idempotent."""

        with self._lock:
            self._stream = None

    @property
    def detached(self) -> bool:
        with self._lock:
            return self._stream is None

    def emit(self, frame: dict[str, Any]) -> None:
        payload = json.dumps(frame, ensure_ascii=False, default=str)
        with self._lock:
            stream = self._stream
            if stream is None:
                # Detached: nobody is reading this pipe and there is nowhere to
                # put the frame. Socket clients are told separately, on the lane
                # they are actually attached to.
                return
            try:
                stream.write(payload + "\n")
                stream.flush()
            except BrokenPipeError:
                if not self._detachable:
                    raise
                # The starter went between the detach check and the write: the
                # same fact, learned a microsecond later. Latched here so the
                # next frame does not have to rediscover it.
                self._stream = None


class _LineFrameProxy(io.TextIOBase):
    """Stand-in for sys.stdout/sys.stderr that re-emits handler output as
    tagged line frames, buffered per request id until a newline."""

    def __init__(self, frames: _FrameWriter, event: str):
        super().__init__()
        self._frames = frames
        self._event = event
        self._buffers: dict[tuple[int | None, str | None], str] = {}
        self._captures: dict[tuple[int | None, str | None], list[str]] = {}
        self._lock = threading.Lock()
        #: RL-19. A file that every completed line is ALSO written to, set for
        #: the ``--service`` arm only. A frame is addressed to whoever is
        #: reading the transport; under ``--service`` that may be nobody at all
        #: (the launcher's three ``DEVNULL`` handles), and the runtime's own
        #: account of its afternoon must survive having no audience.
        self._mirror: Any = None

    def set_mirror(self, stream: Any) -> None:
        """Tee completed lines into *stream* as well as onto the frame sink."""

        self._mirror = stream

    def _mirror_lines(self, lines: list[str]) -> None:
        """Best effort by contract: a full disk must not break a print."""

        mirror = self._mirror
        if mirror is None or not lines:
            return
        try:
            mirror.write("".join(line + "\n" for line in lines))
        except Exception:
            pass

    def writable(self) -> bool:  # pragma: no cover - io protocol
        return True

    def isatty(self) -> bool:
        # Handlers key default output on isatty(); serve is a pipe.
        return False

    @staticmethod
    def _slot(rid: str | None) -> tuple[int | None, str | None]:
        """The partial-line buffer this write belongs to.

        Keyed by (destination, request id), not by request id alone. Request
        ids are chosen by CLIENTS, so once more than one transport is attached
        two connections may legitimately both be running ``req-1`` — and a
        buffer keyed on the id alone would splice one client's half-written
        line into the other's. Stdio's destination is None (stdout), which is
        what every pre-socket request already was.
        """

        sink = _request_sink.get()
        return (id(sink) if sink is not None else None, rid)

    def write(self, text: str) -> int:
        if not text:
            return 0
        rid = _request_id.get()
        slot = self._slot(rid)
        with self._lock:
            buffered = self._buffers.get(slot, "") + str(text)
            *lines, remainder = buffered.split("\n")
            self._buffers[slot] = remainder
            capture = self._captures.get(slot)
            if capture is not None:
                capture.extend(lines)
        self._mirror_lines(lines)
        sink = _request_sink.get() or self._frames
        for line in lines:
            sink.emit({"id": rid, "event": self._event, "line": line})
        return len(text)

    def flush(self) -> None:  # pragma: no cover - io protocol
        return None

    def begin_capture(self, rid: str | None) -> None:
        """Start mirroring [rid]'s emitted lines for the poll response cache."""
        with self._lock:
            self._captures[self._slot(rid)] = []

    def end_capture(self, rid: str | None) -> list[str]:
        """Stop mirroring and return everything captured for [rid]."""
        with self._lock:
            return self._captures.pop(self._slot(rid), [])

    def flush_request(self, rid: str | None) -> None:
        """Emit a request's unterminated tail (handler printed without a
        trailing newline) and drop its buffer."""
        slot = self._slot(rid)
        with self._lock:
            remainder = self._buffers.pop(slot, "")
            if remainder:
                capture = self._captures.get(slot)
                if capture is not None:
                    capture.append(remainder)
        if remainder:
            self._mirror_lines([remainder])
            sink = _request_sink.get() or self._frames
            sink.emit({"id": rid, "event": self._event, "line": remainder})


class _SafeSink:
    """A frame sink that never raises — the socket lane's request path.

    A pool worker's ``finally`` MUST emit its terminal ``exit`` frame and clean
    up its inflight entry; a client that hung up mid-request would otherwise
    take that bookkeeping down with it, leaking the request id forever and
    stalling any drain waiting on it. Stdout is deliberately NOT wrapped: the
    stdio pipe failing is the process losing its transport, and that has always
    propagated.
    """

    __slots__ = ("_target", "write_failures")

    def __init__(self, target: Any):
        self._target = target
        self.write_failures = 0

    def emit(self, frame: dict[str, Any]) -> None:
        try:
            self._target.emit(frame)
        except Exception:
            self.write_failures += 1


def _emit_deferred_reply(build: Any, sink: Any) -> None:
    """Finish ONE deferred method reply on a pool worker and write it.

    ``build`` is already exception-proofed by ``serve_rpc.deferred_reply`` — it
    returns a typed ``-32000`` rather than raising, because a raise here would
    be a client waiting forever for a frame nobody writes. The belt below is for
    the write itself: the socket lane's sink swallows a dead client
    (:class:`_SafeSink`), and stdout's deliberately does not, so a stdio client
    that went away must not take a pool worker's thread down with it.
    """

    try:
        frame = build()
    except BaseException:  # pragma: no cover - deferred_reply already caught it
        return
    try:
        sink.emit(frame)
    except Exception:
        pass
