"""The phone's listener for the call: open while its Eternia is in front and signed in, for your computers only.

Row ``RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-ETERNIA-IS-IN-FRONT`` (step (7) of
``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST``). Both of your devices
try to call each other (owner 2026-11-23: "shouldn't they both try to call"); a phone listens too, whenever its
Eternia asks: in front and signed in (``runtime.gateway.call.listen``), and closed when it leaves the front, on
sign-out and on an account change (``runtime.gateway.call.unlisten``). Eternia decides when; this module owns
the door.

**Who gets in.** ONE hello: a computer holding a grant this phone minted for it
(``agent_runtime.reverse_lane.grants``), naming ``pair_call``. Checked in address order — the grant's machine id
first, then this namespace (``hello_address``) — and only then the grant's proof, bound to this listener's port
(``serve_gateway_auth.proof.grant_dial_proof``). No pairing code, peer code, peer credential, device credential,
reverse lane, attach or unauthenticated op is served here: every other hello is the one ``bad_proof`` refusal,
charged to the listener's rate limiter like the desktop gateway's. An admitted hello is never served as a
connection: the hook turns it into the call (:meth:`~.calls.PairCalls.accept_granted`) or refuses it, so the
only thing a computer reaches through this door is the call, whose every lane proves its own caller again.

**The certificate** is the desktop gateway's mint (``agent_runtime/gateway_tls.py``), which needs
``cryptography``: on phones Flet's 48.0.0, under the desktop's floor, by the one phone-only exception
(``scripts/bundles/phone_wheels.py`` ``PHONE_ONLY_VERSION_EXCEPTIONS``, owner RULED 2026-11-24).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from ..hello_address import hello_address_refusal
from ..serve_socket.hello import HelloAuthOutcome
from ..serve_socket.vocabulary import REJECT_BAD_PROOF, REJECT_REVERSE_LANE_REFUSED

__layer__ = "lanes"

__all__ = ["GrantListener", "grant_listener_authenticator"]

#: The hello fields that name another credential or another lane: never answered on a phone's listener.
_FOREIGN = ("pairing_code", "peer_code", "peer_install_id", "reverse_lane", "reverse_attach", "call_attach")
#: Where a phone listens when Eternia names no address: every interface, so a computer on your network reaches it.
DEFAULT_HOST = "0.0.0.0"


def grant_listener_authenticator(store_root: Path | str) -> Callable[[dict[str, Any], str, Any], HelloAuthOutcome]:
    """The listener's one credential: a computer holding this phone's grant, on the grant's machine."""

    root = Path(store_root)

    def refused(detail: str | None = None) -> HelloAuthOutcome:
        return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF, refusal_detail=detail)

    def authenticate(message: dict[str, Any], nonce: str, port: Any) -> HelloAuthOutcome:
        # MUTATION: answer through the desktop gateway's table (serve_gateway_credentials.authenticate_hello)
        # and test_phone_listener's pairing-code test is admitted.
        if any(message.get(name) for name in _FOREIGN) or not isinstance(message.get("pair_call"), dict):
            return refused()
        from ..reverse_lane import grants as _grants

        computer_id = message.get("device_id")
        grant = _grants.lookup_grant(root, computer_id)
        if grant is None:
            return refused()
        # Address order: the grant's machine, then this namespace, and only then the proof.
        # MUTATION: run this after the proof and test_phone_listener's other-machine test sees the proof read.
        address = hello_address_refusal(message, row_machine_id=grant.machine_id)
        if address is not None:
            return refused(address)
        proved = _grants.verify_dial_proof(root, computer_id, message.get("proof"), nonce, port=port)
        if proved is None:
            return refused()
        return HelloAuthOutcome(ok=True, computer_id=proved.computer_id, computer_grant=proved.level,
                                machine_id=proved.machine_id)

    return authenticate


class GrantListener:
    """One serve's phone listener: opened and closed on its Eternia's word, never by itself."""

    def __init__(self, store_root: Path | str, *, accept: Callable[[Any, Any, Any], str | None],
                 boot_id: str = "pair-call-listener", frame_contract: int = 1,
                 log: Callable[[dict[str, Any]], None] | None = None,
                 server_options: dict[str, Any] | None = None) -> None:
        self._store_root = Path(store_root)
        self._accept = accept
        self._boot_id = boot_id
        self._frame_contract = frame_contract
        self._log = log
        self._server_options = dict(server_options or {})
        self._lock = threading.Lock()
        self._server: Any = None
        self._block: dict[str, Any] | None = None

    def open(self, *, host: str = DEFAULT_HOST, port: int = 0) -> dict[str, Any]:
        """Listen (again, if the address changed). The ``listening`` block, or an ``error:*`` one."""

        with self._lock:
            if self._server is not None and self._block is not None and self._block.get("host") == host \
                    and (port == 0 or self._block.get("port") == port):
                return dict(self._block)
        self.close("relisten")
        from ..gateway_tls import ensure_certificate, server_ssl_context
        from ..serve_socket.server import ServeSocketServer

        certificate = ensure_certificate(self._store_root)
        if not certificate.ok:
            # A door that cannot encrypt does not open (the desktop gateway's rule, R1).
            return {"outcome": f"error:{certificate.state}", "host": host, "port": port}
        try:
            server = ServeSocketServer(
                self._store_root, boot_id=self._boot_id, dispatch_line=_never_served,
                hello_payload=lambda message, connection: {"event": "hello_ok"},
                token_provider=lambda: None, authenticator=grant_listener_authenticator(self._store_root),
                ssl_context=server_ssl_context(self._store_root), host=host, port=port, transport_name="gateway",
                frame_contract=self._frame_contract, log=self._log, handoff=self._hook, **self._server_options)
            bound = server.bind()
            server.start_accepting()
        except Exception as exc:
            return {"outcome": f"error:{type(exc).__name__}", "host": host, "port": port}
        block = {"outcome": "listening", "host": host, "port": bound, "cert_fingerprint": certificate.fingerprint}
        with self._lock:
            self._server, self._block = server, block
        return dict(block)

    def close(self, reason: str = "unlisten") -> bool:
        with self._lock:
            server, self._server, self._block = self._server, None, None
        if server is None:
            return False
        server.close(reason)
        return True

    def status(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._block) if self._block is not None else None

    def _hook(self, admitter: Any, connection: Any, reader: Any, message: dict[str, Any]) -> bool:
        """Every admitted hello becomes the call or is refused: nothing here is served as a connection."""

        refusal: str | None = REJECT_REVERSE_LANE_REFUSED
        if connection.computer_id and isinstance(message.get("pair_call"), dict):
            refusal = self._accept(connection, reader, message.get("pair_call"))
        if refusal is not None:
            from ..serve_socket.handshake import reject

            reject(admitter, connection, refusal)
        return True


def _never_served(line: str, connection: Any) -> None:  # pragma: no cover - the hook takes every socket
    return None
