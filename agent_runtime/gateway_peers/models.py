"""The peer stores' VOCABULARY and row shapes (layout sheet gateway_peers.md §1).

Every word the two peer stores spend (``PEER_STORE_*``, ``PEER_PROOF_*``,
``PEER_AUTH_*``, ``REACHABILITY_*``, ``PEER_EVENT_*``), the six frozen rows,
the trust/cache field partition, the two file paths and the endpoint /
fingerprint coercions. Imports nothing above it; a vocabulary + row-shape
module, exempt from the 100-line floor by kind.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..gateway_identity import gateway_dir
from ..serde import is_hex
from ..store_file_io import stamp_passed as _stamp_passed

__layer__ = "models"


# ── constants ────────────────────────────────────────────────────────────────

#: Beside ``install.json`` / ``devices.json`` / ``pairing.json``. The DIRECTORY
#: is the unit Stage 0 established and Stage 1 extended; this is its fourth file.
PEER_STORE_FILENAME = "peers.json"
#: Serialised beside the rows so a future migration reads a number rather than
#: guessing from key presence — ``devices.json``'s habit, and its reason.
PEER_STORE_CONTRACT = 1

#: 256 bits, hex-encoded. Not configurable, for ``serve_auth``'s reason: a knob
#: here can only ever be turned down.
PEER_SECRET_BYTES = 32

#: The peer handshake's proof version, and it is a THIRD number beside
#: ``HELLO_CONTRACT_VERSION`` (the frame exchange, shared byte-for-byte) and
#: ``GATEWAY_PROOF_CONTRACT`` (the device derivation). It is separate from the
#: device one for the reason that one is separate from the frame one: they
#: describe different derivations, and a single number covering both would have
#: to move whenever either moved, with no way for a client to tell which half
#: changed. The ``pwv`` prefix below is the other half of that separation —
#: even at equal contract numbers, a device proof and a peer proof over the
#: same nonce and port are different bytes.
PEER_PROOF_CONTRACT = 1
PEER_PROOF_ALGORITHM = "hmac-sha256"

#: How many addresses one peer row may carry. An install can legitimately be
#: reachable at more than one (a wired address and a wireless one), and a row
#: that could only hold one would make an operator choose which half of their
#: LAN the edge works on. Bounded because the list arrives over the wire from
#: the joining install, and an unbounded field on a pre-authorization path is a
#: store an unauthenticated peer can grow.
MAX_ENDPOINTS = 4

#: Typed outcomes of :func:`verify_peer_proof`, mirroring the device store's.
#: The reason IS the classification: the socket lane derives "does this charge
#: the auth rate limiter" from it and from nothing else.
PEER_AUTH_OK = "ok"
PEER_AUTH_UNKNOWN = "unknown_peer"
PEER_AUTH_REVOKED = "peer_revoked"
PEER_AUTH_BAD_PROOF = "bad_proof"
PEER_AUTH_MALFORMED = "hello_malformed"
#: A row whose ``expires_at`` has passed. Its own outcome rather than a second
#: spelling of ``peer_revoked``, for :data:`~agent_runtime.serve_gateway_auth.AUTH_EXPIRED`'s
#: reason: an operator re-runs a ceremony for one and does nothing for the other.
PEER_AUTH_EXPIRED = "peer_expired"
#: The six outcomes as one closed vocabulary; ``PeerAuth.outcome`` is one of
#: them and :func:`verify_peer_proof` is their one writer. Plain constants and
#: NOT an Enum: ``ok`` and ``unknown``-class words are fork-wide
#: (``turn_visibility``, ``RpcRefusal``), so an Enum here would make W0-G5
#: arm (c) count every unrelated ``== "ok"`` in the fork (layout sheet §2).
PEER_AUTH_REASONS: Final[tuple[str, ...]] = (
    PEER_AUTH_OK,
    PEER_AUTH_UNKNOWN,
    PEER_AUTH_REVOKED,
    PEER_AUTH_BAD_PROOF,
    PEER_AUTH_MALFORMED,
    PEER_AUTH_EXPIRED,
)


# ── typed results ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PeerPairingCode:
    """A freshly minted peer code. The plaintext ``code`` exists ONLY here.

    No ``tier`` field, and its absence is the design rather than an omission: a
    peer does not hold a tier. It holds an ALLOWLIST — exactly the methods
    ``call_authorization.PEER_METHOD_ALLOWLIST`` names — so there is nothing for
    an operator to choose at pair time and therefore nothing to store. A ``tier``
    here would be a field that looked like it widened a door and did not.
    """

    code: str
    request_id: str
    note: str | None
    expires_at: float

    @property
    def ok(self) -> bool:
        return True

    def expires_in_seconds(self, *, now: float | None = None) -> int:
        return max(0, int(self.expires_at - (now if now is not None else time.time())))


@dataclass(frozen=True, slots=True)
class PeerCredential:
    """What a successful redemption hands back. ``secret`` appears once, here.

    Returned to the REDEEMING side (install A, whose code it was) so A can put
    it on the one ``hello_ok`` that carries it. The joining side (B) receives
    that frame and calls :func:`record_peer` with the same value. After those
    two writes the plaintext exists nowhere: both stores hold the digest.
    """

    peer_install_id: str
    secret: str
    display_name: str
    #: When the edge this redemption just wrote stops working, ISO-8601 UTC, or
    #: ``None`` for never. Returned so the redeeming side can put it on the ONE
    #: ``hello_ok`` that carries the secret: the joining install has no other
    #: way to learn it, and two ends of one edge that expire on different days
    #: is precisely the divergence :func:`~agent_runtime.gateway_peers.trust_store.peer_row` exists to prevent.
    expires_at: str | None = None

    @property
    def ok(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class PeerRecord:
    """One paired install as it is stored — WITHOUT anything secret.

    ``secret_verifier`` is deliberately not a field. Every surface that shows a
    peer to a human (``harness gateway peers list``, a log line, a refusal)
    renders one of these, so the type itself is what makes "the credential
    leaked into an operator surface" unrepresentable rather than merely
    unintended — ``DeviceRecord``'s argument, and it holds harder here because a
    peer secret is live at BOTH ends.

    Which side each field is on (module docstring, R-IP14):

    * ``peer_install_id``, ``approved_at``, ``revoked``, ``revoked_at`` —
      TRUST. This install decided them; nothing on the wire moves them.
    * ``display_name``, ``endpoints``, ``cert_fingerprint``, ``last_seen`` —
      CACHE. ``display_name`` is the name-at-pairing (the far install's own
      word for itself, from the join hello on A or its ``install`` block on B)
      and is never refreshed here; ``endpoints`` and ``cert_fingerprint`` are
      likewise pairing-time copies, refreshed only by a re-``join``; and
      ``last_seen`` is the one the network writes on every verified hello.
    """

    peer_install_id: str
    display_name: str
    endpoints: tuple[dict[str, Any], ...]
    cert_fingerprint: str | None
    approved_at: str
    last_seen: str | None
    revoked: bool
    revoked_at: str | None
    #: TRUST, and the one new field S2 adds to this row. ``None`` means never,
    #: which is what the manual ceremony keeps writing. The far install holds
    #: the SAME value (it rides ``hello_ok.peered.expires_at``), so both ends of
    #: an edge lapse together rather than one refusing while the other keeps
    #: dialling.
    expires_at: str | None = None

    @property
    def expired(self) -> bool:
        """Has :attr:`expires_at` passed? ``False`` when there is none.

        Fails toward LIVE on an unreadable stamp — see
        ``store_file_io.stamp_passed`` for why that direction, and why it is the
        opposite of the direction ``_decode_device`` fails in for a tier.
        """

        return _stamp_passed(self.expires_at)

    def payload(self) -> dict[str, Any]:
        return {
            "peer_install_id": self.peer_install_id,
            "display_name": self.display_name,
            "endpoints": [dict(endpoint) for endpoint in self.endpoints],
            "cert_fingerprint": self.cert_fingerprint,
            "approved_at": self.approved_at,
            "last_seen": self.last_seen,
            "revoked": self.revoked,
            "revoked_at": self.revoked_at,
            "expires_at": self.expires_at,
            "expired": self.expired,
        }


@dataclass(frozen=True, slots=True)
class PeerAuth:
    """The handshake's answer about one peer.

    ``record`` is present only on :data:`PEER_AUTH_OK`, so a caller cannot stamp
    a connection with a peer whose proof did not verify.
    """

    #: One of :data:`PEER_AUTH_REASONS`.
    outcome: str
    peer_install_id: str | None = None
    record: PeerRecord | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == PEER_AUTH_OK


# ── paths ────────────────────────────────────────────────────────────────────


def peer_store_path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / PEER_STORE_FILENAME


# ── endpoints ────────────────────────────────────────────────────────────────


def clean_endpoints(value: Any) -> tuple[dict[str, Any], ...]:
    """Coerce whatever arrived into at most :data:`MAX_ENDPOINTS` addresses.

    This runs on data the OTHER install sent, over a link where it has not yet
    proven anything — the join hello carries the address the joining side says
    it is reachable at. So every field is bounded and typed here rather than
    trusted: a host is a printable single-line string capped at 255 characters
    (the DNS name limit, which is also longer than any address), a port is an
    integer in range, and anything else in the list is dropped rather than
    stored as-is.

    Dropping rather than refusing is deliberate. A peer that offers three good
    addresses and one malformed one is a peer with three good addresses, and
    failing the whole pairing over the fourth would make an install with an
    unusual interface unpairable for a reason nobody could see.
    """

    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    for item in value:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host") or "").strip()
        host = "".join(ch for ch in host if ch.isprintable() and not ch.isspace())[:255]
        if not host:
            continue
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not 0 < port <= 65535:
            continue
        row = {"host": host, "port": port}
        if row not in rows:
            rows.append(row)
        if len(rows) >= MAX_ENDPOINTS:
            break
    return tuple(rows)


def _clean_fingerprint(value: Any) -> str | None:
    """A sha256 hex fingerprint, or ``None``. Never a half-parsed string.

    ``None`` rather than an empty string, because the dialer branches on
    presence: a row with no fingerprint means "pin nothing", which is a real and
    much weaker posture than "pin this". The two must not be spelled the same.
    """

    text = str(value or "").strip().lower()
    return text if is_hex(text, 64) else None


# ── internals ────────────────────────────────────────────────────────────────


#: The row's TRUST half: written by a ceremony or by :func:`revoke_peer`, never
#: by the network. See the module docstring (R-IP14).
PEER_ROW_TRUST_FIELDS = frozenset(
    {
        "peer_install_id",
        "secret_verifier",
        "approved_at",
        "revoked",
        "revoked_at",
        # S2. TRUST and not cache, and the classification is the argument: THIS
        # install decided the lifetime at mint time (or was handed it once, on
        # the one frame that carries the secret), and no later hello may move
        # it. A peer that could push its own expiry out would hold a credential
        # with no end — which is the same authority ``revoked`` denies it.
        "expires_at",
    }
)

#: The row's CACHE half: what the far install told us, at pairing or on a
#: hello. The install is the authority for each of these about ITSELF; this is
#: a copy, and S2c moves the copies to ``peers_cache.json`` (R-IP12a).
PEER_ROW_CACHE_FIELDS = frozenset(
    {"display_name", "endpoints", "cert_fingerprint"}
)


# ══ the cache sidecar (S2c, R-IP12a / R-S2-7) ════════════════════════════════
#
# ``<store_root>/gateway/peers_cache.json``, beside ``peers.json`` and under the
# same directory lock. Two files, and the split is the whole mechanism:
#
#   peers.json        what THIS install decided.  Trust.  Written by a ceremony.
#   peers_cache.json  what the NETWORK told us.    Cache.  Written by a hello,
#                                                          a dial, an announce.
#
# The frozensets S0b added made the classification machine-readable; this makes
# it structural. A reader no longer has to remember which keys the network may
# move — it reads the file the fact is in. And a cache writer physically cannot
# reach a credential, because no function below opens ``peers.json`` for writing
# (asserted in ``test_gateway_peers_store.py``).
#
# **Pushed, never polled** (R-IP12). Nothing here runs on a timer. Every row is
# written by an edge that already existed: a verified hello, a dial that
# succeeded or failed, a roster the tool just fetched, an announce a peer sent.
# The one thing that is not push-shaped is an EXTERNAL write — an editor, or a
# build that predates this file — and that is what :func:`peer_store_revision`
# and the process-local memo below are sized for. A stat, not a poll.

PEER_CACHE_FILENAME = "peers_cache.json"
PEER_CACHE_CONTRACT = 1

#: Three words and no fourth. ``unknown`` is the honest state of a row nothing
#: has dialled or heard from yet, and it is DIFFERENT from ``unreachable``: one
#: means "we have not tried", the other means "we tried and it did not answer",
#: and an operator acts differently on each. A boolean would have collapsed them.
REACHABILITY_UNKNOWN = "unknown"
REACHABILITY_REACHABLE = "reachable"
REACHABILITY_UNREACHABLE = "unreachable"
#: The three words as one vocabulary; ``note_dial_result`` is their one writer.
REACHABILITY_STATES: Final[tuple[str, ...]] = (
    REACHABILITY_UNKNOWN,
    REACHABILITY_REACHABLE,
    REACHABILITY_UNREACHABLE,
)

#: The cache row's keys, declared for the same reason the trust row's are: a
#: field added here without being listed fails ``_cache_row``'s partition test,
#: so "which file owns this fact" stays a decision somebody makes rather than a
#: side effect of where a line was typed.
PEER_CACHE_ROW_FIELDS = frozenset(
    {
        "peer_install_id",
        "announced_display_name",
        "endpoints",
        "cert_fingerprint",
        "last_seen",
        "last_hello_at",
        "reachability",
        "unreachable_since",
        "roster",
        "revoked_you",
        "revoked_you_at",
        "fingerprint_rotation",
        "last_announce_at",
        "correlation",
    }
)

#: The five ``gateway.peer.*`` types, as module-level constants. Constants and
#: not literals at the call sites, because the S55 emitter gate resolves a
#: module-level string binding — and because a type spelled twice is a type that
#: eventually gets spelled differently once.
PEER_EVENT_RECORDED = "gateway.peer.recorded"
PEER_EVENT_REVOKED = "gateway.peer.revoked"
PEER_EVENT_UPDATED = "gateway.peer.updated"
PEER_EVENT_ROSTER = "gateway.peer.roster"
PEER_EVENT_REACHABILITY = "gateway.peer.reachability"
#: The five types as one vocabulary; the store doors are their only writers.
PEER_EVENT_TYPES: Final[tuple[str, ...]] = (
    PEER_EVENT_RECORDED,
    PEER_EVENT_REVOKED,
    PEER_EVENT_UPDATED,
    PEER_EVENT_ROSTER,
    PEER_EVENT_REACHABILITY,
)

#: How many roster rows one cached peer keeps. The HUD shows eight; this is the
#: store's own ceiling so a far install with two hundred agents cannot grow this
#: file without bound through an edge that is supposed to be read-only.
PEER_CACHE_ROSTER_CAP = 64


@dataclass(frozen=True, slots=True)
class PeerCacheRow:
    """What one paired install has TOLD us, as it is cached.

    Every field is the far install's own claim about itself, or this install's
    own observation of trying to reach it. Nothing here is a credential and
    nothing here is consulted by :func:`verify_peer_proof` — which is what makes
    it safe for a peer to write (through :func:`apply_peer_announce`) at all.

    Two fields need their asymmetry stated because a reader would otherwise
    assume symmetry:

    * ``cert_fingerprint`` is the fingerprint the peer ANNOUNCED. The pin a dial
      uses is always the TRUST row's. A rotation is recorded in
      ``fingerprint_rotation`` and shown to an operator; it is never applied,
      because a peer that could rotate its own pin could rotate it to a
      certificate it does not hold and become a different machine (S0b B2 —
      re-pair is the cure).
    * ``revoked_you`` is ONE-WAY. An announce may set it; only a trust write
      (a re-``join``, a re-``redeem``) clears it. An un-revoke that arrived over
      the wire would be an install granting itself access it had been refused.
    """

    peer_install_id: str
    announced_display_name: str | None = None
    endpoints: tuple[dict[str, Any], ...] = ()
    cert_fingerprint: str | None = None
    last_seen: str | None = None
    last_hello_at: str | None = None
    reachability: str = REACHABILITY_UNKNOWN
    unreachable_since: str | None = None
    roster: dict[str, Any] | None = None
    revoked_you: bool = False
    revoked_you_at: str | None = None
    fingerprint_rotation: dict[str, Any] | None = None
    last_announce_at: str | None = None
    correlation: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "peer_install_id": self.peer_install_id,
            "announced_display_name": self.announced_display_name,
            "endpoints": [dict(endpoint) for endpoint in self.endpoints],
            "cert_fingerprint": self.cert_fingerprint,
            "last_seen": self.last_seen,
            "last_hello_at": self.last_hello_at,
            "reachability": self.reachability,
            "unreachable_since": self.unreachable_since,
            "roster": dict(self.roster) if isinstance(self.roster, dict) else None,
            "revoked_you": self.revoked_you,
            "revoked_you_at": self.revoked_you_at,
            "fingerprint_rotation": (
                dict(self.fingerprint_rotation)
                if isinstance(self.fingerprint_rotation, dict)
                else None
            ),
            "last_announce_at": self.last_announce_at,
            "correlation": self.correlation,
        }


@dataclass(frozen=True, slots=True)
class UsablePeer:
    """One peer an address could actually reach, with the spelling that reaches it.

    THE predicate's row type (R-S2-16). Before it, three surfaces each decided
    "is this peer usable" for themselves — the resolver checked ``revoked``, the
    HUD listed everything, and a tool would have had to invent a third rule — so
    an operator could see a peer in one place and be refused it in another with
    no way to tell which was right.
    """

    record: PeerRecord
    cache: PeerCacheRow | None
    #: How this peer must be SPELLED in an ``@install/target`` to resolve: the
    #: display name when it is unique among usable peers, otherwise the install
    #: id. The line an operator reads is therefore always an address a send
    #: would accept, rather than a name the resolver would refuse as ambiguous.
    ref: str

    @property
    def peer_install_id(self) -> str:
        return self.record.peer_install_id


def peer_cache_path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / PEER_CACHE_FILENAME


def _guard_vocabularies() -> None:
    """Refuse at import a vocabulary that spells one word twice.

    Each tuple above is the one declaration of its words; two members with one
    spelling would make two outcomes (two events, two reachability states)
    indistinguishable to every reader downstream — the
    ``mission_chat_outcome._guard_turn_outcome_vocabulary`` pattern.
    """

    for name, words in (
        ("PEER_AUTH_REASONS", PEER_AUTH_REASONS),
        ("REACHABILITY_STATES", REACHABILITY_STATES),
        ("PEER_EVENT_TYPES", PEER_EVENT_TYPES),
    ):
        if len(set(words)) != len(words):
            raise RuntimeError(f"{name} spells one word twice: {sorted(words)}")


_guard_vocabularies()
