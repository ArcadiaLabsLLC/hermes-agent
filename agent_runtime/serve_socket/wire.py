"""Line framing and small wire coercions shared by the server and the client:
``_LineReader`` (bounded line reads), JSON object parsing, text
coercion, accept-error classification and the ``reached_at`` stamp.
"""

from __future__ import annotations

import errno
import json
import socket
import time
from typing import Any

from agent_runtime.serve_socket.vocabulary import MAX_LINE_BYTES

__layer__ = "models"

__all__ = [
    "_LineReader",
    "_LineTooLong",
    "_client_text",
    "_is_fatal_accept_error",
    "_parse_object",
    "_peer_text",
    "_reached_at",
]


# ── line framing ─────────────────────────────────────────────────────────────


class _LineTooLong(Exception):
    pass


class _LineReader:
    """NDJSON line assembly over a byte stream, with a hard per-line bound."""

    def __init__(self, sock: Any, *, max_line_bytes: int = MAX_LINE_BYTES) -> None:
        self._sock = sock
        self._buffer = b""
        self._max = int(max_line_bytes)

    def read_line(self, *, deadline_seconds: float | None) -> str | None:
        """Next line, or None at end of stream.

        ``deadline_seconds`` bounds the WHOLE read (the hello phase); None means
        "wait as long as the socket's own timeout allows", and a socket timeout
        propagates so the caller can treat it as an idle lap.
        """

        deadline = None if deadline_seconds is None else time.monotonic() + deadline_seconds
        while True:
            if b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                return line.decode("utf-8", errors="replace")
            if len(self._buffer) > self._max:
                raise _LineTooLong()
            if deadline is not None and time.monotonic() >= deadline:
                return None
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:  # noqa: UP041
                if deadline is None:
                    raise
                continue
            except ConnectionResetError:
                # A peer that closed rudely (RST) is a peer that is gone. The
                # distinction between FIN and RST is not one any caller of this
                # reader can act on differently, and raising it would turn an
                # ordinary disconnect into an error path.
                chunk = b""
            if not chunk:
                if self._buffer:
                    line, self._buffer = self._buffer, b""
                    return line.decode("utf-8", errors="replace")
                return None
            self._buffer += chunk


def _parse_object(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _client_text(value: Any) -> str | None:
    """A client-supplied label, bounded and flattened.

    Client-controlled text lands in log lines and in ``harness status`` output,
    so it is capped and stripped of anything that could forge a second line.
    """

    if not isinstance(value, str):
        return None
    flattened = " ".join(value.split())
    return flattened[:64] or None


def _peer_text(peer: Any) -> str:
    try:
        return f"{peer[0]}:{peer[1]}"
    except Exception:
        return str(peer)


def _reached_at(sock: Any) -> dict[str, Any] | None:
    """``{host, port}`` the far side actually reached, or ``None``.

    D12. ``getsockname()`` on an ACCEPTED socket returns the local end of that
    particular connection — not the listener's bind — so on a wildcard listener
    it names the one interface this client arrived on. That is the measurement
    the pairing lane keeps re-deriving and throwing away.

    Never raises and never guesses: a socket that cannot answer, or answers
    with a sockaddr that is not an IP one (an AF_UNIX path, a raw family),
    yields ``None``. A wildcard or empty host is also refused — a bind address
    is not something anyone can dial (R-D1), and passing one along here would
    hand the far side exactly the ``0.0.0.0`` that lane spent a wave removing.
    """

    try:
        sockaddr = sock.getsockname()
    except Exception:
        return None
    try:
        host = str(sockaddr[0])
        port = int(sockaddr[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not host or host in {"0.0.0.0", "::", "*"} or port <= 0:
        return None
    return {"host": host, "port": port}


def _is_fatal_accept_error(exc: OSError) -> bool:
    return exc.errno in {errno.EBADF, errno.EINVAL, errno.ENOTSOCK}
