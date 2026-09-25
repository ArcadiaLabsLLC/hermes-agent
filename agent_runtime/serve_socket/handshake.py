"""The handshake half of ``ServeSocketServer``: TLS wrap, the mandatory hello,
authentication, the typed rejection, and the post-hello read loop.

Functions that take the server rather than methods on it: the server owns the
listener, the connection table and the counters; this module owns the protocol
steps a single accepted socket walks. Split out so ``server`` reads as the
lifecycle (bind, accept, admit, drain, close) and this file as the wire.
"""

from __future__ import annotations

import secrets
import socket
import time
from typing import TYPE_CHECKING, Any

from agent_runtime.serve_socket.vocabulary import (
    AUTH_FAILURE_REJECT_REASONS,
    HELLO_PROOF_ALGORITHM,
    NONCE_BYTES,
    REJECT_BAD_PROOF,
    REJECT_HELLO_MALFORMED,
    REJECT_HELLO_REQUIRED,
    REJECT_HELLO_TIMEOUT,
    REJECT_HELLO_TOO_LONG,
    _REJECT_LINGER_SECONDS,
)
from agent_runtime.serve_socket.hello import (
    HELLO_CONTRACT_VERSION,
    HelloAuthOutcome,
    verify_hello_proof,
)
from agent_runtime.serve_socket.connection import SocketConnection
from agent_runtime.serve_socket.wire import _LineReader, _LineTooLong, _client_text, _parse_object

__layer__ = "lanes"

__all__ = ["handshake", "authenticate_hello", "wrap_tls", "read_loop", "reject"]

if TYPE_CHECKING:
    from agent_runtime.serve_socket.server import ServeSocketServer


def handshake(
    server: ServeSocketServer, connection: SocketConnection, sock: socket.socket, key: str
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
                "boot_id": server._boot_id,
                "contract": server._frame_contract,
                "hello_contract": HELLO_CONTRACT_VERSION,
                "algorithm": HELLO_PROOF_ALGORITHM,
            }
        )
    except Exception:
        connection.close("server_hello_write_failed")
        return None
    try:
        hello_line = reader.read_line(deadline_seconds=server._hello_deadline)
    except _LineTooLong:
        # A peer that FLOODED is not a peer that was silent. Charging this
        # to the timeout throttle accounted an attack as an absence, and
        # let it consume the budget reserved for genuinely quiet clients.
        reject(server, connection, REJECT_HELLO_TOO_LONG)
        return None
    except Exception:
        hello_line = None
    if hello_line is None:
        # NOT an auth failure: a peer that said nothing presented no
        # credential to be wrong about. It gets its own throttle instead,
        # so silence can still be bounded without locking out clients that
        # hold the right secret.
        with server._lock:
            server._hello_timeouts += 1
        server._timeout_limiter.record_failure()
        reject(server, connection, REJECT_HELLO_TIMEOUT)
        return None
    message = _parse_object(hello_line)
    if message is None:
        reject(server, connection, REJECT_HELLO_MALFORMED)
        return None
    if message.get("op") != "hello":
        reject(server, connection, REJECT_HELLO_REQUIRED)
        return None
    # `server._port` — what this server actually listens on — never a value
    # from the peer's frame, which is the whole point of the binding.
    outcome = authenticate_hello(server, message, nonce, server._port or 0)
    if not outcome.ok:
        # ONE typed frame, and nothing else: a rejected connection never
        # learns anything about the runtime it failed to reach. On the
        # gateway lane every credential failure — no device named, unknown
        # id, revoked row, wrong proof — collapses into this single reason,
        # so a peer cannot map which device ids exist by watching it change.
        reject(server, connection, outcome.reject_reason)
        return None
    connection.device_id = outcome.device_id
    connection.device_tier = outcome.device_tier
    connection.pairing_token = outcome.issued_token
    connection.peer_install_id = outcome.peer_install_id
    connection.peer_secret = outcome.issued_peer_secret
    connection.peer_secret_expires_at = outcome.issued_peer_secret_expires_at
    server._rate_limiter.record_success()
    # Symmetry the first pass missed: a completed handshake proves the lane
    # is reachable and answering, so the SILENCE throttle has nothing left
    # to protect against either. Cleared only by time, a burst of abandoned
    # connections went on refusing the client holding the right credential —
    # the same "the server's own state locks out a good client" shape the
    # auth limiter was given `record_success` to retire.
    server._timeout_limiter.record_success()
    connection.client = _client_text(message.get("client"))
    connection.client_build = _client_text(message.get("client_build"))
    connection.authenticated = True
    with server._lock:
        server._connections[key] = connection
        server._accepted += 1
    try:
        sock.settimeout(server._io_timeout)
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
        open_log["transport"] = server._transport_name
        open_log["device_id"] = connection.device_id
        open_log["device_tier"] = connection.device_tier
    if connection.peer_install_id is not None:
        # The peer half of the same line, and the reason is the same one:
        # an install id is what makes a cross-install connection auditable
        # after the fact. The credential that proved it appears here as it
        # appears everywhere else, which is nowhere.
        open_log["transport"] = server._transport_name
        open_log["peer_install_id"] = connection.peer_install_id
    server._emit_log(open_log)
    try:
        connection.emit(server._hello_payload(message, connection))
    except Exception:
        server._drop_connection(connection, reason="hello_write_failed")
        return None
    return reader


def authenticate_hello(
    server: ServeSocketServer, message: dict[str, Any], nonce: str, port: int
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

    if server._authenticator is not None:
        try:
            outcome = server._authenticator(message, nonce, port)
        except Exception:
            with server._lock:
                server._handshake_errors += 1
                server._last_handshake_error = "authenticator_failed"
            return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
        if not isinstance(outcome, HelloAuthOutcome):  # pragma: no cover
            return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
        return outcome
    try:
        token = server._token_provider()
    except Exception:
        token = None
    ok = verify_hello_proof(message.get("proof"), nonce, token, port=port)
    del token
    return HelloAuthOutcome(ok=ok, reject_reason=REJECT_BAD_PROOF)


def wrap_tls(
server: ServeSocketServer, sock: socket.socket) -> Any | None:
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
        return server._ssl_context.wrap_socket(sock, server_side=True)
    except Exception:
        return None


def read_loop(
server: ServeSocketServer, connection: SocketConnection, reader: "_LineReader") -> None:
    reason = "client_disconnect"
    try:
        while not server._stop.is_set() and not connection.closed:
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
                server._dispatch_line(line, connection)
            except Exception as exc:  # a handler fault is not a process fault
                server._emit_log(
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
        server._drop_connection(connection, reason=reason)


def reject(
server: ServeSocketServer, connection: SocketConnection, reason: str) -> None:
    """Refuse one connection, typed, and charge the RIGHT counter.

    Whether this counts as an authentication failure is derived from the
    reason (:data:`AUTH_FAILURE_REJECT_REASONS`) and from nothing else. It
    used to be a boolean the caller passed, defaulting to True, so capacity
    and drain refusals were charged as attacks — and a ``rate_limited``
    refusal re-armed the very window that produced it. That is a permanent,
    server-sustaining lockout: proven live, 12 polite retries with the RIGHT
    credential over 12 seconds, never recovering. A refusal caused by the
    SERVER's own state can never extend a block against the client.
    """

    if reason in AUTH_FAILURE_REJECT_REASONS:
        server._rate_limiter.record_failure()
    with server._lock:
        server._rejected += 1
        server._rejected_by_reason[reason] = (
            server._rejected_by_reason.get(reason, 0) + 1
        )
    connection.try_emit({"event": "hello_rejected", "reason": reason})
    server._emit_log(
        {
            "event": "serve_socket_connection_rejected",
            "connection": connection.key,
            "client": connection.client,
            "peer": connection.peer,
            "reason": reason,
        }
    )
    if server._reject_penalty > 0:
        # Charged here, on the rejected connection's own thread — the accept
        # loop stays responsive for legitimate clients.
        time.sleep(server._reject_penalty)
    # Lingering close: a rejected client has almost always pipelined its
    # next op already, and closing on top of that unread data would RST the
    # connection and can destroy the rejection frame in flight. The typed
    # reason IS the observability of an auth failure; losing it would leave
    # the peer with an unexplained disconnect.
    connection.close(reason, linger_seconds=_REJECT_LINGER_SECONDS)
