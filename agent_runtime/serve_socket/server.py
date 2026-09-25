"""``ServeSocketServer`` — bind, accept, authenticate, frame, count, close.

Moved whole in the MOVE commit (ruling Q8: a class moved whole may cross the
ceiling for exactly one commit); the CHANGE lifts the handshake methods into
``handshake`` and the per-accept body out of ``_accept_loop``.
"""

from __future__ import annotations

import secrets
import select
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable

from agent_runtime.serve_socket.vocabulary import (
    AUTH_FAILURE_REJECT_REASONS,
    BROADCAST_BUDGET_SECONDS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_PENDING_CONNECTIONS,
    HELLO_DEADLINE_SECONDS,
    HELLO_PROOF_ALGORITHM,
    HELLO_REJECT_PENALTY_SECONDS,
    HELLO_TIMEOUT_LIMIT,
    HELLO_TIMEOUT_WINDOW_SECONDS,
    IO_TIMEOUT_SECONDS,
    NONCE_BYTES,
    REJECT_BAD_PROOF,
    REJECT_DRAINING,
    REJECT_HANDSHAKE_THROTTLED,
    REJECT_HELLO_MALFORMED,
    REJECT_HELLO_REQUIRED,
    REJECT_HELLO_TIMEOUT,
    REJECT_HELLO_TOO_LONG,
    REJECT_RATE_LIMITED,
    REJECT_TLS_HANDSHAKE_FAILED,
    REJECT_TOO_MANY_CONNECTIONS,
    REJECT_TOO_MANY_PENDING,
    SOCKET_HOST,
    _REJECT_LINGER_SECONDS,
)
from agent_runtime.serve_socket.hello import (
    HELLO_CONTRACT_VERSION,
    HelloAuthOutcome,
    HelloRateLimiter,
    verify_hello_proof,
)
from agent_runtime.serve_socket.connection import SocketConnection
from agent_runtime.serve_socket.wire import (
    _LineReader,
    _LineTooLong,
    _client_text,
    _is_fatal_accept_error,
    _now_iso,
    _parse_object,
    _peer_text,
    _reached_at,
)

__layer__ = "lanes"

__all__ = [
    "ServeSocketServer",
]


# ── the server ───────────────────────────────────────────────────────────────


class ServeSocketServer:
    """Bind, accept, authenticate, and feed the shared dispatcher.

    Two-phase start on purpose. :meth:`bind` happens EARLY — before the serve
    registry entry and the ready frame, so both can carry the real port — while
    :meth:`start_accepting` happens after the request pool exists. A client that
    connects in between waits in the listen backlog, which is exactly what a
    backlog is for; dispatching a request into a pool that does not exist yet is
    not.
    """

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
        host: str = SOCKET_HOST,
        port: int = 0,
        ssl_context: Any = None,
        authenticator: Callable[[dict[str, Any], str, int], HelloAuthOutcome]
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
        self._host = host
        #: 0 = ephemeral, which is what the loopback lane has always done and
        #: what every existing caller gets by omission. A FIXED port exists for
        #: the gateway lane, where an operator has to write a firewall rule and
        #: a phone has to be told a number that survives a restart.
        self._bind_port = max(0, int(port))
        #: ``None`` on the loopback lane — local trust model unchanged, and a
        #: local process pays no handshake to reach a service it could read the
        #: token file of anyway. Set on the gateway lane (R1).
        self._ssl_context = ssl_context
        #: The credential model. ``None`` means the per-root token, i.e. exactly
        #: what this class did before the seam existed — see
        #: :meth:`_authenticate_hello`.
        self._authenticator = authenticator
        #: What every frame this listener answers is tagged with, and what
        #: ``call_authorization`` keys its structural guard on. ``socket`` for
        #: loopback, ``gateway`` for the second listener.
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

        self._listener: socket.socket | None = None
        #: The accept loop's wakeup, and the reason it exists: closing a
        #: listening socket from another thread aborts a pending ``accept()``
        #: on Windows and does NOT wake one on Linux. A loop parked in
        #: ``accept()`` therefore outlived ``close()`` on every POSIX host and
        #: ``accept_loop_exited`` — the field whose whole purpose is "the loop
        #: never stops quietly" — was stamped by whichever platform happened to
        #: be kind. The loop waits on this pair BESIDE the listener, so the
        #: ending is the same everywhere and is caused, not raced for. The
        #: write end is closed by ``_close_listener``; the read end is closed
        #: by the only thread that ever selects on it.
        self._wake_read: socket.socket | None = None
        self._wake_write: socket.socket | None = None
        self._port: int | None = None
        self._accept_thread: threading.Thread | None = None
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
        #: Every way the accept loop can fail, counted and SURFACED. The loop
        #: dying used to be invisible while the port stayed advertised — a
        #: service that answers its discovery record and nothing else.
        self._accept_errors = 0
        self._accept_loop_exited: str | None = None
        #: A handshake that raised instead of deciding. Counted separately from
        #: the rejections it is now converted into, because "we could not even
        #: process this peer" is a different operational fact from "we refused
        #: it", and the first one is the one that used to leave no trace at all.
        self._handshake_errors = 0
        self._last_handshake_error: str | None = None
        self._rejected_by_reason: dict[str, int] = {}
        self._started_at: str | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def started_at(self) -> str | None:
        return self._started_at

    def bind(self) -> int:
        """Bind this listener's host/port and listen. Returns the port.

        Ephemeral by default, which is the loopback lane's unchanged behaviour;
        a non-zero ``port`` constructor argument pins it. Still no
        ``SO_REUSEADDR``, and that matters MORE with a fixed port than it ever
        did with an ephemeral one: on Windows it permits a second process to
        bind a port already in use, so on a pinned port it would turn "the
        address is taken" into a silent hijack of a listener a phone is about to
        dial. A bind that cannot have the port RAISES, and the caller reports a
        typed outcome rather than serving from somewhere else.
        """

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR — see the module docstring.
        listener.bind((self._host, self._bind_port))
        listener.listen(max(8, self._max_connections))
        # Non-blocking, because the accept loop now decides readiness with
        # ``select`` and must never park in ``accept()`` — that is the one
        # place ``close()`` cannot reach it on a POSIX host. The socket handed
        # back by ``accept()`` gets its own explicit timeout in
        # ``_serve_connection``, so nothing downstream inherits this.
        listener.setblocking(False)
        self._wake_read, self._wake_write = socket.socketpair()
        self._wake_read.setblocking(False)
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        self._started_at = _now_iso()
        return self._port

    def start_accepting(self) -> None:
        if self._listener is None:
            raise RuntimeError("bind() must run before start_accepting()")
        if self._accept_thread is not None:
            return
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="harness-serve-socket-accept", daemon=True
        )
        self._accept_thread.start()

    def begin_drain(self) -> None:
        """Stop accepting NEW connections; existing ones stay up to be told.

        The refusal of new OPS is not this object's decision — it belongs to the
        shared dispatcher, which already refuses every request the same way on
        both transports. Duplicating that rule here is how two transports start
        disagreeing about what draining means.
        """

        with self._lock:
            if self._draining:
                return
            self._draining = True
        self._close_listener()
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
        """Stop accepting, close every connection, and release nothing else.

        The LOCK is not released here: its owner is the serve loop, which holds
        it for the process's lifetime and drops it as the last act of the drain.
        """

        self._stop.set()
        self._close_listener()
        for connection in self.connections():
            self._drop_connection(connection, reason=reason)
        thread = self._accept_thread
        if thread is None:
            # Bound but never accepted: nobody is selecting on the read end, so
            # nobody else will ever close it.
            self._close_wake_read()
        elif thread.is_alive():
            thread.join(2.0)

    # ── introspection ───────────────────────────────────────────────────────

    def connections(self) -> list[SocketConnection]:
        with self._lock:
            return list(self._connections.values())

    def connections_payload(self) -> dict[str, Any]:
        rows = [connection.payload() for connection in self.connections()]
        with self._lock:
            accepted, rejected, draining = self._accepted, self._rejected, self._draining
            pending, pending_peak = self._pending, self._pending_peak
            accept_errors = self._accept_errors
            accept_loop_exited = self._accept_loop_exited
            hello_timeouts = self._hello_timeouts
            handshake_errors = self._handshake_errors
            last_handshake_error = self._last_handshake_error
            by_reason = dict(self._rejected_by_reason)
        return {
            "port": self._port,
            "host": self._host,
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
            # An accept loop that stopped while the port stayed advertised is
            # the one failure a client cannot detect by connecting; both the
            # error count and the loop's exit reason are stated, always.
            "accept_errors": accept_errors,
            "accept_loop_exited": accept_loop_exited,
            # A handshake that RAISED. Surfaced next to the accept-loop
            # failures for the same reason: an unauthenticated peer must never
            # be able to make the service misbehave without leaving a number.
            "handshake_errors": handshake_errors,
            "last_handshake_error": last_handshake_error,
            "hello_contract": HELLO_CONTRACT_VERSION,
            "connections": rows,
        }

    # ── accept loop ─────────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Accept until stopped, and ANNOUNCE the ending whatever it is.

        Nothing in here may terminate the loop quietly. The listener stays
        bound and the discovery record stays published for as long as this
        process lives, so a loop that stopped without a word leaves a service
        that answers "connect to me" and then never answers anything — the
        exact false-all-clear shape this workstream exists to retire. Every
        exit therefore records ``accept_loop_exited`` (readable in the
        ``connections`` block) and emits a typed log line.
        """

        outcome = "stopped"
        try:
            while not self._stop.is_set():
                listener = self._listener
                if listener is None:
                    outcome = "listener_closed"
                    return
                try:
                    ready, _, _ = select.select([listener, self._wake_read], [], [])
                except ValueError:
                    # A closed socket answers ``fileno() == -1``, which select
                    # refuses. That IS the listener being gone.
                    outcome = "listener_closed"
                    return
                except OSError as exc:
                    if self._stop.is_set() or self._listener is None:
                        outcome = "listener_closed"
                        return
                    with self._lock:
                        self._accept_errors += 1
                    self._emit_log(
                        {
                            "event": "serve_socket_accept_error",
                            "phase": "wait",
                            "reason": type(exc).__name__,
                        }
                    )
                    if _is_fatal_accept_error(exc):
                        outcome = f"fatal_accept_error:{type(exc).__name__}"
                        return
                    time.sleep(0.05)
                    continue
                if self._stop.is_set() or self._listener is None:
                    outcome = "listener_closed"
                    return
                if listener not in ready:
                    # Only the wakeup spoke, and the check above already said
                    # the lane is still open. Nothing was dialled; go back to
                    # waiting rather than inventing an ending.
                    continue
                try:
                    sock, peer = listener.accept()
                except BlockingIOError:
                    # ``select`` promised a peer and the kernel no longer has
                    # one (a connection aborted between the two calls). Not an
                    # error, and — because the listener is non-blocking — not a
                    # park either.
                    continue
                except OSError as exc:
                    if self._stop.is_set() or self._listener is None:
                        outcome = "listener_closed"
                        return
                    # A typed line, never process death: an accept that fails on
                    # a transient OS condition must not take the runtime with it.
                    with self._lock:
                        self._accept_errors += 1
                    self._emit_log(
                        {
                            "event": "serve_socket_accept_error",
                            "phase": "accept",
                            "reason": type(exc).__name__,
                        }
                    )
                    if _is_fatal_accept_error(exc):
                        outcome = f"fatal_accept_error:{type(exc).__name__}"
                        return
                    time.sleep(0.05)
                    continue
                # INSIDE the loop's error handling, deliberately. A thread
                # spawn that fails (the interpreter is out of threads — which
                # is precisely what an unbounded pre-auth flood produces) used
                # to propagate out of the accept loop and kill it, silently,
                # while the port stayed advertised. It is now one accounted
                # rejection of one peer, and the lane keeps serving everybody
                # else.
                try:
                    threading.Thread(
                        target=self._serve_connection,
                        args=(sock, peer),
                        name="harness-serve-socket-conn",
                        daemon=True,
                    ).start()
                except BaseException as exc:  # noqa: BLE001 - reported, never raised out
                    with self._lock:
                        self._accept_errors += 1
                    self._emit_log(
                        {
                            "event": "serve_socket_accept_error",
                            "phase": "spawn",
                            "reason": type(exc).__name__,
                        }
                    )
                    try:
                        sock.close()
                    except OSError:
                        pass
                    time.sleep(0.05)
                    continue
        except BaseException as exc:  # noqa: BLE001 - reported, never raised out
            outcome = f"error:{type(exc).__name__}"
            with self._lock:
                self._accept_errors += 1
        finally:
            # This thread is the only one that ever selects on the read end, so
            # it is the only one that may close it: closing it from ``close()``
            # would free a descriptor out from under a live ``select``.
            self._close_wake_read()
            with self._lock:
                self._accept_loop_exited = outcome
            self._emit_log(
                {"event": "serve_socket_accept_loop_exit", "outcome": outcome}
            )

    def _serve_connection(self, sock: socket.socket, peer: Any) -> None:
        with self._lock:
            self._next_connection += 1
            key = f"conn-{self._next_connection}"
            at_capacity = len(self._connections) >= self._max_connections
            pending_full = self._pending >= self._max_pending
            admitted = not (at_capacity or pending_full)
            if admitted:
                self._pending += 1
                self._pending_peak = max(self._pending_peak, self._pending)
        connection = SocketConnection(
            key=key,
            sock=sock,
            peer=_peer_text(peer),
            connected_at=_now_iso(),
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
        reader: "_LineReader | None" = None
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
                wrapped = self._wrap_tls(sock)
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
                self._reject(connection, REJECT_TOO_MANY_CONNECTIONS)
                return
            if pending_full:
                # The bound that did not exist: 64 peers that said nothing sat
                # on 64 threads because only AUTHENTICATED connections counted.
                self._reject(connection, REJECT_TOO_MANY_PENDING)
                return
            if self._rate_limiter.blocked():
                self._reject(connection, REJECT_RATE_LIMITED)
                return
            if self._timeout_limiter.blocked():
                self._reject(connection, REJECT_HANDSHAKE_THROTTLED)
                return
            if self._draining:
                self._reject(connection, REJECT_DRAINING)
                return
            try:
                reader = self._handshake(connection, sock, key)
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
                    self._reject(connection, REJECT_HELLO_MALFORMED)
                except Exception:
                    connection.close("handshake_failed")
        finally:
            if admitted:
                with self._lock:
                    self._pending = max(0, self._pending - 1)
        if reader is None:
            return
        self._read_loop(connection, reader)

    def _handshake(
        self, connection: SocketConnection, sock: socket.socket, key: str
    ) -> "_LineReader | None":
        """Challenge, verify, admit. Returns the reader, or None on rejection.

        The SERVER speaks first — one ``server_hello`` carrying a nonce minted
        for THIS connection — and the client answers with an HMAC over it. The
        token never appears on the wire in either direction, so a captured
        transcript authenticates nothing and cannot be replayed: the next
        connection demands a proof over a different nonce.

        What an unauthenticated peer learns is deliberately bounded to the
        challenge itself (nonce, boot id, contract numbers, algorithm). No
        build, no runtime root, no answer to any op — the boot id is disclosed
        because a client must be able to tell "the service I was talking to
        restarted" from "a different service answered" BEFORE it commits to a
        handshake, and it is a per-boot random value that authorises nothing.
        """

        reader = _LineReader(sock)
        nonce = secrets.token_hex(NONCE_BYTES)
        try:
            connection.emit(
                {
                    "event": "server_hello",
                    "nonce": nonce,
                    "boot_id": self._boot_id,
                    "contract": self._frame_contract,
                    "hello_contract": HELLO_CONTRACT_VERSION,
                    "algorithm": HELLO_PROOF_ALGORITHM,
                }
            )
        except Exception:
            connection.close("server_hello_write_failed")
            return None
        try:
            hello_line = reader.read_line(deadline_seconds=self._hello_deadline)
        except _LineTooLong:
            # A peer that FLOODED is not a peer that was silent. Charging this
            # to the timeout throttle accounted an attack as an absence, and
            # let it consume the budget reserved for genuinely quiet clients.
            self._reject(connection, REJECT_HELLO_TOO_LONG)
            return None
        except Exception:
            hello_line = None
        if hello_line is None:
            # NOT an auth failure: a peer that said nothing presented no
            # credential to be wrong about. It gets its own throttle instead,
            # so silence can still be bounded without locking out clients that
            # hold the right secret.
            with self._lock:
                self._hello_timeouts += 1
            self._timeout_limiter.record_failure()
            self._reject(connection, REJECT_HELLO_TIMEOUT)
            return None
        message = _parse_object(hello_line)
        if message is None:
            self._reject(connection, REJECT_HELLO_MALFORMED)
            return None
        if message.get("op") != "hello":
            self._reject(connection, REJECT_HELLO_REQUIRED)
            return None
        # `self._port` — what this server actually listens on — never a value
        # from the peer's frame, which is the whole point of the binding.
        outcome = self._authenticate_hello(message, nonce, self._port or 0)
        if not outcome.ok:
            # ONE typed frame, and nothing else: a rejected connection never
            # learns anything about the runtime it failed to reach. On the
            # gateway lane every credential failure — no device named, unknown
            # id, revoked row, wrong proof — collapses into this single reason,
            # so a peer cannot map which device ids exist by watching it change.
            self._reject(connection, outcome.reject_reason)
            return None
        connection.device_id = outcome.device_id
        connection.device_tier = outcome.device_tier
        connection.pairing_token = outcome.issued_token
        connection.peer_install_id = outcome.peer_install_id
        connection.peer_secret = outcome.issued_peer_secret
        connection.peer_secret_expires_at = outcome.issued_peer_secret_expires_at
        self._rate_limiter.record_success()
        # Symmetry the first pass missed: a completed handshake proves the lane
        # is reachable and answering, so the SILENCE throttle has nothing left
        # to protect against either. Cleared only by time, a burst of abandoned
        # connections went on refusing the client holding the right credential —
        # the same "the server's own state locks out a good client" shape the
        # auth limiter was given `record_success` to retire.
        self._timeout_limiter.record_success()
        connection.client = _client_text(message.get("client"))
        connection.client_build = _client_text(message.get("client_build"))
        connection.authenticated = True
        with self._lock:
            self._connections[key] = connection
            self._accepted += 1
        try:
            sock.settimeout(self._io_timeout)
        except OSError:
            pass
        open_log: dict[str, Any] = {
            "event": "serve_socket_connection_open",
            "connection": key,
            "client": connection.client,
            "client_build": connection.client_build,
            "peer": connection.peer,
        }
        if connection.device_id is not None:
            # Additive on a gateway row only, so every existing consumer of this
            # line reads the shape it was written against. A device id is the
            # one thing that makes a remote connection auditable after the fact;
            # the credential that proved it appears here as it appears
            # everywhere else, which is nowhere.
            open_log["transport"] = self._transport_name
            open_log["device_id"] = connection.device_id
            open_log["device_tier"] = connection.device_tier
        if connection.peer_install_id is not None:
            # The peer half of the same line, and the reason is the same one:
            # an install id is what makes a cross-install connection auditable
            # after the fact. The credential that proved it appears here as it
            # appears everywhere else, which is nowhere.
            open_log["transport"] = self._transport_name
            open_log["peer_install_id"] = connection.peer_install_id
        self._emit_log(open_log)
        try:
            connection.emit(self._hello_payload(message, connection))
        except Exception:
            self._drop_connection(connection, reason="hello_write_failed")
            return None
        return reader

    def _authenticate_hello(
        self, message: dict[str, Any], nonce: str, port: int
    ) -> HelloAuthOutcome:
        """Who is this? The per-root token by default; a device when injected.

        The DEFAULT arm is the loopback lane's original code, moved and not
        rewritten: read this root's shared secret, recompute the proof over the
        nonce and the listening port, compare in constant time. A server built
        with no ``authenticator`` therefore behaves byte-for-byte as it did
        before this seam existed, which is the invariant Stage 1 owes the local
        launcher and the CLI.

        An authenticator that RAISES is a refusal, never an admission. The
        gateway lane's reads a store off disk on a path an unauthenticated peer
        drives, so the failure is ordinary rather than exotic — and the one
        answer that must never come out of an exception handler here is "yes".
        """

        if self._authenticator is not None:
            try:
                outcome = self._authenticator(message, nonce, port)
            except Exception:
                with self._lock:
                    self._handshake_errors += 1
                    self._last_handshake_error = "authenticator_failed"
                return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
            if not isinstance(outcome, HelloAuthOutcome):  # pragma: no cover
                return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
            return outcome
        try:
            token = self._token_provider()
        except Exception:
            token = None
        ok = verify_hello_proof(message.get("proof"), nonce, token, port=port)
        del token
        return HelloAuthOutcome(ok=ok, reject_reason=REJECT_BAD_PROOF)

    def _wrap_tls(self, sock: socket.socket) -> Any | None:
        """Server-side TLS handshake. Returns the wrapped socket, or ``None``.

        Never raises: a peer that cannot speak TLS — a port scanner, a browser,
        a client that has not been told this lane is encrypted — is an ordinary
        event on a listener bound beyond loopback, and an exception escaping
        here would land on the pre-auth path the module docstring says must have
        no uncaught calls on it.

        The raw socket is closed by the caller's rejection path; this only
        reports.
        """

        try:
            return self._ssl_context.wrap_socket(sock, server_side=True)
        except Exception:
            return None

    def _read_loop(self, connection: SocketConnection, reader: "_LineReader") -> None:
        reason = "client_disconnect"
        try:
            while not self._stop.is_set() and not connection.closed:
                try:
                    line = reader.read_line(deadline_seconds=None)
                except socket.timeout:  # noqa: UP041 - alias differs across versions
                    continue
                except OSError as exc:
                    reason = f"read_error:{type(exc).__name__}"
                    break
                if line is None:
                    break
                if not line.strip():
                    continue
                try:
                    self._dispatch_line(line, connection)
                except Exception as exc:  # a handler fault is not a process fault
                    self._emit_log(
                        {
                            "event": "serve_socket_dispatch_error",
                            "connection": connection.key,
                            "client": connection.client,
                            "reason": type(exc).__name__,
                        }
                    )
        except _LineTooLong:
            reason = "line_too_long"
        finally:
            self._drop_connection(connection, reason=reason)

    # ── connection teardown / rejection ─────────────────────────────────────

    def _reject(self, connection: SocketConnection, reason: str) -> None:
        """Refuse one connection, typed, and charge the RIGHT counter.

        Whether this counts as an authentication failure is derived from the
        reason (:data:`AUTH_FAILURE_REJECT_REASONS`) and from nothing else. It
        used to be a boolean the caller passed, defaulting to True, so capacity
        and drain refusals were charged as attacks — and a ``rate_limited``
        refusal re-armed the very window that produced it. That is a permanent,
        self-sustaining lockout: proven live, 12 polite retries with the RIGHT
        credential over 12 seconds, never recovering. A refusal caused by the
        SERVER's own state can never extend a block against the client.
        """

        if reason in AUTH_FAILURE_REJECT_REASONS:
            self._rate_limiter.record_failure()
        with self._lock:
            self._rejected += 1
            self._rejected_by_reason[reason] = (
                self._rejected_by_reason.get(reason, 0) + 1
            )
        connection.try_emit({"event": "hello_rejected", "reason": reason})
        self._emit_log(
            {
                "event": "serve_socket_connection_rejected",
                "connection": connection.key,
                "client": connection.client,
                "peer": connection.peer,
                "reason": reason,
            }
        )
        if self._reject_penalty > 0:
            # Charged here, on the rejected connection's own thread — the accept
            # loop stays responsive for legitimate clients.
            time.sleep(self._reject_penalty)
        # Lingering close: a rejected client has almost always pipelined its
        # next op already, and closing on top of that unread data would RST the
        # connection and can destroy the rejection frame in flight. The typed
        # reason IS the observability of an auth failure; losing it would leave
        # the peer with an unexplained disconnect.
        connection.close(reason, linger_seconds=_REJECT_LINGER_SECONDS)

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

    def _close_listener(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        # WAKE FIRST, then close. The wakeup is what actually ends the accept
        # loop; ``listener.close()`` is only what stops the port answering.
        # Ordering them the other way would leave a window where the loop woke
        # on a listener it could still read ``self._listener`` as live.
        self._signal_wakeup()
        try:
            listener.close()
        except OSError:
            pass

    def _signal_wakeup(self) -> None:
        """Tell the accept loop to look again, then hand it a permanent EOF.

        One byte covers the loop already waiting; closing the write end covers
        the loop that has not reached ``select`` yet, because a read end at EOF
        stays readable forever. Both halves matter: without the second, a loop
        that woke, read the byte and looped would park again.
        """

        wake, self._wake_write = self._wake_write, None
        if wake is None:
            return
        try:
            wake.send(b"\x00")
        except OSError:
            pass
        try:
            wake.close()
        except OSError:
            pass

    def _close_wake_read(self) -> None:
        wake, self._wake_read = self._wake_read, None
        if wake is None:
            return
        try:
            wake.close()
        except OSError:
            pass

    def _emit_log(self, payload: dict[str, Any]) -> None:
        if self._log is None:
            return
        try:
            self._log({"boot_id": self._boot_id, **payload})
        except Exception:  # pragma: no cover - an instrument may not raise
            pass
