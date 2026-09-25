"""The ops manifest and the gateway pairing/credential classifiers — the op and credential
vocabularies ``serve`` advertises on its greeting, read by the loop and the gateway listener.
"""

from __future__ import annotations

from typing import Any

from hermes_cli.harness_parts.serve.constants import (
    GATEWAY_TRANSPORT,
    OPS_CONTRACT_VERSION,
    OPS_EVERY_TRANSPORT,
    OPS_GATEWAY_DENIED,
    OPS_STDIO_ONLY,
    SUBSCRIBE_LANES,
)

__layer__ = "policy"

__all__ = [
    "_CREDENTIAL_FIELDS",
    "_credential_kind",
    "_is_gateway",
    "_pairing_block",
    "ops_manifest",
]


def ops_manifest(*, transport: str, service: bool = False) -> dict[str, Any]:
    """What this runtime's OP lane offers *transport*, for the greeting frames.

    Rides ``ready`` (stdio), ``hello_ok`` (socket) and the re-askable ``version``
    reply — the same three frames ``serve_rpc.manifest()`` rides, for the same
    reason: a durable service outlives the install it was started from, so "does
    the thing I am attached to carry the push lane" must be answerable at any
    time and not only from a greeting a client read hours ago.

    ``service`` is read TWICE by a client and the two readings are both
    deliberate (RL-2):

    * **presence of the key** says this runtime understands ``--service`` at
      all. A hermes that predates L-h carries no ``service`` key anywhere, and
      that absence is the launcher's membership gate for falling back to the
      stdio-pipe transport — a condition it can evaluate without version
      arithmetic, which is the same set-plus-integer rule the ops list itself
      already uses.
    * **the value** says whether THIS process is running as one, i.e. whether
      its lifetime is independent of the stdin it was started on.

    The contract integer is untouched: this is an added key on an existing
    block, and every reader written against the four-key block finds exactly
    those four unchanged.
    """

    ops = set(OPS_EVERY_TRANSPORT)
    if transport == "stdio":
        ops |= set(OPS_STDIO_ONLY)
    if transport == GATEWAY_TRANSPORT:
        # The per-transport shape earning its keep a second time. A device
        # learns what it may ask by MEMBERSHIP — the set-plus-integer rule the
        # D12 rollout gate proved — rather than by trying `drain` and reading an
        # error, and the manifest cannot disagree with the dispatcher because
        # both read this tuple.
        ops -= set(OPS_GATEWAY_DENIED)
    return {
        "contract": OPS_CONTRACT_VERSION,
        "transport": transport,
        "ops": sorted(ops),
        "subscribe_lanes": sorted(SUBSCRIBE_LANES),
        "service": bool(service),
    }


def _pairing_block(connection: Any) -> dict[str, Any]:
    """Pop the one-shot credentials onto the greeting, or contribute nothing.

    A function rather than an inline expression because the CLEAR has to be
    unconditional and unmissable: a `getattr` that read the token without
    clearing it would leave a secret on a long-lived object for the life of the
    session, and the bug would be invisible until somebody logged a connection.

    Two slots, one function, and they are mutually exclusive by construction —
    a hello redeems a device code or a peer code, never both, because the
    authenticator refuses a frame that names two credentials. Rendered as two
    differently-named blocks (`paired` / `peered`) rather than one with a
    discriminator, so a client that only understands devices cannot mistake a
    peer secret for a device token by reading a field it already knows.
    """

    token = getattr(connection, "pairing_token", None)
    if token:
        connection.pairing_token = None
        return {
            "paired": {
                "device_id": connection.device_id,
                "tier": connection.device_tier,
                # Store it now — this is the only time it is ever sent, and the
                # install itself keeps only a digest of it.
                "device_token": token,
            }
        }
    secret = getattr(connection, "peer_secret", None)
    if secret:
        connection.peer_secret = None
        expires_at = getattr(connection, "peer_secret_expires_at", None)
        # Cleared with the secret and in the same breath: the two are one
        # one-shot fact, and a slot that outlived its secret would be a stale
        # expiry on a long-lived object for the rest of the session.
        connection.peer_secret_expires_at = None
        return {
            # Gateway Stage 6. The joining install writes its own half of the
            # edge from this block; the `install` block on the same frame is
            # what names WHICH install it just paired with, so nothing is
            # repeated here that the greeting already carries.
            "peered": {
                "peer_install_id": connection.peer_install_id,
                # The only time it is ever sent. BOTH installs keep only a
                # digest of it — see ``gateway_peers`` — so a client that drops
                # this frame has paired an edge it can never use.
                "peer_secret": secret,
                # S2 (R-IP15 as amended). ADDITIVE, and ``None`` on every edge
                # the manual ceremony mints, so a joining install that predates
                # this key reads what it always read. It has to travel: the
                # redeeming side computed the stamp and the joining side has no
                # other way to learn it, and an edge whose two ends expire on
                # different days is the divergence ``_row`` exists to prevent.
                "expires_at": expires_at,
            }
        }
    return {}


def _is_gateway(connection: Any) -> bool:
    """Did this frame arrive on the gateway lane — from a device or a peer?

    Keyed on the TRANSPORT and not on the credential stamp, deliberately. The
    stamp answers "which device" or "which install"; this answers "did this come
    through the door that is open to the network", and those are different
    questions whose answers must not be allowed to diverge. A gateway connection
    that somehow lacks a stamp is exactly the case where the narrower test would
    silently grant local authority — the same reasoning, and the same guard, as
    ``call_authorization.caller_for_connection``'s gateway arm.

    Named ``_is_device`` until gateway Stage 6, when the name became false: the
    refusals it guards (`argv_lane_unavailable`, `op_not_available_on_gateway`)
    were always about the DOOR and now genuinely have two kinds of caller behind
    them. The behaviour did not change and neither did the predicate; a peer
    inherits both refusals for free, which is the point of keying on the lane.
    """

    return (
        connection is not None
        and str(getattr(connection, "transport", "") or "") == GATEWAY_TRANSPORT
    )


#: The four credential fields a gateway hello may name, in the order
#: :func:`_credential_kind` reports them. A TUPLE and not four ``if``s, because
#: the rule being enforced is "exactly one of these" and a rule about a set is
#: only checkable against a set — four independent branches is how a fifth field
#: eventually gets added to three of them.
_CREDENTIAL_FIELDS: tuple[str, ...] = (
    "pairing_code",
    "peer_code",
    "peer_install_id",
    "device_id",
)


def _credential_kind(message: dict[str, Any]) -> str | None:
    """Which ONE credential this hello names, or ``None`` for zero or many.

    The whole of "device-tier and peer-tier credentials are never
    interchangeable" at the FRAME level, and it is a counting rule rather than a
    precedence rule on purpose. A precedence — "a code beats an id", "a peer
    beats a device" — answers a malformed frame by picking a winner, and every
    such rule is one refactor away from picking the more privileged one.
    Counting cannot be got wrong in that direction: two credentials is a
    refusal, and the refusal looks exactly like every other credential failure
    on this lane.

    The ONE pair that is not two credentials is spelled out rather than hidden:
    a join frame carries ``peer_code`` AND ``peer_install_id``, where the code
    is the credential and the id is the name being claimed under it. Writing
    that as an explicit allowance keeps the counting rule intact for every other
    combination, including the one an attacker would actually try — a peer id
    beside a device id, or a device code beside a peer code.
    """

    named = [
        field
        for field in _CREDENTIAL_FIELDS
        if isinstance(message.get(field), str) and str(message.get(field)).strip()
    ]
    if named == ["peer_code", "peer_install_id"]:
        return "peer_code"
    return named[0] if len(named) == 1 else None
