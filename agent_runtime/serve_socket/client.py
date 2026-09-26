"""``ServeSocketClient`` — the client half: connect, TLS wrap, the four hello
kinds, framed send/read.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from typing import Any

from agent_runtime.serve_socket.vocabulary import NONCE_BYTES
from agent_runtime.serve_socket.hello import (
    HELLO_CONTRACT_VERSION,
    ServeCertificatePinMismatch,
    ServeHelloProtocolError,
    hello_proof,
)
from agent_runtime.serve_socket.wire import _LineReader, _parse_object

__layer__ = "lanes"

__all__ = [
    "_add_peer_assertions",
    "ServeSocketClient",
]


class ServeSocketClient:
    """The other end of the handshake: connect, hello, then read frames.

    Deliberately small and dependency-free — it is the reference client the CLI
    probe verb uses, and the shape the Launcher's own client will mirror when it
    migrates off the stdio child.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_seconds: float = 10.0,
        tls: bool = False,
        cert_fingerprint: str | None = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout_seconds)
        #: Off by default — the loopback lane is plaintext and stays that way.
        #: On for the gateway lane, where the client trusts NO certificate
        #: authority and pins instead (R1).
        self._tls = bool(tls) or cert_fingerprint is not None
        self._cert_fingerprint = (
            str(cert_fingerprint).strip().lower() if cert_fingerprint else None
        )
        self._sock: socket.socket | None = None
        self._reader: _LineReader | None = None
        #: The challenge frame this connection was greeted with, once
        #: :meth:`hello` has read it. Kept so a caller can report the contract
        #: and boot id it actually answered — not re-read, and never a place
        #: the token is stored.
        self.server_hello: dict[str, Any] | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        sock.settimeout(self._timeout)
        if self._tls:
            sock = self._wrap_tls(sock)
        self._sock = sock
        self._reader = _LineReader(sock)

    def _wrap_tls(self, sock: socket.socket) -> Any:
        """Negotiate TLS and PIN the certificate. The reference pinning path.

        There is no CA and no hostname to check: the install's certificate is
        self-signed and the address is whatever the operator's LAN gave the
        machine, so both of the usual checks would fail on a link that is
        exactly as it should be. What replaces them is a fingerprint the client
        was given out of band — through the pairing payload — and comparing it
        is not optional decoration: without it the encryption stops any
        eavesdropper and stops no impostor, and the pairing payload's
        ``cert_fingerprint`` field would be a value nobody uses.

        Written here rather than only in a test because this class is the
        reference client — the shape the launcher's own connector mirrors, where
        the same comparison lives inside ``badCertificateCallback``.
        """

        import ssl

        from agent_runtime.gateway_tls import stdlib_ssl_context

        def configure(context: ssl.SSLContext) -> None:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        context = stdlib_ssl_context(ssl.PROTOCOL_TLS_CLIENT, configure)
        wrapped = context.wrap_socket(sock, server_hostname=None)
        if self._cert_fingerprint is not None:
            presented = wrapped.getpeercert(binary_form=True) or b""
            actual = hashlib.sha256(presented).hexdigest()
            if not hmac.compare_digest(
                actual.encode("ascii"), self._cert_fingerprint.encode("ascii")
            ):
                try:
                    wrapped.close()
                except OSError:
                    pass
                raise ServeCertificatePinMismatch(
                    "the peer's certificate does not match the pinned fingerprint"
                )
        wrapped.settimeout(self._timeout)
        return wrapped

    def hello(
        self,
        *,
        token: str,
        client: str,
        client_build: str | None = None,
        expect_hello_contract: int | None = HELLO_CONTRACT_VERSION,
    ) -> dict[str, Any] | None:
        """Answer the server's challenge and return the single reply frame.

        The SERVER speaks first, so this reads before it writes: one
        ``server_hello`` carrying the nonce, then the proof. **The token never
        goes on the wire** — it is the HMAC key, it is not logged, not echoed
        into the returned frame, and not retained on this object. A transcript
        of this exchange authenticates nobody: the nonce is fresh per
        connection, so a replayed proof is a proof over the wrong challenge.

        Anything other than a well-formed ``server_hello`` raises
        :class:`ServeHelloProtocolError` with the offending frame attached
        rather than pressing on: the two ways that happens are a service that
        refused us before the challenge (its ``hello_rejected`` reason is the
        answer) and something on this port that is not this service — and
        neither is a case where sending a credential is the right next move.
        """

        nonce = self._challenge_nonce(expect_hello_contract)
        self.send(
            {
                "op": "hello",
                "client": client,
                "client_build": client_build,
                # `self._port` — the port THIS client dialled, taken from its
                # own socket rather than from anything the greeting claims. A
                # relay that forwards our answer to a different port cannot
                # use it.
                "proof": hello_proof(token, nonce, port=self._port),
            }
        )
        return self.read_frame()

    def device_hello(
        self,
        *,
        device_id: str,
        token: str,
        client: str,
        client_build: str | None = None,
        expect_hello_contract: int | None = HELLO_CONTRACT_VERSION,
    ) -> dict[str, Any] | None:
        """The GATEWAY lane's hello: same frames, a per-device credential.

        Structurally identical to :meth:`hello` — server speaks first, one
        ``server_hello`` carrying a fresh nonce, one answer carrying a proof —
        and that sameness is the point: the gateway lane is this contract made
        reachable beyond loopback, not a second protocol. The two differences
        are that the frame NAMES a device (so the server knows which key to
        recompute with) and that the proof derivation binds that name
        (``serve_gateway_auth.device_proof``).

        The device token never goes on the wire, in either direction — and it is
        not even the HMAC key: its digest is, so the value on this device and
        the value in the install's store are different bytes. See
        ``serve_gateway_auth``'s docstring for the honest limit of that.
        """

        from ..serve_gateway_auth import device_proof

        nonce = self._challenge_nonce(expect_hello_contract)
        self.send(
            {
                "op": "hello",
                "client": client,
                "client_build": client_build,
                "device_id": device_id,
                # `self._port` again — the port THIS client dialled, from its own
                # socket rather than from anything the greeting claims.
                "proof": device_proof(
                    token, nonce, port=self._port, device_id=device_id
                ),
            }
        )
        return self.read_frame()

    def peer_hello(
        self,
        *,
        peer_install_id: str,
        verifier: str,
        client: str,
        client_build: str | None = None,
        display_name: str | None = None,
        endpoints: Any = None,
        cert_fingerprint: str | None = None,
        expect_hello_contract: int | None = HELLO_CONTRACT_VERSION,
    ) -> dict[str, Any] | None:
        """The GATEWAY lane's PEER hello: same frames, a per-INSTALL credential.

        Structurally identical to :meth:`hello` and :meth:`device_hello`, and
        that sameness is again the point — Stage 6 is not a third protocol.
        Two things differ, and both are what keep the credentials from being
        interchangeable: the frame names ``peer_install_id`` where a device
        names ``device_id`` (so the server knows which store to look in as well
        as which key to recompute with), and the derivation carries a different
        prefix (``gateway_peers.peer_proof``).

        ``verifier`` — ``sha256(secret)`` — is what a paired install actually
        holds; see ``gateway_peers``' docstring for why both ends store the
        digest and key the HMAC with it directly, and for the honest limit of
        that. It never goes on the wire, in either direction.

        **S2c adds three OPTIONAL fields and they are not credentials.**
        ``peer_display_name`` / ``peer_endpoints`` / ``peer_cert_fingerprint``
        are the same three the JOIN hello has always carried, on the ordinary
        hello too, so the far side's CACHE is refreshed by every connection
        rather than only by a re-``join``. Before this, an install that changed
        networks became unreachable until an operator re-ran a ceremony they had
        no reason to suspect was needed.

        They are ASSERTIONS and are treated as such at the far end: bounded and
        cleaned by ``gateway_peers``, written to ``peers_cache.json``, and never
        to the trust row — in particular the announced fingerprint becomes a
        rotation NOTICE and never the pin. ``_credential_kind`` is untouched,
        because none of the three is a credential and a hello that carries them
        still names exactly one.
        """

        from ..gateway_peers import peer_proof

        nonce = self._challenge_nonce(expect_hello_contract)
        frame: dict[str, Any] = {
            "op": "hello",
            "client": client,
            "client_build": client_build,
            "peer_install_id": peer_install_id,
            # `self._port` again — the port THIS client dialled, from its own
            # socket rather than from anything the greeting claims.
            "proof": peer_proof(
                verifier, nonce, port=self._port, peer_install_id=peer_install_id
            ),
        }
        # Omitted rather than sent as null when a caller has nothing to say, so
        # a hello from a client that does not know these keys and a hello from
        # one that has no address to offer are the same bytes.
        _add_peer_assertions(frame, display_name, endpoints, cert_fingerprint)
        self.send(frame)
        return self.read_frame()

    def peer_join_hello(
        self,
        *,
        peer_code: str,
        peer_install_id: str,
        display_name: str | None = None,
        endpoints: Any = None,
        cert_fingerprint: str | None = None,
        client: str = "hermes-peer",
        client_build: str | None = None,
        expect_hello_contract: int | None = HELLO_CONTRACT_VERSION,
    ) -> dict[str, Any] | None:
        """Redeem a PEER code and become a paired install, in one round trip.

        The ceremony's second half and the mirror of :meth:`pair_hello`. What is
        different is the direction the facts flow: a phone redeeming a device
        code tells the install nothing about itself worth storing, while a
        joining INSTALL must tell the other side who it is (``peer_install_id``),
        what to call it, where to dial it back, and what certificate to pin —
        because the edge is symmetric and the other install will one day be the
        one dialling.

        Those four fields are ASSERTIONS by the joining side, and are treated as
        such: the server bounds and cleans them (``gateway_peers.clean_endpoints``)
        and stores them as a starting point rather than as a proof. What makes
        them trustworthy is not the wire — it is that an operator at the other
        machine minted the code seconds earlier and is standing there. That is
        R5's "both sides", and it is the only thing that makes the assertion
        safe to keep.

        No proof is computed and none is possible: the code IS the credential for
        this one exchange, exactly as in the device ceremony, protected by the
        same three properties (a pinned TLS link, a one-shot code deleted before
        the secret is minted, and a failed redeem that looks like every other
        credential failure and charges the same limiter).

        A caller MUST store ``hello_ok["peered"]["peer_secret"]``: the remote
        install keeps only a digest of it and cannot reissue it, so a client that
        drops the frame has paired an edge it can never use.
        """

        self._challenge(expect_hello_contract)
        frame: dict[str, Any] = {
            "op": "hello",
            "client": client,
            "client_build": client_build,
            # A DIFFERENT key from the device ceremony's ``pairing_code``, and
            # deliberately: the two codes redeem into different stores, and a
            # shared field name is the one thing that could make a server's
            # branch pick the wrong one.
            "peer_code": str(peer_code).strip().upper(),
            "peer_install_id": peer_install_id,
        }
        _add_peer_assertions(frame, display_name, endpoints, cert_fingerprint)
        self.send(frame)
        return self.read_frame()

    def _challenge(self, expect_hello_contract: int | None) -> dict[str, Any]:
        """Read and validate the ``server_hello``. The common half of four hellos.

        Extracted when Stage 6 added the fourth and fifth: the same fifteen
        lines had been copied per hello, and a fifth copy is how one of them
        eventually stops checking the contract. The validation is unchanged —
        anything that is not a well-formed ``server_hello`` RAISES with the
        offending frame attached rather than pressing on, because the two ways
        that happens (a service that refused us before the challenge, and
        something on this port that is not this service) are both cases where
        sending a credential is the wrong next move.
        """

        greeting = self.read_frame()
        if not isinstance(greeting, dict) or greeting.get("event") != "server_hello":
            raise ServeHelloProtocolError(
                "the peer did not open with a server_hello challenge", frame=greeting
            )
        contract = greeting.get("hello_contract")
        if expect_hello_contract is not None and contract != expect_hello_contract:
            raise ServeHelloProtocolError(
                f"unsupported hello_contract {contract!r} "
                f"(this client speaks {expect_hello_contract})",
                frame=greeting,
            )
        self.server_hello = greeting
        return greeting

    def _challenge_nonce(self, expect_hello_contract: int | None) -> str:
        """:meth:`_challenge`, then the nonce the three proof-carrying hellos sign.

        A greeting without a usable nonce RAISES with the frame attached, for the
        reason :meth:`_challenge` gives: sending a credential is the wrong move.
        """

        greeting = self._challenge(expect_hello_contract)
        nonce = greeting.get("nonce")
        if not isinstance(nonce, str) or len(nonce) < 2 * NONCE_BYTES:
            raise ServeHelloProtocolError(
                "server_hello carried no usable nonce", frame=greeting
            )
        return nonce

    def pair_hello(
        self,
        *,
        pairing_code: str,
        client: str,
        client_build: str | None = None,
        expect_hello_contract: int | None = HELLO_CONTRACT_VERSION,
    ) -> dict[str, Any] | None:
        """Redeem a pairing code and become a device, in one round trip.

        The only exchange in this lane where the client presents something it
        was given out of band — eight characters off the operator's terminal —
        and the only reply that carries a secret. A caller MUST store
        ``hello_ok["paired"]["device_token"]``: the install keeps a digest of it
        and cannot reissue it, so a client that drops the frame has paired a
        device it can never be again.

        No proof is computed and none is possible: the code IS the credential
        for this one exchange. What protects it is the pinned TLS link it rides
        (an impostor cannot receive it), its one-shot nature (redeemed, it is
        deleted before the token is minted), and the store's lockout.
        """

        self._challenge(expect_hello_contract)
        self.send(
            {
                "op": "hello",
                "client": client,
                "client_build": client_build,
                "pairing_code": str(pairing_code).strip().upper(),
            }
        )
        return self.read_frame()

    def send(self, message: dict[str, Any]) -> None:
        if self._sock is None:
            raise RuntimeError("connect() first")
        payload = json.dumps(message, ensure_ascii=False, default=str) + "\n"
        self._sock.sendall(payload.encode("utf-8"))

    def set_timeout(self, seconds: float) -> None:
        """Re-arm the socket timeout after the handshake.

        Gateway Stage 7 needs the DIAL and the READ to be bounded differently,
        and they are different questions. R8's "bounded per-attempt dial
        timeout" is about how long to wait for an install that may simply be
        off — seconds, because an unreachable peer should converge rather than
        hang. Waiting for a chat TURN to finish on that install is a wall
        budget the sender chose, measured in minutes, and reusing the dial's
        number for it would kill every remote turn that took longer than a
        handshake.

        Deliberately a method rather than a second constructor argument: the
        value that matters changes at a moment (the ack), not at construction,
        and a client with two timeouts baked in would still have to be told
        when to switch.
        """

        self._timeout = float(seconds)
        if self._sock is not None:
            self._sock.settimeout(self._timeout)

    def read_frame(self) -> dict[str, Any] | None:
        if self._reader is None:
            raise RuntimeError("connect() first")
        while True:
            line = self._reader.read_line(deadline_seconds=None)
            if line is None:
                return None
            if not line.strip():
                continue
            return _parse_object(line)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        self._reader = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def __enter__(self) -> "ServeSocketClient":
        self.connect()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _add_peer_assertions(
    frame: dict[str, Any],
    display_name: str | None,
    endpoints: Any,
    cert_fingerprint: str | None,
) -> None:
    """The peer hellos' three optional ASSERTIONS, each omitted rather than null.

    A hello from a client that does not know these keys and a hello from one that
    has no address to offer are then the same bytes (see :meth:`ServeSocketClient.peer_hello`).
    """

    if display_name:
        frame["peer_display_name"] = display_name
    if endpoints:
        frame["peer_endpoints"] = endpoints
    if cert_fingerprint:
        frame["peer_cert_fingerprint"] = cert_fingerprint
