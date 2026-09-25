"""One outbound peer handshake over the candidate list (Stage 6, S2c, R-D20).

``dial_peer``: guards before any socket, cache endpoints first then the
trust row's, the pin always the trust row's, the attempt loop, and the
``local_policy`` word ``_dial_failure_word`` leads a failure with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cache import note_dial_result, read_peer_cache
from .trust_store import _read_peers, lookup_peer

__layer__ = "lanes"


# ── dialling ─────────────────────────────────────────────────────────────────


#: R-D20's word for "this machine's own OS refused to send", spelled once here
#: so the chat lane and ``peers join`` cannot drift apart. The classifier itself
#: lives in :mod:`hermes_cli.harness_parts.gateway_commands`, beside the
#: interface enumeration it has to consult — see :func:`_dial_failure_word`.
LOCAL_POLICY = "local_policy"


def _dial_failure_word(exc: BaseException, host: str) -> str:
    """What to write beside a failed candidate: ``local_policy`` or the class.

    The classification is R-D20's and it needs to know whether ``host`` is on a
    segment one of THIS machine's addresses sits on — a question only the
    interface enumeration in ``gateway_commands`` can answer, which is why the
    classifier lives there and is reached from here the same way
    :func:`dial_peer` already reaches ``_candidate_endpoints``: a function-local
    import, so nothing at module load couples this layer to the CLI one.

    A CLI half that will not import falls back to the exception class, which is
    exactly what this line printed before D6h. The classification is a BETTER
    word for a failure, never the only word — a dial that failed must report
    that it failed whatever else is missing.
    """

    try:
        from ..gateway_endpoints import DIAL_LOCAL_POLICY, classify_dial_error

        if classify_dial_error(exc, host) == DIAL_LOCAL_POLICY:
            return LOCAL_POLICY
    except Exception:
        pass
    return type(exc).__name__


def dial_peer(
    store_root: Path | str,
    peer_install_id: str,
    *,
    client: str = "hermes-peer",
    timeout_seconds: float = 10.0,
) -> tuple[Any, dict[str, Any]]:
    """Connect to a paired install and complete the peer handshake.

    **The endpoints come from THIS INSTALL'S OWN STORES and from nowhere else**,
    which is the plan's Stage 6 risk line made into code: the serve registry
    (``<store_root>/serve_instances/``) names ports on THIS machine, and a
    cross-machine read of it is not merely stale, it is impossible — the file is
    on the other install's disk. So a peer's address is a fact somebody TOLD us,
    and staleness is handled by retry posture rather than by discovery (R8).

    S2c widened *which* store, not where they come from: the cache's addresses
    (what the peer said on its last hello or in an announce) are tried first,
    then the pairing record's, deduped. The PIN is the pairing record's
    fingerprint on every attempt regardless — see the comment at the loop.

    Each endpoint is tried in order and the first handshake that succeeds wins.
    The certificate fingerprint is pinned from the same row: without the pin,
    TLS on a self-signed LAN link stops an eavesdropper and stops no impostor.

    Returns ``(client, hello_ok)``. The caller owns the connection and must
    close it. Raises ``ConnectionError`` when no endpoint answered — a
    TRANSPORT failure, which is the distinction Stage 7's retry posture rests
    on: unreachable is not refused.

    D6h changes one WORD inside that failure and no control flow (R-D20). An
    ``EHOSTUNREACH`` against an address on one of this machine's own subnets is
    macOS 15 Local Network privacy refusing this process, not a route — so the
    failure it records and raises leads with ``local_policy`` and the
    ``gateway.peer.reachability`` event carries that instead of a bare
    ``OSError``. See :func:`_dial_failure_word`.
    """

    dial = Dial.guards(Path(store_root), peer_install_id)
    return dial.outcome(dial.attempts(dial.candidates(), client, timeout_seconds))


@dataclass
class Dial:
    """One ``dial_peer`` call, as the phases its comment map always had.

    ``guards`` refuses before any socket, ``candidates`` spells the address
    order, ``attempts`` runs the loop, ``outcome`` records and answers. The
    fields are what the phases share — the trust row, this root's identity and
    what it advertises — so no phase re-reads a store it has already read.
    """

    root: Path
    peer_install_id: str
    record: Any
    verifier: str
    identity: Any
    self_endpoints: list[dict[str, Any]] = field(default_factory=list)
    self_fingerprint: str | None = None
    failures: list[str] = field(default_factory=list)
    # R-D20's half of the chat lane: the addresses this machine's own OS refused
    # to send to. See :func:`_dial_failure_word`.
    policy_refused: list[str] = field(default_factory=list)

    @classmethod
    def guards(cls, root: Path, peer_install_id: str) -> Dial:
        """Every refusal a dial can give without opening a socket, in order."""

        record = lookup_peer(root, peer_install_id)
        if record is None:
            raise ConnectionError(f"no install {peer_install_id!r} is paired with this root")
        if record.revoked:
            raise ConnectionError(
                f"install {peer_install_id!r} is revoked at this root; re-pair it first"
            )
        # Beside the revocation and BEFORE any socket, for the revocation's reason:
        # a credential this side already knows is dead costs no attempt. Unlike the
        # verifier arms, order does not matter here — nothing is being probed, this
        # is our own store telling us not to bother.
        if record.expired:
            raise ConnectionError(
                f"the credential for install {peer_install_id!r} expired at "
                f"{record.expires_at}; an operator re-introduces the edge to renew it"
            )
        # The VERIFIER, not a secret: both ends of a peer edge store ``sha256(secret)``
        # and key the HMAC with it, which is what makes the edge symmetric — either
        # install can dial the other with the row it holds. The plaintext secret
        # exists only for the length of the one frame that delivered it, and neither
        # store has ever held it.
        verifier = _read_peers(root).get(record.peer_install_id, {}).get("secret_verifier")
        if not verifier:
            raise ConnectionError(f"the peer row for {peer_install_id!r} holds no credential")
        if not record.endpoints:
            raise ConnectionError(
                f"the peer row for {peer_install_id!r} names no endpoint to dial"
            )

        from ..gateway_identity import read_install_identity

        identity = read_install_identity(root)
        if not identity.ok or not identity.install_id:
            raise ConnectionError(
                "this root has no install identity, so it cannot name itself to a peer"
            )
        dial = cls(root, peer_install_id, record, str(verifier), identity)
        dial.advertise()
        return dial

    def advertise(self) -> None:
        """What THIS root advertises about itself, best-effort.

        Read here rather than threaded in by every caller: a dial that could not
        answer "where am I reachable" would silently stop refreshing the far
        side's cache, and the symptom would be a peer that can call us until it
        reboots.
        """

        try:
            from ..gateway_tls import read_certificate

            certificate = read_certificate(self.root)
            self.self_fingerprint = certificate.fingerprint if certificate.ok else None
        except Exception:
            self.self_fingerprint = None
        try:
            from ..gateway_endpoints import _candidate_endpoints

            self.self_endpoints = _candidate_endpoints(self.root)
        except Exception:
            self.self_endpoints = []

    def candidates(self) -> list[dict[str, Any]]:
        """**Cache endpoints FIRST, then the trust row's** (S2c, R-IP14).

        The cache holds what the peer said most recently — on its last hello, or
        in an announce after it changed networks — and the trust row holds what
        it said at pairing time. Trying the fresher one first is what lets a
        laptop that moved keep working without an operator re-running a
        ceremony; keeping the pairing-time one as a fallback is what stops a bad
        announce from cutting an edge that still works at its old address.

        **The PIN is always the trust row's** (:meth:`attempt`), whichever list
        the address came from. An announced fingerprint is a notice
        (``fingerprint_rotation``) an operator reads, never a value a dial
        adopts: a peer that could nominate the certificate it is checked against
        could become a different machine, which is the one thing pinning exists
        to prevent.
        """

        cached = read_peer_cache(self.root).get(self.record.peer_install_id)
        candidates: list[dict[str, Any]] = []
        for endpoint in (cached.endpoints if cached is not None else ()) + self.record.endpoints:
            row = {"host": str(endpoint["host"]), "port": int(endpoint["port"])}
            if row not in candidates:
                candidates.append(row)
        return candidates

    def attempts(
        self, candidates: list[dict[str, Any]], client: str, timeout_seconds: float
    ) -> tuple[Any, dict[str, Any]] | None:
        """The first handshake that succeeds wins; every failure is recorded."""

        for endpoint in candidates:
            answered = self.attempt(endpoint, client, timeout_seconds)
            if answered is not None:
                return answered
        return None

    def attempt(
        self, endpoint: dict[str, Any], client: str, timeout_seconds: float
    ) -> tuple[Any, dict[str, Any]] | None:
        """One candidate: connect with the trust row's pin, say hello, check it."""

        from ..serve_socket.client import ServeSocketClient

        address = f"{endpoint['host']}:{endpoint['port']}"
        connection = ServeSocketClient(
            str(endpoint["host"]),
            int(endpoint["port"]),
            timeout_seconds=timeout_seconds,
            tls=True,
            cert_fingerprint=self.record.cert_fingerprint,
        )
        try:
            connection.connect()
            reply = connection.peer_hello(
                peer_install_id=self.identity.install_id,
                verifier=self.verifier,
                client=client,
                # S2c: this root's own current facts, so the FAR side's cache is
                # refreshed by every hello rather than only by a re-``join``.
                # Optional on the frame and ignored by a peer that predates
                # them, which is what makes the refresh additive.
                display_name=self.identity.display_name,
                endpoints=self.self_endpoints,
                cert_fingerprint=self.self_fingerprint,
            )
        except Exception as exc:
            word = _dial_failure_word(exc, str(endpoint["host"]))
            if word == LOCAL_POLICY:
                self.policy_refused.append(address)
            self.failures.append(f"{address} {word}")
            connection.close()
            return None
        if not isinstance(reply, dict) or reply.get("event") != "hello_ok":
            self.failures.append(f"{address} {(reply or {}).get('reason') or 'no hello_ok'}")
            connection.close()
            return None
        return connection, reply

    def outcome(self, answered: tuple[Any, dict[str, Any]] | None) -> tuple[Any, dict[str, Any]]:
        """Record reachability either way; answer the connection or raise."""

        if answered is not None:
            note_dial_result(self.root, self.record.peer_install_id, ok=True)
            return answered
        detail = "; ".join(self.failures)
        # R-D20: the word LEADS, so ``gateway.peer.reachability`` carries
        # ``local_policy …`` rather than a bare ``OSError`` and a subscriber can
        # tell a permission on THIS machine apart from a peer that is down. Same
        # shape as the ``peers join`` refusal notes, deliberately — one edge,
        # one vocabulary.
        if self.policy_refused:
            detail = f"{LOCAL_POLICY}: {', '.join(self.policy_refused)}; {detail}"
        note_dial_result(self.root, self.record.peer_install_id, ok=False, error=detail)
        raise ConnectionError(
            f"no endpoint on the {self.peer_install_id!r} row answered: {detail}"
        )
