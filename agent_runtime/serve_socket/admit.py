"""``ConnectionAdmitter`` — admit, authenticate, dispatch, count and drop connected sockets.

The half of the socket lane that needs no listener (review w1118a.79 of
`MC-PHONE-DRIVEN-THE-PHONE-DIALS-OUT-SO-A-COMPUTER-CAN-REACH-ITS-ENGINE`): ``server.py``
keeps the bind and the accept loop, and hands each accepted socket here. A phone, which
runs no listener (D3 2026-09-30), hands its OUTBOUND lane here instead
(``agent_runtime.reverse_lane``): the same hello, the same authentication, the same
typed rejections, the same read loop, the same connection table, on a byte source the
phone dialled rather than one it accepted.

``binding`` is what the proof is bound to, and each end knows it from its own side: the
port a listener listens on, or the lane id a phone minted for its outbound lane. It is
never read off the peer's frame.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable

from agent_runtime.clock import now_iso
from agent_runtime.serve_socket.vocabulary import (
    BROADCAST_BUDGET_SECONDS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_PENDING_CONNECTIONS,
    HELLO_DEADLINE_SECONDS,
    HELLO_REJECT_PENALTY_SECONDS,
    HELLO_TIMEOUT_LIMIT,
    HELLO_TIMEOUT_WINDOW_SECONDS,
    IO_TIMEOUT_SECONDS,
    REJECT_DRAINING,
    REJECT_HANDSHAKE_THROTTLED,
    REJECT_HELLO_MALFORMED,
    REJECT_RATE_LIMITED,
    REJECT_TLS_HANDSHAKE_FAILED,
    REJECT_TOO_MANY_CONNECTIONS,
    REJECT_TOO_MANY_PENDING,
)
from agent_runtime.serve_socket.hello import (
    HELLO_CONTRACT_VERSION,
    HelloAuthOutcome,
    HelloRateLimiter,
)
from agent_runtime.serve_socket.connection import SocketConnection
from agent_runtime.serve_socket.handshake import handshake, read_loop, reject, wrap_tls
from agent_runtime.serve_socket.wire import _LineReader, _peer_text, _reached_at

__layer__ = "lanes"

__all__ = [
    "ConnectionAdmitter",
    "HandoffHook",
]

#: After a hello authenticated, before the connection joins the table: a hook that may
#: TAKE the socket for another use (the reverse lane's park and attach) and answers True
#: when it did. Called on the connection's own thread, which is the one point nothing
#: else reads the socket.
HandoffHook = Callable[["ConnectionAdmitter", SocketConnection, _LineReader, dict[str, Any]], bool]


def _disable_nagle(sock: Any) -> None:
    """Set TCP_NODELAY on a connected socket (RT-SERVE-SOCKET-NODELAY).

    Per-token frames are small writes; with Nagle on, the kernel holds one
    behind the peer's delayed ACK and the launcher sees text arrive in bunches
    (as ``tui_gateway/ws.py::_disable_nagle`` found for the TUI lane). A
    transport that is not TCP (a unix or pipe socket) refuses the option with
    ``OSError``; that is not this connection's failure, so it is tolerated.
    """

    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass


class ConnectionAdmitter:
    """Authenticate connected sockets and feed the shared dispatcher. No listener."""

    def __init__(
        self,
        store_root: Path | str,
        *,
        boot_id: str,
        dispatch_line: Callable[[str, SocketConnection], Any],
        hello_payload: Callable[[dict[str, Any], SocketConnection], dict[str, Any]],
        token_provider: Callable[[], str | None],
        on_disconnect: Callable[[SocketConnection], None] | None = None,
        log: Callable[[dict[str, Any]], None] | None = None,
        ssl_context: Any = None,
        authenticator: Callable[[dict[str, Any], str, Any], HelloAuthOutcome]
        | None = None,
        transport_name: str = "socket",
        frame_contract: int = 1,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_pending_connections: int = DEFAULT_MAX_PENDING_CONNECTIONS,
        rate_limiter: HelloRateLimiter | None = None,
        timeout_limiter: HelloRateLimiter | None = None,
        hello_deadline_seconds: float = HELLO_DEADLINE_SECONDS,
        io_timeout_seconds: float = IO_TIMEOUT_SECONDS,
        reject_penalty_seconds: float = HELLO_REJECT_PENALTY_SECONDS,
        handoff: HandoffHook | None = None,
    ) -> None:
        self._store_root = Path(store_root)
        self._boot_id = str(boot_id)
        self._dispatch_line = dispatch_line
        self._hello_payload = hello_payload
        #: Returns THIS root's shared secret, or None. Called once per
        #: handshake and never retained: the server needs the key to recompute
        #: a proof, and nothing else — no frame, log, or error derived from it
        #: ever carries the value.
        self._token_provider = token_provider
        self._on_disconnect = on_disconnect
        self._log = log
        #: ``None`` on the loopback lane — local trust model unchanged, and a
        #: local process pays no handshake to reach a service it could read the
        #: token file of anyway. Set on the gateway lane (R1). ``None`` on a
        #: reverse lane too: its TLS is the dialler's, already negotiated.
        self._ssl_context = ssl_context
        #: The credential model. ``None`` means the per-root token, i.e. exactly
        #: what this class did before the seam existed — see
        #: ``handshake.authenticate_hello``.
        self._authenticator = authenticator
        #: What every frame this lane answers is tagged with, and what
        #: ``call_authorization`` keys its structural guard on. ``socket`` for
        #: loopback, ``gateway`` for the second listener and for a reverse lane.
        self._transport_name = str(transport_name or "socket")
        self._frame_contract = int(frame_contract)
        self._max_connections = max(1, int(max_connections))
        self._max_pending = max(1, int(max_pending_connections))
        self._rate_limiter = rate_limiter or HelloRateLimiter()
        self._timeout_limiter = timeout_limiter or HelloRateLimiter(
            limit=HELLO_TIMEOUT_LIMIT, window_seconds=HELLO_TIMEOUT_WINDOW_SECONDS
        )
        self._hello_deadline = float(hello_deadline_seconds)
        self._io_timeout = float(io_timeout_seconds)
        self._reject_penalty = float(reject_penalty_seconds)
        self._handoff = handoff
        #: The listener's port, when there is a listener (``ServeSocketServer``).
        self._port: int | None = None

        self._connections: dict[str, SocketConnection] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._draining = False
        self._next_connection = 0
        self._accepted = 0
        self._rejected = 0
        #: Accepted, not yet authenticated. Bounded separately (see
        #: DEFAULT_MAX_PENDING_CONNECTIONS) and reported, because a peer that
        #: has proven nothing is exactly the peer no other counter was watching.
        self._pending = 0
        self._pending_peak = 0
        self._hello_timeouts = 0
        #: A handshake that raised instead of deciding. Counted separately from
        #: the rejections it is now converted into, because "we could not even
        #: process this peer" is a different operational fact from "we refused
        #: it", and the first one is the one that used to leave no trace at all.
        self._handshake_errors = 0
        self._last_handshake_error: str | None = None
        self._rejected_by_reason: dict[str, int] = {}

    # ── lifecycle ───────────────────────────────────────────────────────────

    def begin_drain(self) -> None:
        """Refuse NEW connections; existing ones stay up to be told.

        The refusal of new OPS is not this object's decision — it belongs to the
        shared dispatcher, which already refuses every request the same way on
        every transport. Duplicating that rule here is how two transports start
        disagreeing about what draining means.
        """

        with self._lock:
            if self._draining:
                return
            self._draining = True
        self._emit_log({"event": "serve_socket_draining"})

    def broadcast(
        self,
        frame: dict[str, Any],
        *,
        budget_seconds: float | None = BROADCAST_BUDGET_SECONDS,
    ) -> int:
        """Send *frame* to every authenticated connection. Returns the count.

        Bounded as a WHOLE, not per connection. This runs on the drain path,
        where the old per-connection budget summed: 32 subscribers whose
        readers had stopped reading could each park a ``sendall`` for
        IO_TIMEOUT_SECONDS, so announcing a drain could outlast the drain. With
        one deadline across the pass, the worst case is a single parked write
        plus this budget, and the connections that did not get the frame are
        COUNTED and logged rather than silently missed.
        """

        delivered = 0
        skipped = 0
        deadline = (
            None if budget_seconds is None else time.monotonic() + float(budget_seconds)
        )
        for connection in self.connections():
            if not connection.authenticated:
                continue
            if deadline is not None and time.monotonic() >= deadline:
                skipped += 1
                continue
            lock_timeout = 0.5
            if deadline is not None:
                lock_timeout = max(0.0, min(lock_timeout, deadline - time.monotonic()))
            if connection.try_emit(frame, lock_timeout=lock_timeout):
                delivered += 1
            else:
                skipped += 1
        if skipped:
            self._emit_log(
                {
                    "event": "serve_socket_broadcast_incomplete",
                    "frame_event": frame.get("event"),
                    "delivered": delivered,
                    "skipped": skipped,
                }
            )
        return delivered

    def close(self, reason: str = "shutdown") -> None:
        """Close every connection. A listener's own close also stops accepting."""

        self._stop.set()
        for connection in self.connections():
            self._drop_connection(connection, reason=reason)

    def drop_where(self, predicate: Callable[[SocketConnection], bool], *, reason: str) -> int:
        """Close every connection *predicate* names (a revoked grant's lanes). Returns the count."""

        dropped = 0
        for connection in self.connections():
            if predicate(connection):
                self._drop_connection(connection, reason=reason)
                dropped += 1
        return dropped

    # ── introspection ───────────────────────────────────────────────────────

    def connections(self) -> list[SocketConnection]:
        with self._lock:
            return list(self._connections.values())

    def connections_payload(self) -> dict[str, Any]:
        rows = [connection.payload() for connection in self.connections()]
        with self._lock:
            accepted, rejected, draining = self._accepted, self._rejected, self._draining
            pending, pending_peak = self._pending, self._pending_peak
            hello_timeouts = self._hello_timeouts
            handshake_errors = self._handshake_errors
            last_handshake_error = self._last_handshake_error
            by_reason = dict(self._rejected_by_reason)
        return {
            "count": len(rows),
            "max_connections": self._max_connections,
            "accepted_total": accepted,
            "rejected_total": rejected,
            "draining": draining,
            # The pre-auth lane, which no counter used to watch at all.
            "pending": pending,
            "pending_peak": pending_peak,
            "max_pending_connections": self._max_pending,
            "hello_timeouts": hello_timeouts,
            "rejected_by_reason": by_reason,
            # A handshake that RAISED. Surfaced beside the rejections because an
            # unauthenticated peer must never be able to make the service
            # misbehave without leaving a number.
            "handshake_errors": handshake_errors,
            "last_handshake_error": last_handshake_error,
            "hello_contract": HELLO_CONTRACT_VERSION,
            "connections": rows,
        }

    # ── admission ───────────────────────────────────────────────────────────

    def admit(
        self,
        sock: socket.socket,
        peer: Any,
        *,
        binding: Any = None,
        initial_bytes: bytes = b"",
    ) -> None:
        """Walk one connected socket through the hello, then serve it until it ends.

        Blocks for the connection's life, on the caller's thread: the accept loop
        gives each socket its own thread, and a reverse lane's dialler is already
        one. ``binding`` defaults to the listener's port. ``initial_bytes`` are
        bytes the caller read past its own last line before handing the socket
        over, so none is lost at the seam.
        """

        if binding is None:
            binding = self._port or 0
        with self._lock:
            self._next_connection += 1
            key = f"conn-{self._next_connection}"
            at_capacity = len(self._connections) >= self._max_connections
            pending_full = self._pending >= self._max_pending
            admitted = not (at_capacity or pending_full)
            if admitted:
                self._pending += 1
                self._pending_peak = max(self._pending_peak, self._pending)
        _disable_nagle(sock)
        connection = SocketConnection(
            key=key,
            sock=sock,
            peer=_peer_text(peer),
            connected_at=now_iso(),
            # Read HERE, at accept, and not lazily at greeting time: a TLS wrap
            # or a refusal can close this socket before the frame is built, and
            # a `getsockname()` on a closed socket answers nothing useful. The
            # measurement is a property of the accept, so it is taken there.
            reached_at=_reached_at(sock),
            transport=self._transport_name,
        )
        try:
            sock.settimeout(self._hello_deadline)
        except OSError:
            pass
        reader: _LineReader | None = None
        try:
            # TLS BEFORE the admission checks, not after, and the cost is
            # deliberate. Every one of those checks answers with a typed
            # ``hello_rejected`` frame, and on an encrypted listener a frame
            # written to a socket the peer has not negotiated is bytes it cannot
            # read — so refusing before the wrap would turn every capacity and
            # throttle refusal into an unexplained disconnect. The typed reason
            # IS the observability; paying a handshake to deliver one is the
            # right trade.
            if self._ssl_context is not None:
                wrapped = wrap_tls(self, sock)
                if wrapped is None:
                    # Nothing readable can be sent to a peer that never
                    # negotiated, so this refusal is COUNTED rather than
                    # announced — and counted against the silence throttle,
                    # because a half-open TLS handshake is, from the accept
                    # loop's point of view, exactly a peer that said nothing.
                    with self._lock:
                        self._rejected += 1
                        self._rejected_by_reason[REJECT_TLS_HANDSHAKE_FAILED] = (
                            self._rejected_by_reason.get(REJECT_TLS_HANDSHAKE_FAILED, 0)
                            + 1
                        )
                    self._timeout_limiter.record_failure()
                    self._emit_log(
                        {
                            "event": "serve_socket_connection_rejected",
                            "connection": connection.key,
                            "peer": connection.peer,
                            "reason": REJECT_TLS_HANDSHAKE_FAILED,
                        }
                    )
                    connection.close(REJECT_TLS_HANDSHAKE_FAILED)
                    return
                connection.sock = wrapped
                sock = wrapped
            if at_capacity:
                reject(self, connection, REJECT_TOO_MANY_CONNECTIONS)
                return
            if pending_full:
                # The bound that did not exist: 64 peers that said nothing sat
                # on 64 threads because only AUTHENTICATED connections counted.
                reject(self, connection, REJECT_TOO_MANY_PENDING)
                return
            if self._rate_limiter.blocked():
                reject(self, connection, REJECT_RATE_LIMITED)
                return
            if self._timeout_limiter.blocked():
                reject(self, connection, REJECT_HANDSHAKE_THROTTLED)
                return
            if self._draining:
                reject(self, connection, REJECT_DRAINING)
                return
            try:
                reader = handshake(
                    self, connection, sock, key, binding=binding, initial_bytes=initial_bytes
                )
            except Exception as exc:
                # The pre-auth path is driven entirely by an unauthenticated
                # peer, so ONE uncaught call on it is one too many: an escaping
                # exception used to mean no rejection frame, no accounting, no
                # limiter charge, a socket left to the garbage collector, and a
                # traceback on the protocol stream. Anything that gets here is
                # a peer we could not process — charged as an auth failure so
                # it cannot be used to hammer the handshake for free — and it
                # is COUNTED, because the whole point of the finding was that
                # the attempt was invisible.
                reader = None
                with self._lock:
                    self._handshake_errors += 1
                    self._last_handshake_error = type(exc).__name__
                try:
                    reject(self, connection, REJECT_HELLO_MALFORMED)
                except Exception:
                    connection.close("handshake_failed")
        finally:
            if admitted:
                with self._lock:
                    self._pending = max(0, self._pending - 1)
        if reader is None:
            return
        read_loop(self, connection, reader)

    # ── connection teardown ─────────────────────────────────────────────────

    def _drop_connection(self, connection: SocketConnection, *, reason: str) -> None:
        with self._lock:
            existed = self._connections.pop(connection.key, None) is not None
        connection.close(reason)
        if not existed:
            return
        if self._on_disconnect is not None:
            try:
                self._on_disconnect(connection)
            except Exception:
                pass
        self._emit_log(
            {
                "event": "serve_socket_connection_close",
                "connection": connection.key,
                "client": connection.client,
                "reason": reason,
                "frames_out": connection.frames_out,
                "bytes_out": connection.bytes_out,
            }
        )

    def _emit_log(self, payload: dict[str, Any]) -> None:
        if self._log is None:
            return
        try:
            self._log({"boot_id": self._boot_id, **payload})
        except Exception:  # pragma: no cover - an instrument may not raise
            pass
