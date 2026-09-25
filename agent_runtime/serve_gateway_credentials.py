"""The gateway hello's credential kinds, as a table (program rule 12).

FOUR hellos reach the gateway lane's authenticator and this module is the only
place that tells them apart: a device credential, a device pairing code, a peer
credential and a peer join code. :func:`credential_kind` classifies a frame by
which FIELD it names — and refuses a frame that names more than one, which is
where Stage 6's "device-tier and peer-tier credentials are never
interchangeable" is enforced at the frame level — and :data:`CREDENTIAL_KINDS`
maps each :class:`CredentialKind` to the one function that verifies it. The
classifier is the table's only key source, so a fifth credential is one enum
member and one table row, never a fifth ``if``.

Every failure of any kind — no id, unknown id, revoked row, wrong proof, wrong
code, wrong ceremony — comes back as the SAME ``bad_proof`` rejection, so a
caller that has proven nothing cannot enumerate which device ids or which paired
installs exist by watching the reason change. The runtime's own log keeps the
distinction; the wire does not.

Lives beside ``serve_gateway_auth`` rather than inside it only because that
module is at the size ceiling (its own split is lane R3's); the store calls it
makes are that module's and ``gateway_peers``'.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

__layer__ = "lanes"

__all__ = [
    "CREDENTIAL_KINDS",
    "CredentialKind",
    "authenticate_hello",
    "credential_kind",
]


class CredentialKind(StrEnum):
    """Which credential field a gateway hello names — the field name itself."""

    PAIRING_CODE = "pairing_code"
    PEER_CODE = "peer_code"
    PEER_INSTALL_ID = "peer_install_id"
    DEVICE_ID = "device_id"


#: The ONE pair that is not two credentials: a peer JOIN frame carries the code
#: (the credential) and the install id (the name being claimed under it).
_PEER_JOIN_FRAME: Final[tuple[CredentialKind, ...]] = (
    CredentialKind.PEER_CODE,
    CredentialKind.PEER_INSTALL_ID,
)


def credential_kind(message: dict[str, Any]) -> CredentialKind | None:
    """Which ONE credential this hello names, or ``None`` for zero or many.

    A counting rule rather than a precedence rule on purpose. A precedence — "a
    code beats an id", "a peer beats a device" — answers a malformed frame by
    picking a winner, and every such rule is one refactor away from picking the
    more privileged one. Counting cannot be got wrong in that direction: two
    credentials is a refusal, and the refusal looks exactly like every other
    credential failure on this lane.

    The ONE pair that is not two credentials is spelled out rather than hidden
    (:data:`_PEER_JOIN_FRAME`). Writing that as an explicit allowance keeps the
    counting rule intact for every other combination, including the one an
    attacker would actually try — a peer id beside a device id, or a device code
    beside a peer code. Enumeration order is the enum's, which is the order the
    fields were always reported in.
    """

    named = tuple(
        kind
        for kind in CredentialKind
        if isinstance(message.get(kind.value), str) and str(message.get(kind.value)).strip()
    )
    if named == _PEER_JOIN_FRAME:
        return CredentialKind.PEER_CODE
    return named[0] if len(named) == 1 else None


def _bad_proof() -> Any:
    from agent_runtime.serve_socket import REJECT_BAD_PROOF, HelloAuthOutcome

    return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)


def _redeem_device_pairing_code(store_root: Any, message: dict[str, Any], nonce: str, port: int) -> Any:
    """A phone that has just been shown eight characters on the operator's terminal.

    The store redeems them under all of ``gateway/pairing.py``'s discipline (TTL,
    pending cap, lockout, constant-time compare) and the connection is admitted as
    the device it just created, with the minted token riding the ``hello_ok`` it
    was going to send anyway. Safe in one round trip because the link is already
    TLS with a fingerprint handed over out of band, the code is one-shot, and a
    failed redemption is the same ``bad_proof`` charged to the same limiter.
    """

    from agent_runtime.serve_gateway_auth import DeviceCredential, redeem_pairing_code
    from agent_runtime.serve_socket import HelloAuthOutcome

    outcome = redeem_pairing_code(
        store_root,
        message.get("pairing_code"),
        device_name=message.get("client")
        if isinstance(message.get("client"), str)
        else None,
    )
    if not isinstance(outcome, DeviceCredential):
        return _bad_proof()
    return HelloAuthOutcome(
        ok=True,
        device_id=outcome.device_id,
        device_tier=outcome.tier,
        issued_token=outcome.token,
    )


def _redeem_peer_join_code(store_root: Any, message: dict[str, Any], nonce: str, port: int) -> Any:
    """The peer join (Stage 6): the device ceremony's three properties, plus one.

    It is the only arm that WRITES facts the other side asserted — the joining
    install's name, its endpoints, its certificate fingerprint — bounded and
    cleaned by ``gateway_peers`` before they land, and safe to keep because the
    code was minted seconds earlier by a human at THIS machine.
    """

    from agent_runtime.gateway_peers import PeerCredential, note_dial_result, redeem_peer_code
    from agent_runtime.serve_socket import HelloAuthOutcome

    # The joining install must NAME itself in the same frame: the edge
    # is symmetric, so a row keyed by nothing would be a peer this
    # install could never dial back and could never recognise again.
    outcome = redeem_peer_code(
        store_root,
        message.get("peer_code"),
        peer_install_id=str(message.get("peer_install_id") or ""),
        display_name=message.get("peer_display_name")
        or message.get("client"),
        endpoints=message.get("peer_endpoints"),
        cert_fingerprint=message.get("peer_cert_fingerprint"),
    )
    if not isinstance(outcome, PeerCredential):
        return _bad_proof()
    # R-D16, this side of the ceremony. The joining install just
    # completed a TLS handshake against this listener and proved a code
    # a human minted here seconds ago — the same evidence the
    # ``peer_install_id`` arm turns into ``reachable`` through
    # ``cache_peer_hello``. Without this the MINTING side's cache stayed
    # at whatever a past dial left, so an edge both stores had just
    # written read as unusable on one of them.
    #
    # Outside ``redeem_peer_code``'s own lock rather than inside it:
    # ``_store_lock`` is not reentrant (``locks._file_lock``), so a
    # cache touch taken within that span would spend its ten-second
    # budget contending with the write it is describing and then give up
    # silently.
    note_dial_result(store_root, outcome.peer_install_id, ok=True)
    return HelloAuthOutcome(
        ok=True,
        peer_install_id=outcome.peer_install_id,
        issued_peer_secret=outcome.secret,
        # S2: whatever the mint decided, carried straight through. The
        # store computed it at redemption; this function neither derives
        # nor defaults one, so the two ends of the edge hold one value.
        issued_peer_secret_expires_at=outcome.expires_at,
    )


def _verify_peer_proof(store_root: Any, message: dict[str, Any], nonce: str, port: int) -> Any:
    """A paired install: an HMAC keyed by the shared verifier, bound to the port."""

    from agent_runtime.gateway_peers import (
        cache_peer_hello,
        note_peer_seen,
        note_peer_store_read,
        verify_peer_proof,
    )
    from agent_runtime.serve_socket import HelloAuthOutcome

    # S2c (R-S2-8). The revision read that makes an EXTERNAL write
    # visible, taken on a read this lane was making anyway. The serve is
    # the process that notices because it is the one that reads
    # repeatedly; a fresh CLI process seeds on its first read and emits
    # nothing, having no baseline to claim a change against.
    note_peer_store_read(store_root)
    peer = verify_peer_proof(
        store_root,
        message.get("peer_install_id"),
        message.get("proof"),
        nonce,
        port=port,
    )
    if not peer.ok or peer.record is None:
        return _bad_proof()
    note_peer_seen(store_root, peer.record.peer_install_id)
    # …and the three OPTIONAL facts the hello may carry about itself,
    # after the proof and never before it: these are assertions by a
    # party that has now authenticated, and writing them for a caller
    # that had not would let an unpaired stranger grow this file.
    cache_peer_hello(
        store_root,
        peer.record.peer_install_id,
        display_name=message.get("peer_display_name"),
        endpoints=message.get("peer_endpoints"),
        cert_fingerprint=message.get("peer_cert_fingerprint"),
    )
    return HelloAuthOutcome(
        ok=True, peer_install_id=peer.record.peer_install_id
    )


def _verify_device_proof(store_root: Any, message: dict[str, Any], nonce: str, port: int) -> Any:
    """A paired device: an HMAC keyed by its own token's digest, bound to the port."""

    from agent_runtime.serve_gateway_auth import note_device_seen, verify_device_proof
    from agent_runtime.serve_socket import HelloAuthOutcome

    auth = verify_device_proof(
        store_root,
        message.get("device_id"),
        message.get("proof"),
        nonce,
        port=port,
    )
    if not auth.ok or auth.record is None:
        return _bad_proof()
    note_device_seen(store_root, auth.record.device_id)
    return HelloAuthOutcome(
        ok=True,
        device_id=auth.record.device_id,
        device_tier=auth.record.tier,
    )


#: One verifier per credential kind, frozen. ``credential_kind`` is its only
#: key source; :func:`_guard_credential_table` fails the import when an enum
#: member has no row.
CREDENTIAL_KINDS: Final[Mapping[CredentialKind, Callable[[Any, dict[str, Any], str, int], Any]]] = (
    MappingProxyType(
        {
            CredentialKind.PAIRING_CODE: _redeem_device_pairing_code,
            CredentialKind.PEER_CODE: _redeem_peer_join_code,
            CredentialKind.PEER_INSTALL_ID: _verify_peer_proof,
            CredentialKind.DEVICE_ID: _verify_device_proof,
        }
    )
)


def authenticate_hello(store_root: Any, message: dict[str, Any], nonce: str, port: int) -> Any:
    """The gateway lane's ``authenticator`` seam: classify, then verify by table."""

    kind = credential_kind(message)
    if kind is None:
        # Zero credentials named, or more than one. A handshake with two
        # credentials in it is exactly where a downgrade lives, and the
        # server must not get to pick which one it liked.
        return _bad_proof()
    return CREDENTIAL_KINDS[kind](store_root, message, nonce, port)


def _guard_credential_table() -> None:
    missing = set(CredentialKind) - set(CREDENTIAL_KINDS)
    if missing:
        raise RuntimeError(f"gateway credential kinds with no verifier: {sorted(missing)}")


_guard_credential_table()
