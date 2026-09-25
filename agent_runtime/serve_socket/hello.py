"""The hello handshake's policy half: the per-peer rate limiter, the protocol
and pin-mismatch errors, the HMAC proof (``hello_proof`` / ``verify_hello_proof``)
and the typed ``HelloAuthOutcome`` an authenticator returns — and
``HELLO_CONTRACT_VERSION``, the contract they implement (its own home, so the
contract-version authority gate keys it on a basename no other module shares).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from agent_runtime.serve_socket.vocabulary import (
    HELLO_FAILURE_LIMIT,
    HELLO_FAILURE_WINDOW_SECONDS,
    REJECT_BAD_PROOF,
)

__layer__ = "policy"

__all__ = [
    "HELLO_CONTRACT_VERSION",
    "HelloAuthOutcome",
    "HelloRateLimiter",
    "ServeCertificatePinMismatch",
    "ServeHelloProtocolError",
    "hello_proof",
    "verify_hello_proof",
]


#: The handshake version stamped on every ``server_hello``. Bumped from the
#: (implicit) token hello to the nonce/HMAC challenge-response; a client that
#: does not recognise this number must refuse to proceed rather than guess at
#: the frame it is expected to answer with.
#: 3 binds the proof to the listening PORT (see :func:`hello_proof`). Bumped
#: rather than shimmed: no client speaks this handshake yet, so the migration
#: cost is zero today and permanent the moment one does.
HELLO_CONTRACT_VERSION = 3


# ── hello rate limiting ──────────────────────────────────────────────────────


class HelloRateLimiter:
    """Sliding-window failure counter. Clock injected so it is unit-testable."""

    def __init__(
        self,
        *,
        limit: int = HELLO_FAILURE_LIMIT,
        window_seconds: float = HELLO_FAILURE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = max(1, int(limit))
        self._window = float(window_seconds)
        self._clock = clock
        self._failures: list[float] = []
        self._lock = threading.Lock()

    def blocked(self) -> bool:
        with self._lock:
            self._evict()
            return len(self._failures) >= self._limit

    def record_failure(self) -> int:
        with self._lock:
            self._evict()
            self._failures.append(self._clock())
            return len(self._failures)

    def record_success(self) -> None:
        """A good hello clears the window: this bounds abuse, not real clients."""

        with self._lock:
            self._failures.clear()

    def _evict(self) -> None:
        cutoff = self._clock() - self._window
        self._failures = [item for item in self._failures if item >= cutoff]


# ── the challenge-response proof ─────────────────────────────────────────────


class ServeHelloProtocolError(Exception):
    """The peer did not speak the handshake this contract requires.

    Carries the offending ``frame`` when there was one, because the two
    interesting cases look identical from a bare exception: a service that
    rejected us before the challenge (``hello_rejected``, and the reason is the
    answer), and something on the port that is not this service at all.
    """

    def __init__(self, detail: str, *, frame: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.frame = frame if isinstance(frame, dict) else None

    @property
    def reason(self) -> str | None:
        if self.frame is None:
            return None
        value = self.frame.get("reason")
        return value if isinstance(value, str) else None


class ServeCertificatePinMismatch(ServeHelloProtocolError):
    """The TLS peer presented a certificate the client did not pin.

    A SUBCLASS rather than a flag on the parent, and it exists for one caller:
    ``peers join``, which since R-D3 dials a LIST of candidate addresses and has
    to know which failures are worth moving past. A refused connection or a
    timeout says *this address*; a certificate that does not match the pinned
    fingerprint says *this identity*, and no other address in the list can make
    that come out differently — so the loop stops rather than offering the same
    wrong certificate three more chances to be accepted.

    Subclassing keeps every existing ``except ServeHelloProtocolError`` arm and
    every ``pytest.raises(ServeHelloProtocolError, match=...)`` true, and the
    message is unchanged: this names a condition that was already raised, it
    does not add one.
    """


def hello_proof(token: str, nonce: str, *, port: int) -> str:
    """``HMAC-SHA256(key=token, msg="v3|<port>|<nonce>")`` as lowercase hex.

    The ONE derivation in this stack: the client computes it, the server
    recomputes it, and a second copy of this line is how the two ends start
    disagreeing about what a proof is. The token is the KEY and never the
    message — a proof therefore reveals nothing about it, which is the whole
    point of not putting the token on the wire.

    **The proof is bound to the PORT, and that is what makes it unrelayable.**
    A fresh nonce stops a captured transcript from being replayed, but it does
    NOT stop a live relay: an impostor listener can dial the real service, take
    its nonce, present that same nonce as its own challenge, and forward the
    answer it receives. Every value in the ``server_hello`` frame is chosen by
    whoever sent it, so binding to `boot_id` would be bound to a number the
    impostor simply echoes. The port is different: each end takes it from its
    OWN socket — the server from what it listens on, the client from what it
    dialled — so a proof minted for the impostor's port cannot verify at the
    real one. Channel binding has to use something both ends know independently
    of anything the other one claims.
    """

    message = f"v{HELLO_CONTRACT_VERSION}|{int(port)}|{nonce}"
    return hmac.new(
        str(token).encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_hello_proof(
    presented: Any, nonce: str, token: str | None, *, port: int
) -> bool:
    """Constant-time check of *presented* against the proof this nonce demands.

    Fails CLOSED on every missing input — no token for this root, no proof in
    the hello, an empty nonce — because the alternative ("nothing configured,
    let everyone in") is the failure mode that turns a hardening into a bypass.
    """

    if not token or not nonce:
        return False
    if not isinstance(presented, str) or not presented.strip():
        return False
    # BYTES, never str. `hmac.compare_digest` RAISES TypeError when either str
    # operand is non-ASCII, and `presented` is attacker-controlled on a path no
    # credential is needed to reach: one accented character used to unwind out
    # of the handshake, so the peer got no rejection frame, the attempt was
    # never counted, the rate limiter was never charged, and the traceback was
    # written to a stderr that `serve_loop` has redirected onto the NDJSON
    # protocol stream. Encoding first makes a hostile proof merely wrong.
    return hmac.compare_digest(
        presented.strip().lower().encode("utf-8", "replace"),
        hello_proof(token, nonce, port=port).encode("ascii"),
    )


# ── who a hello turned out to be ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HelloAuthOutcome:
    """What an :class:`ServeSocketServer` authenticator decided about one hello.

    The seam that lets ONE listener implementation serve two credential models
    without either one growing a branch on the other. The loopback lane's
    authenticator checks the per-root token and returns no identity beyond
    "yes"; the gateway lane's checks a per-device credential and returns the
    device it belongs to.

    ``reject_reason`` is a member of the typed vocabulary above rather than free
    text, because ``_reject`` derives whether a refusal charges the auth rate
    limiter FROM the reason and from nothing else — a caller-supplied flag there
    is exactly how capacity refusals came to be counted as attacks.
    """

    ok: bool
    reject_reason: str = REJECT_BAD_PROOF
    #: Set only when ``ok`` and only by a device-credential authenticator, so a
    #: connection cannot be stamped with a device whose proof did not verify.
    device_id: str | None = None
    device_tier: str | None = None
    #: A credential MINTED by this handshake — the pairing ceremony's second
    #: half, and the only frame in this lane that ever carries a secret. It
    #: exists because a code that cannot be redeemed by the party it was printed
    #: for is half a ceremony: the operator runs `harness gateway pair`, reads
    #: eight characters onto a phone, and the phone has to be able to turn them
    #: into something durable over the link it just pinned.
    #:
    #: Handed to the ``hello_payload`` builder through a one-shot slot on the
    #: connection and cleared there, so it lives for the microseconds between
    #: the handshake and the reply and is never a field anything can read later.
    issued_token: str | None = None
    #: Set only when ``ok`` and only by a PEER-credential authenticator (gateway
    #: Stage 6): which paired INSTALL this connection is. Never set beside
    #: ``device_id`` — a hello names one credential or the other, and the
    #: authenticator refuses a frame that names both.
    peer_install_id: str | None = None
    #: The peer half of ``issued_token``: the symmetric secret a ``peer_code``
    #: hello just minted, riding the one ``hello_ok`` that carries it and read-
    #: and-cleared exactly as the device token is. Two slots rather than one
    #: because the two ceremonies mint different credentials into different
    #: stores, and a single field would let a future edit put a device token on
    #: a peer's greeting by getting one branch wrong.
    issued_peer_secret: str | None = None
    #: When the credential :attr:`issued_peer_secret` names stops working
    #: (ISO-8601 UTC), or ``None`` for never — S2, R-IP15 as amended. It rides
    #: BESIDE the secret rather than being derived on the joining side, because
    #: the redeeming side is the one that decided it: an edge whose two ends
    #: computed their own expiry would lapse at two different moments.
    issued_peer_secret_expires_at: str | None = None
