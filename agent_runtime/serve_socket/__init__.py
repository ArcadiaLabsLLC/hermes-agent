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
handshake   lanes   TLS wrap, the hello, authentication, rejection, read loop
admit       lanes   ``ConnectionAdmitter``: admit, dispatch, drain, close — no listener
server      lanes   ``ServeSocketServer``: bind and accept, on top of the admitter
client      lanes   ``ServeSocketClient``
cli_route   lanes   ``relay_argv``: one CLI argv relay, the typed ``RelayOutcome``,
                    the one fallback rule (``FallbackPolicy``)
==========  ======  ========================================================

Stores written: ``<runtime_root>/<SOCKET_LOCK_FILENAME>`` and
``<SOCKET_OWNER_FILENAME>`` (``owner_lock`` only). The protocol (hello v3,
reject reasons, drain, TLS pin) is documented once, in
``docs/agent-runtime-harness/03-transport-and-wire.md`` § "The socket lane".
"""

from __future__ import annotations

from typing import Any

#: Every exported name and the family it lives in. Resolved on first use (PEP 562), so
#: importing one family never imports the rest: a phone ships the admit, handshake and
#: client families of this package and not the listener or the owner lock
#: (``bundled-phone.yaml``, review w1118a.79).
_EXPORTS: dict[str, str] = {
    "AUTH_FAILURE_REJECT_REASONS": "vocabulary",
    "DEFAULT_MAX_CONNECTIONS": "vocabulary",
    "DEFAULT_MAX_PENDING_CONNECTIONS": "vocabulary",
    "HELLO_FAILURE_LIMIT": "vocabulary",
    "HELLO_FAILURE_WINDOW_SECONDS": "vocabulary",
    "HELLO_PROOF_ALGORITHM": "vocabulary",
    "MAX_LINE_BYTES": "vocabulary",
    "NONCE_BYTES": "vocabulary",
    "REJECT_BAD_PROOF": "vocabulary",
    "REJECT_DRAINING": "vocabulary",
    "REJECT_EXTERNAL_ACCESS_OFF": "vocabulary",
    "REJECT_HANDSHAKE_THROTTLED": "vocabulary",
    "REJECT_HELLO_MALFORMED": "vocabulary",
    "REJECT_HELLO_REQUIRED": "vocabulary",
    "REJECT_HELLO_TIMEOUT": "vocabulary",
    "REJECT_HELLO_TOO_LONG": "vocabulary",
    "REJECT_RATE_LIMITED": "vocabulary",
    "REJECT_TLS_HANDSHAKE_FAILED": "vocabulary",
    "REJECT_TOO_MANY_CONNECTIONS": "vocabulary",
    "REJECT_TOO_MANY_PENDING": "vocabulary",
    "SOCKET_HOST": "vocabulary",
    "SOCKET_LOCK_DRAIN_POLL_SECONDS": "vocabulary",
    "SOCKET_LOCK_DRAIN_WAIT_SECONDS": "vocabulary",
    "SOCKET_LOCK_FILENAME": "vocabulary",
    "SOCKET_OWNER_FILENAME": "vocabulary",
    "SocketLockResult": "owner_lock",
    "SocketOwnerLock": "owner_lock",
    "read_socket_owner": "owner_lock",
    "socket_lock_path": "owner_lock",
    "socket_owner_path": "owner_lock",
    "HELLO_CONTRACT_VERSION": "hello",
    "HelloAuthOutcome": "hello",
    "HelloRateLimiter": "hello",
    "ServeCertificatePinMismatch": "hello",
    "ServeHelloProtocolError": "hello",
    "hello_proof": "hello",
    "verify_hello_proof": "hello",
    "ServeSocketServer": "server",
    "CLASSIFICATION_OWNER_FILE_UNVERIFIED": "target",
    "SocketTarget": "target",
    "resolve_socket_target": "target",
    "ServeSocketClient": "client",
}

#: The families, importable as attributes of the package as before.
_FAMILIES = frozenset({"vocabulary", "owner_lock", "hello", "connection", "server", "admit",
                       "handshake", "target", "client", "cli_route", "wire"})


def __getattr__(name: str) -> Any:
    from importlib import import_module

    if name in _FAMILIES:
        return import_module(f"{__name__}.{name}")
    family = _EXPORTS.get(name)
    if family is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{family}"), name)


__layer__ = "lanes"

__all__ = [
    "AUTH_FAILURE_REJECT_REASONS",
    "CLASSIFICATION_OWNER_FILE_UNVERIFIED",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_PENDING_CONNECTIONS",
    "HELLO_CONTRACT_VERSION",
    "HELLO_FAILURE_LIMIT",
    "HELLO_FAILURE_WINDOW_SECONDS",
    "HELLO_PROOF_ALGORITHM",
    "MAX_LINE_BYTES",
    "NONCE_BYTES",
    "REJECT_BAD_PROOF",
    "REJECT_DRAINING",
    "REJECT_EXTERNAL_ACCESS_OFF",
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
    "HelloAuthOutcome",
    "HelloRateLimiter",
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
