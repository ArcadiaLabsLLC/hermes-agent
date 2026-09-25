"""Every constant of the socket lane: the loopback host, the lock/owner filenames,
connection and hello limits, the hello contract version, the ``REJECT_*``
vocabulary, budgets and timeouts, lock outcomes and owner states.

A leaf: it imports nothing from the package, so every other module (and
``core_cache``'s module-level read of the two filenames) reads it without a
cycle. The protocol these constants serve is documented in
``docs/agent-runtime-harness/03-transport-and-wire.md`` § "The socket lane".
"""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"

__all__ = [
    "LockOutcome",
    "RejectReason",
    "AUTH_FAILURE_REJECT_REASONS",
    "BROADCAST_BUDGET_SECONDS",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_PENDING_CONNECTIONS",
    "HELLO_DEADLINE_SECONDS",
    "HELLO_FAILURE_LIMIT",
    "HELLO_FAILURE_WINDOW_SECONDS",
    "HELLO_PROOF_ALGORITHM",
    "HELLO_REJECT_PENALTY_SECONDS",
    "HELLO_TIMEOUT_LIMIT",
    "HELLO_TIMEOUT_WINDOW_SECONDS",
    "IO_TIMEOUT_SECONDS",
    "LOCK_OUTCOME_ACQUIRED",
    "LOCK_OUTCOME_HELD",
    "MAX_LINE_BYTES",
    "NONCE_BYTES",
    "OWNER_STATE_ABSENT",
    "OWNER_STATE_DEAD",
    "OWNER_STATE_LIVE",
    "OWNER_STATE_LIVENESS_UNKNOWN",
    "OWNER_STATE_MALFORMED",
    "OWNER_STATE_PID_MISSING",
    "OWNER_STATE_SELF",
    "OWNER_STATE_UNREADABLE",
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
    "SOCKET_OWNER_DRAINING_KEY",
    "SOCKET_OWNER_FILENAME",
    "_REJECT_LINGER_SECONDS",
]


#: The LOOPBACK lane's host. Never configurable, and the sentence that follows
#: is unchanged from the day it was written: a knob HERE can only ever widen
#: exposure, and this runtime executes agents with tools.
#:
#: Stage 1 did not turn this into a knob. It added a SECOND listener — off by
#: default, per-config, TLS-wrapped, and accepting only per-device credentials —
#: precisely so that widening exposure is a different object with a different
#: credential story rather than a different value in this constant. A caller
#: that reads ``SOCKET_HOST`` is asking about the local lane and still gets the
#: local answer.
SOCKET_HOST = "127.0.0.1"


SOCKET_LOCK_FILENAME = "serve_socket.lock"


SOCKET_OWNER_FILENAME = "serve_socket.owner.json"


#: Connections a single serve will hold. A durable service is meant to be
#: multi-client, not unbounded: every connection costs a reader thread, and an
#: unbounded accept loop is a local denial of service against the runtime.
DEFAULT_MAX_CONNECTIONS = 32


#: Connections that have been accepted but have not yet PROVEN anything. Kept
#: small and counted SEPARATELY from the authenticated pool, because the
#: authenticated pool is the wrong bound for the pre-auth phase: with capacity
#: measured against authenticated peers only, 64 sockets that never said hello
#: sat on 64 threads and drew not one rejection. A peer that has proven nothing
#: gets a handshake deadline and one of these slots, and no more.
DEFAULT_MAX_PENDING_CONNECTIONS = 8


#: Failed hellos tolerated inside the window before every new connection is
#: rejected outright. The secret is 256 bits, so this is not what makes guessing
#: infeasible — it is what stops a local process from spending the runtime's
#: threads and log volume trying.
HELLO_FAILURE_LIMIT = 5


HELLO_FAILURE_WINDOW_SECONDS = 10.0


#: The SEPARATE, non-auth throttle for peers that connect and then say nothing.
#: A silent peer is not an authentication failure and must never be charged to
#: the auth limiter (that is what made the lockout self-sustaining), but it is
#: still a way to spend the runtime's threads, so it has its own bound.
HELLO_TIMEOUT_LIMIT = 16


HELLO_TIMEOUT_WINDOW_SECONDS = 10.0


#: Challenge size. 32 bytes → 64 hex characters, fresh per CONNECTION.
NONCE_BYTES = 32


HELLO_PROOF_ALGORITHM = "hmac-sha256"


#: Typed rejection reasons. The reason IS the classification: whether a
#: rejection counts against the auth rate limiter is derived from it below,
#: never from a boolean the caller passes in (a caller-supplied flag is exactly
#: how capacity refusals came to be charged as auth failures).
class RejectReason(StrEnum):
    """Every ``hello_rejected`` reason: part of the hello contract (rule 14).

    A client branches on the reason, so the set is closed here and every
    refusal site reads a member. ``StrEnum`` members ARE their strings on the
    wire, so the frames are byte-identical to the free strings they replace.
    """

    TOO_MANY_CONNECTIONS = "too_many_connections"
    TOO_MANY_PENDING = "too_many_pending"
    RATE_LIMITED = "rate_limited"
    HANDSHAKE_THROTTLED = "handshake_throttled"
    DRAINING = "draining"
    HELLO_TIMEOUT = "hello_timeout"
    HELLO_REQUIRED = "hello_required"
    HELLO_MALFORMED = "hello_malformed"
    HELLO_TOO_LONG = "hello_too_long"
    BAD_PROOF = "bad_proof"

    #: The peer could not complete TLS. Only reachable on a listener configured with
    #: an ``ssl_context`` (the gateway lane); the loopback lane never mints it.
    #:
    #: NOT an auth failure — a TLS failure says nothing about whether the peer holds
    #: a credential, and charging it to the auth limiter is the same mistake that
    #: made capacity refusals self-sustaining. It IS a way to spend the runtime's
    #: threads, so it charges the SILENCE throttle instead, alongside the peer that
    #: connects and says nothing: from the accept loop's point of view a half-open
    #: TLS handshake is exactly that.
    TLS_HANDSHAKE_FAILED = "tls_handshake_failed"


#: The module-level names every importer and test reads — aliases of the members.
REJECT_TOO_MANY_CONNECTIONS = RejectReason.TOO_MANY_CONNECTIONS
REJECT_TOO_MANY_PENDING = RejectReason.TOO_MANY_PENDING
REJECT_RATE_LIMITED = RejectReason.RATE_LIMITED
REJECT_HANDSHAKE_THROTTLED = RejectReason.HANDSHAKE_THROTTLED
REJECT_DRAINING = RejectReason.DRAINING
REJECT_HELLO_TIMEOUT = RejectReason.HELLO_TIMEOUT
REJECT_HELLO_REQUIRED = RejectReason.HELLO_REQUIRED
REJECT_HELLO_MALFORMED = RejectReason.HELLO_MALFORMED
REJECT_HELLO_TOO_LONG = RejectReason.HELLO_TOO_LONG
REJECT_BAD_PROOF = RejectReason.BAD_PROOF
REJECT_TLS_HANDSHAKE_FAILED = RejectReason.TLS_HANDSHAKE_FAILED


#: The ONLY reasons that charge the auth rate limiter: a peer that presented a
#: bad credential, or that spoke something other than a hello where a hello was
#: mandatory. Capacity, drain, timeout, and throttle refusals say nothing about
#: whether the peer holds the secret — and counting them made a blocked window
#: extend itself forever, so a well-behaved client with the RIGHT credential
#: could never recover.
AUTH_FAILURE_REJECT_REASONS = frozenset(
    {
        REJECT_BAD_PROOF,
        REJECT_HELLO_REQUIRED,
        REJECT_HELLO_MALFORMED,
        REJECT_HELLO_TOO_LONG,
    }
)


#: Total budget for one broadcast across every attached connection. A drain
#: announcement must not be summed over N wedged readers: worst case is now one
#: parked ``sendall`` (bounded by IO_TIMEOUT_SECONDS) plus this, instead of
#: N × IO_TIMEOUT. Skipped connections are counted and logged, never silent.
BROADCAST_BUDGET_SECONDS = 2.0


#: Charged to the REJECTED connection's own thread, never to the accept loop.
HELLO_REJECT_PENALTY_SECONDS = 0.25


#: How long a rejected connection half-closes and drains before the final close,
#: so the rejection frame survives (see ``SocketConnection.close``).
_REJECT_LINGER_SECONDS = 0.25


#: A connection that has not said hello by then is not a client.
HELLO_DEADLINE_SECONDS = 5.0


#: Socket timeout after the handshake. Receive timeouts are a normal idle lap;
#: a SEND timeout is fatal to that connection — a write that cannot land inside
#: this budget is a reader that has stopped reading, and a partially written
#: frame cannot be resynchronised.
IO_TIMEOUT_SECONDS = 10.0


#: Hard bound on a single client line. The ops are small JSON objects; anything
#: past this is a client streaming garbage at the runtime.
MAX_LINE_BYTES = 1 << 20


class LockOutcome(StrEnum):
    """What ``SocketOwnerLock.acquire`` answered (``SocketLockResult.outcome``)."""

    ACQUIRED = "acquired"
    HELD = "lock_held_by"


LOCK_OUTCOME_ACQUIRED = LockOutcome.ACQUIRED
LOCK_OUTCOME_HELD = LockOutcome.HELD


#: The key a LEAVING owner stamps on its sidecar at drain start (RS-3), and the
#: only thing that tells a contender "alive and leaving" apart from "alive and
#: serving". Both are a live pid holding the lock; only one of them is going to
#: let go.
SOCKET_OWNER_DRAINING_KEY = "draining_at"


#: How long a contender will wait for an owner it can PROVE is leaving (RS-4).
#: Derived from the launcher's drain deadline rather than chosen: its
#: ``drainDeadline`` in
#: `EterniaLauncher/lib/features/mission_control/data/mission_control_serve_session_io.dart`
#: is 20 s, so a bound below that would give up while the drain it is waiting
#: for is still legitimately running — which is the failure this exists to end.
#: The margin covers the exit that follows the deadline. Named ONCE, here,
#: because a second spelling of it is a second thing to keep in step with the
#: launcher.
SOCKET_LOCK_DRAIN_WAIT_SECONDS = 25.0


#: The retry cadence inside that bound. Short enough that the replacement's
#: ready frame is not visibly later than the release, long enough that the whole
#: wait is a hundred syscalls rather than tens of thousands.
SOCKET_LOCK_DRAIN_POLL_SECONDS = 0.25


#: What the PREVIOUS owner sidecar was, at the moment this process took (or
#: failed to take) the lock. Diagnostic only — it rides the log line and the
#: result object, never the greeting: a launcher decides on ``outcome`` plus
#: ``took_over_from``, and a fifth vocabulary on the wire would be a fifth thing
#: to keep true. ``OWNER_STATE_DEAD`` deliberately spells ``pid_not_running``,
#: the same word ``serve_registry.classify_serve_instance`` gives its
#: ``stale_dead_pid`` rows, because it is the same probe answering the same
#: question about the same process.
OWNER_STATE_ABSENT = "absent"
OWNER_STATE_UNREADABLE = "sidecar_unreadable"
OWNER_STATE_MALFORMED = "sidecar_malformed"
OWNER_STATE_PID_MISSING = "pid_missing"
OWNER_STATE_SELF = "self"
OWNER_STATE_DEAD = "pid_not_running"
OWNER_STATE_LIVE = "pid_running"
OWNER_STATE_LIVENESS_UNKNOWN = "liveness_unreadable"
