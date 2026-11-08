"""The gateway credential store's constants and typed results (rows, outcomes, refusals).

Part of the :mod:`agent_runtime.serve_gateway_auth` layout; the package docstring is the design.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..call_authorization import (
    DEVICE_KIND_DEVICE,
    TIER_CONSOLE,
)
from ..clock import stamp_passed as _stamp_passed

__layer__ = "stores"


# ── constants ────────────────────────────────────────────────────────────────

#: Beside ``install.json`` under ``<store_root>/gateway/``. The DIRECTORY is the
#: unit Stage 0 established; Stage 6 adds ``peers.json`` here too.
DEVICE_STORE_FILENAME = "devices.json"
PAIRING_STORE_FILENAME = "pairing.json"
#: Serialised beside the rows so a future migration reads a number rather than
#: guessing from key presence. Same "a set plus an integer" habit the RPC
#: manifest uses; this one is a file, so nothing negotiates on it.
DEVICE_STORE_CONTRACT = 1

#: The code discipline — alphabet, length, TTL, caps, lockout — is
#: ``gateway_pairing_codes``' and is RE-EXPORTED here rather than restated,
#: because Stage 6's peer ceremony obeys the same numbers over the same pending
#: map. The names stay importable from this module: they were this module's API
#: for the whole of Stage 1 and several tests read them here.

#: 256 bits, hex-encoded. Not configurable, for ``serve_auth``'s reason: a knob
#: here can only ever be turned down.
DEVICE_TOKEN_BYTES = 32

#: The gateway handshake's proof version. SEPARATE from
#: ``serve_socket.HELLO_CONTRACT_VERSION`` on purpose — that number describes the
#: FRAME exchange (who speaks first, what fields are present), which the gateway
#: lane shares byte-for-byte; this one describes the DERIVATION, which differs
#: because a device proof also binds the device id. A single number covering both
#: would have to move whenever either moved, and a client could not tell which
#: half changed.
GATEWAY_PROOF_CONTRACT = 1
GATEWAY_PROOF_ALGORITHM = "hmac-sha256"

#: Typed outcomes of :func:`verify_device_proof`. The reason IS the
#: classification: the socket lane derives "does this charge the auth rate
#: limiter" from it, never from a boolean a caller passes in — the shape
#: ``serve_socket._reject`` already had to be corrected into.
AUTH_OK = "ok"
AUTH_UNKNOWN_DEVICE = "unknown_device"
AUTH_REVOKED = "device_revoked"
AUTH_BAD_PROOF = "bad_proof"
AUTH_MALFORMED = "hello_malformed"
#: A row whose ``expires_at`` has passed (R-IP15 as amended: an INTRODUCED
#: credential lives 30 days). Its own outcome rather than a second spelling of
#: ``device_revoked``, because the operator's next move differs: a revoked
#: device was thrown out on purpose and should stay out; an expired one is a
#: device that was fine and needs a fresh introduction. The WIRE still collapses
#: both into one rejection — see :func:`verify_device_proof`.
AUTH_EXPIRED = "device_expired"

#: How long a credential MINTED BY ``harness gateway introduce`` lives, in
#: seconds — thirty days, R-IP15 as amended. ONE constant for both stores
#: (``gateway_peers`` imports it from here, as it already imports the lock and
#: the pairing-state helpers), because a device half and a peer half minted by
#: one ``introduce`` that expired on different days would be an edge whose two
#: ends disagree about when it died.
#:
#: **``None`` is the other legal value and it means "never".** The manual
#: ceremony (``gateway pair`` / ``peers pair``) keeps minting with no TTL, so a
#: row written by a pre-S2 build and a row written by today's manual verbs stay
#: byte-identical: an operator standing at both machines is the provenance, and
#: expiring that on a clock would lock people out of their own workshop. The TTL
#: exists for the credential nobody carried by hand — the one a backend grant
#: introduced — which is exactly the one that should not outlive its errand.
CREDENTIAL_TTL_SECONDS_INTRODUCED = 30 * 86400

#: Why a row was revoked, when this module revoked it rather than an operator
#: (RL-23). The only value today: the far launcher redeemed a NEW code for the
#: same ``account_device_id``, so the old credential is superfluous rather than
#: compromised. An operator's ``harness gateway revoke`` still writes no reason
#: at all, and that absence is the reading — nobody automated it.
REVOKED_SUPERSEDED = "superseded"

#: How long a REVOKED row is kept before the boot prune removes it — thirty
#: days, the same span as an introduced credential and for a related reason: the
#: row's remaining job is to answer "why did my Mac stop connecting", and after a
#: month nobody is asking. A LIVE row is never a candidate at any age, and a row
#: whose ``revoked_at`` will not parse is kept (:func:`prune_revoked_devices`).
REVOKED_ROW_RETENTION_SECONDS = 30 * 86400

#: The tier a pairing run on the install's own machine confers, per R11 as
#: ruled: the operator standing at the console IS the account-auth trace, so the
#: default is the full one and ``read`` is what an operator asks for explicitly.
#: Both spellings are representable from day one — a field that exists but has
#: one value is a field nobody has tested.
DEFAULT_DEVICE_TIER = TIER_CONSOLE


# ── typed results ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StoreRefusal:
    """A write that did not happen, with the reason spelled for a machine."""

    reason: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PairingCode:
    """A freshly minted code. The plaintext ``code`` exists ONLY here.

    It is returned to the CLI verb that asked for it and is never persisted:
    ``pairing.json`` holds a salted digest. A caller that loses this object has
    to mint another one, which is the intended failure mode.
    """

    code: str
    request_id: str
    tier: str
    name: str | None
    expires_at: float

    @property
    def ok(self) -> bool:
        return True

    def expires_in_seconds(self, *, now: float | None = None) -> int:
        return max(0, int(self.expires_at - (now if now is not None else time.time())))


@dataclass(frozen=True, slots=True)
class DeviceCredential:
    """What a successful redemption hands back. ``token`` appears once, here."""

    device_id: str
    token: str
    tier: str
    name: str
    kind: str = DEVICE_KIND_DEVICE
    bound_instances: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    """One paired device as it is stored — WITHOUT anything secret.

    The ``verifier`` is deliberately not a field on this dataclass. Every
    surface that shows a device to a human (``harness gateway devices list``, a
    log line, a future ``gateway.*`` method) renders one of these, so the type
    itself is what makes "the credential leaked into an operator surface"
    unrepresentable rather than merely unintended.
    """

    device_id: str
    name: str
    tier: str
    created_at: str
    last_seen: str | None
    revoked: bool
    revoked_at: str | None
    #: When this credential stops working, ISO-8601 UTC, or ``None`` for never
    #: (R-IP15 as amended). TRUST, not cache: THIS install decided it at mint
    #: time from :data:`CREDENTIAL_TTL_SECONDS_INTRODUCED`, and nothing on the
    #: wire can move it — a device that could push its own expiry out would hold
    #: a credential with no end.
    expires_at: str | None = None
    #: The ACCOUNT's device id, when an ``introduce`` named one. A LABEL and not
    #: a check: hermes never learns an account device id at redeem time (the row
    #: id is minted ``dev_<hex>`` here), so this is the join key that relates
    #: this row to the account row an operator sees in the launcher's sheet
    #: (R-IP14, one bookkeeping) — and nothing authenticates against it.
    account_device_id: str | None = None
    #: Why this row was revoked, when the runtime revoked it rather than an
    #: operator: :data:`REVOKED_SUPERSEDED`, or ``None`` for every hand-run
    #: ``harness gateway revoke`` and every row written before RL-23.
    revoked_reason: str | None = None
    #: The credential that replaced this one, when :attr:`revoked_reason` is
    #: ``superseded``. The two travel together on purpose — a revoked row that
    #: names its successor turns a column of dead credentials into one device's
    #: history.
    superseded_by: str | None = None
    #: TRUST, written by the ceremony (``RT-EXTERNAL-GATEWAY-CHANNEL-CREDENTIAL``): ``device`` —
    #: every row written before the rule — or ``channel``, the owner's own external gateway,
    #: which may only relay chat turns to :attr:`bound_instances` (``gateway_channel``).
    kind: str = DEVICE_KIND_DEVICE
    bound_instances: tuple[str, ...] = ()
    #: A channel's owning account namespace (the launcher's 64-hex client-scope digest), written
    #: at ``pair --kind channel --client-scope`` (``RT-EXTERNAL-GATEWAY-CHANNEL-CLIENT-SCOPE``):
    #: every conversation the channel mints is stamped with it, so the account-filtered
    #: ``runtime.operator.conversation.list`` lists it. ``None`` — every row before the rule, or
    #: an unreadable value — mints unscoped conversations (they list under ``all_accounts``).
    client_scope: str | None = None

    @property
    def expired(self) -> bool:
        """Has :attr:`expires_at` passed? ``False`` when there is none.

        Computed rather than stored, for the reason every "is it stale yet"
        predicate is: a boolean written at mint time is a fact about the past
        wearing the tense of the present. An unparseable stamp reads as NOT
        expired — the same direction ``decode_device`` fails in for an unknown
        tier is the SAFE direction there (least privilege) and the opposite one
        here, because a clock this build cannot read must not silently revoke
        every device an operator paired.
        """

        return _stamp_passed(self.expires_at)

    def payload(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "tier": self.tier,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "revoked": self.revoked,
            "revoked_at": self.revoked_at,
            "expires_at": self.expires_at,
            "expired": self.expired,
            "account_device_id": self.account_device_id,
            "revoked_reason": self.revoked_reason,
            "superseded_by": self.superseded_by,
            # ``device_kind`` on the surface: a CLI envelope's own ``kind`` sits beside these keys.
            "device_kind": self.kind,
            "bound_instances": list(self.bound_instances),
            "client_scope": self.client_scope,
        }


@dataclass(frozen=True, slots=True)
class DeviceAuth:
    """The handshake's answer about one device.

    ``record`` is present only on :data:`AUTH_OK`, so a caller cannot stamp a
    connection with a device whose proof did not verify — the same reason
    ``SocketConnection.authenticated`` is set after ``verify_hello_proof`` and
    not before.
    """

    outcome: str
    device_id: str | None = None
    record: DeviceRecord | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == AUTH_OK
