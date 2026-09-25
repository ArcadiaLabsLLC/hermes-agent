"""The socket lane — one durable, multi-client serve per runtime root (the package map, rule 16).

Entry points (what calls in):

* ``server.ServeSocketServer`` — the serve boot binds and runs it
  (``harness_parts.serve.subscriptions``); ``owner_lock.SocketOwnerLock`` decides
  which serve may.
* ``client.ServeSocketClient`` / ``target.resolve_socket_target`` — every client
  (``serve connect``, ``media_proxy``, ``tools.agent_chat_dispatch``, peers).
* ``hello`` — the proof and the typed outcome the gateway authenticator
  (``serve_gateway_credentials``) returns.

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  ========================================================
module      layer   owns
==========  ======  ========================================================
vocabulary  models  limits, the hello contract version, ``REJECT_*``, owner states
wire        models  line framing, JSON/text coercion, the reached-at stamp
hello       policy  rate limiter, proof, ``HelloAuthOutcome``, hello errors
owner_lock  stores  the one-owner lock, owner record, drain wait (byte locks:
                    ``agent_runtime.file_locks``)
connection  stores  ``SocketConnection``
target      stores  ``SocketTarget``, ``resolve_socket_target``
server      lanes   ``ServeSocketServer``: bind, accept, admit, drain, close
handshake   lanes   TLS wrap, the hello, authentication, rejection, read loop
client      lanes   ``ServeSocketClient``
==========  ======  ========================================================

Stores written: ``<runtime_root>/<SOCKET_LOCK_FILENAME>`` and
``<SOCKET_OWNER_FILENAME>`` (``owner_lock`` only). The protocol (hello v3,
reject reasons, drain, TLS pin) is documented once, in
``docs/agent-runtime-harness/03-transport-and-wire.md`` § "The socket lane".
"""

from __future__ import annotations

from agent_runtime.serve_socket import (  # noqa: F401 — every family, in the original definition order
    vocabulary,
    owner_lock,
    hello,
    connection,
    server,
    target,
    client,
    wire,
)
from agent_runtime.serve_socket.vocabulary import (
    AUTH_FAILURE_REJECT_REASONS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_PENDING_CONNECTIONS,
    HELLO_FAILURE_LIMIT,
    HELLO_FAILURE_WINDOW_SECONDS,
    HELLO_PROOF_ALGORITHM,
    MAX_LINE_BYTES,
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
    SOCKET_LOCK_DRAIN_POLL_SECONDS,
    SOCKET_LOCK_DRAIN_WAIT_SECONDS,
    SOCKET_LOCK_FILENAME,
    SOCKET_OWNER_FILENAME,
)
from agent_runtime.serve_socket.owner_lock import (
    SocketLockResult,
    SocketOwnerLock,
    read_socket_owner,
    socket_lock_path,
    socket_owner_path,
)
from agent_runtime.serve_socket.hello import (
    HELLO_CONTRACT_VERSION,
    HelloAuthOutcome,
    HelloRateLimiter,
    ServeCertificatePinMismatch,
    ServeHelloProtocolError,
    hello_proof,
    verify_hello_proof,
)
from agent_runtime.serve_socket.server import ServeSocketServer
from agent_runtime.serve_socket.target import (
    CLASSIFICATION_OWNER_FILE_UNVERIFIED,
    SocketTarget,
    resolve_socket_target,
)
from agent_runtime.serve_socket.client import ServeSocketClient

__layer__ = "wiring"

__all__ = [
    "AUTH_FAILURE_REJECT_REASONS",
    "CLASSIFICATION_OWNER_FILE_UNVERIFIED",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_PENDING_CONNECTIONS",
    "HELLO_CONTRACT_VERSION",
    "HELLO_FAILURE_LIMIT",
    "HELLO_FAILURE_WINDOW_SECONDS",
    "HELLO_PROOF_ALGORITHM",
    "HelloAuthOutcome",
    "HelloRateLimiter",
    "MAX_LINE_BYTES",
    "NONCE_BYTES",
    "REJECT_BAD_PROOF",
    "REJECT_DRAINING",
    "REJECT_HANDSHAKE_THROTTLED",
    "REJECT_HELLO_MALFORMED",
    "REJECT_HELLO_REQUIRED",
    "REJECT_HELLO_TIMEOUT",
    "REJECT_HELLO_TOO_LONG",
    "REJECT_RATE_LIMITED",
    "REJECT_TLS_HANDSHAKE_FAILED",
    "REJECT_TOO_MANY_CONNECTIONS",
    "REJECT_TOO_MANY_PENDING",
    "SOCKET_HOST",
    "SOCKET_LOCK_DRAIN_POLL_SECONDS",
    "SOCKET_LOCK_DRAIN_WAIT_SECONDS",
    "SOCKET_LOCK_FILENAME",
    "SOCKET_OWNER_FILENAME",
    "ServeCertificatePinMismatch",
    "ServeHelloProtocolError",
    "ServeSocketClient",
    "ServeSocketServer",
    "SocketLockResult",
    "SocketOwnerLock",
    "SocketTarget",
    "hello_proof",
    "read_socket_owner",
    "resolve_socket_target",
    "socket_lock_path",
    "socket_owner_path",
    "verify_hello_proof",
]
