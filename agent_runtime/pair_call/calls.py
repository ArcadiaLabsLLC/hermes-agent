"""One serve's calls: dial, accept, attach, admit each lane, and the lane's credential check.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST``.

* **Dial** (:meth:`PairCalls.dial`): the machine owner hands this engine the far device's endpoint,
  pin, machine id and install id and this device's credential on it (a device token, held in memory
  only, as ``ComputerWay`` is). A :class:`~.dialer.CallDialer` keeps trying. Each round is a pinned TLS
  dial and this device's own hello naming ``pair_call: {"call", "install"}``; the far side answers
  ``pair_call_accepted`` with its address, checked machine first (``hello_address``) and then its
  install id, before the socket becomes a :class:`~.call.PairCall`.
* **Accept** (:meth:`PairCalls.accept`, the listeners' hello hook): a paired device's hello carrying
  ``pair_call``, after its credential passed the address order (machine, namespace, proof). The socket
  becomes a call; the hello's machine id is the ROW's, so the call's far address is the proven one.
* **Attach** (:meth:`PairCalls.attach`): this machine owner's Eternia on loopback says hello with
  ``call_attach: <far install id>``; a lane opens on the call to that install and Eternia's socket is
  bridged onto it, unread. Eternia then runs its own hello over the lane, answered by the far engine.
* **Admit** (:meth:`PairCalls._on_lane_open`): a lane the far side opened is admitted here as one more
  connection, through a socket pair, by a listener-less admitter whose check is
  :func:`call_lane_authenticator`: the lane's caller proves its OWN credential, bound to the call and
  lane ids — so carrying two directions on one socket admits nobody new.

The wire reasons stay the reverse lane's two (``reverse_lane_refused`` / ``reverse_lane_absent``): the
reverse lane is one lane of the call, and no new reject word is added to the serve-frame mirror.
"""

from __future__ import annotations

import hmac
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..hello_address import answer_address_refusal, hello_address_refusal, install_address, own_namespace
from ..serve_socket.hello import HelloAuthOutcome
from ..serve_socket.vocabulary import REJECT_BAD_PROOF, REJECT_REVERSE_LANE_ABSENT, REJECT_REVERSE_LANE_REFUSED
from .call import LaneClient, PairCall, _close_quietly
from .dialer import CallDialer
from .envelope import ID_PATTERN, MISMATCH_INSTALL, Endpoint, mint_id
from .registry import CallRegistry

__layer__ = "lanes"

__all__ = ["CallWay", "LaneBinding", "PairCalls", "call_lane_authenticator", "lane_device_hello"]

_DIAL_TIMEOUT = 10.0
_CLIENT_NAME = "hermes-pair-call"
_ID_LIMIT = 128
#: The hello fields a lane's caller may not carry: each names another credential or another lane.
_FOREIGN = ("pairing_code", "peer_code", "peer_install_id", "reverse_lane", "reverse_attach", "pair_call",
            "call_attach")


@dataclass(frozen=True, slots=True)
class CallWay:
    """How this engine reaches one of your other devices. The token is never written or logged."""

    host: str
    port: int
    cert_fingerprint: str
    machine_id: str
    install_id: str
    device_id: str
    token: str

    def __repr__(self) -> str:
        return f"CallWay(host={self.host!r}, port={self.port!r}, install_id={self.install_id!r})"


@dataclass(frozen=True, slots=True)
class LaneBinding:
    """What a lane's hello proof is bound to: the call, the lane, and the call's proven far end."""

    call_id: str
    lane_id: str
    far: Endpoint


def own_endpoint(store_root: Path | str) -> Endpoint:
    from ..gateway_identity import ensure_install_identity

    machine = install_address().get("machine_id") or ""
    return Endpoint(str(machine), own_namespace(), ensure_install_identity(store_root).install_id)


def call_lane_authenticator(store_root: Path | str) -> Callable[[dict[str, Any], str, Any], HelloAuthOutcome]:
    """A lane's caller: a computer holding this phone's grant, or a device paired here, on the far machine."""

    root = Path(store_root)

    def refused(detail: str | None = None) -> HelloAuthOutcome:
        return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF, refusal_detail=detail)

    def authenticate(message: dict[str, Any], nonce: str, binding: Any) -> HelloAuthOutcome:
        if not isinstance(binding, LaneBinding) or any(message.get(name) for name in _FOREIGN):
            return refused()
        from ..reverse_lane import grants as _grants

        device_id = message.get("device_id")
        grant = _grants.lookup_grant(root, device_id)
        if grant is not None:
            # This engine is a phone and the caller a computer it granted: that computer, on this call.
            if grant.computer_install_id != binding.far.install_id:
                return refused()
            address = hello_address_refusal(message, row_machine_id=grant.machine_id)
            if address is not None:
                return refused(address)
            proved = _grants.verify_lane_proof(root, device_id, message.get("proof"), nonce,
                                               lane_id=binding.lane_id)
            if proved is None:
                return refused()
            return HelloAuthOutcome(ok=True, computer_id=proved.computer_id, computer_grant=proved.level,
                                    machine_id=proved.machine_id)
        return _device_on_lane(root, message, nonce, binding, refused)

    return authenticate


def _device_on_lane(root: Path, message: dict[str, Any], nonce: str, binding: LaneBinding,
                    refused: Callable[..., HelloAuthOutcome]) -> HelloAuthOutcome:
    from ..call_authorization import DEVICE_KIND_CHANNEL
    from ..serve_gateway_auth import lookup_device
    from ..serve_gateway_auth.proof import call_lane_proof_from_verifier
    from ..serve_gateway_auth.store import read_devices

    device_id = str(message.get("device_id") or "").strip()
    row = lookup_device(root, device_id)
    if row is None or row.kind == DEVICE_KIND_CHANNEL:
        return refused()
    address = hello_address_refusal(message, row_machine_id=row.machine_id)
    if address is not None:
        return refused(address)
    if row.machine_id != binding.far.machine_id:
        # A device of yours, but not on the machine at the other end of THIS call.
        return refused()
    raw = read_devices(root).get(device_id)
    verifier = str(raw.get("verifier") or "").strip() if isinstance(raw, dict) else ""
    presented = message.get("proof")
    if not verifier or not isinstance(presented, str) or not nonce:
        return refused()
    expected = call_lane_proof_from_verifier(verifier, nonce, call_id=binding.call_id, lane_id=binding.lane_id,
                                             device_id=device_id)
    if not hmac.compare_digest(presented.strip().lower().encode("utf-8", "replace"), expected.encode("ascii")):
        return refused()
    if row.revoked or row.expired:
        return refused()
    return HelloAuthOutcome(ok=True, device_id=row.device_id, device_tier=row.tier, device_kind=row.kind,
                            bound_instances=row.bound_instances, machine_id=row.machine_id)


def lane_device_hello(client: LaneClient, *, call: PairCall, device_id: str, token: str,
                      timeout: float = 10.0) -> dict[str, Any] | None:
    """This engine's own hello on a lane it opened, as the device it is paired as on the far side."""

    from ..hello_address import hello_fields
    from ..serve_gateway_auth.proof import call_lane_proof

    challenge = client.next_frame(timeout)
    if not isinstance(challenge, dict) or challenge.get("event") != "server_hello":
        return challenge
    nonce = str(challenge.get("nonce") or "")
    client.send({"op": "hello", "client": _CLIENT_NAME, "device_id": device_id, **hello_fields(),
                 "proof": call_lane_proof(token, nonce, call_id=call.call_id, lane_id=client.lane_id,
                                          device_id=device_id)})
    return client.next_frame(timeout)


class PairCalls:
    """The serve's calls, both ways: its registry, its dialers and its lane admitter."""

    def __init__(self, store_root: Path | str, *, admitter_factory: Callable[[], Any] | None = None,
                 log: Callable[[dict[str, Any]], None] | None = None,
                 dialer_options: dict[str, Any] | None = None) -> None:
        self._store_root = Path(store_root)
        self._admitter_factory = admitter_factory
        self._log = log
        self._dialer_options = dict(dialer_options or {})
        self._lock = threading.Lock()
        self._admitter: Any = None
        self._dialers: dict[str, CallDialer] = {}
        self._closed = False
        self.registry = CallRegistry(log=log)
        self._own: Endpoint | None = None

    @property
    def own(self) -> Endpoint:
        if self._own is None:
            self._own = own_endpoint(self._store_root)
        return self._own

    # ── dial ────────────────────────────────────────────────────────────────

    def dial(self, way: CallWay) -> dict[str, Any]:
        """Keep trying to call *way*'s device until :meth:`hangup`, from this side."""

        with self._lock:
            if self._closed:
                return {"ok": False, "reason": "draining"}
            old = self._dialers.pop(way.install_id, None)
        if old is not None:
            old.stop("redialed")
        dialer = CallDialer(self.registry, way.install_id, lambda: self.dial_once(way), **self._dialer_options)
        with self._lock:
            self._dialers[way.install_id] = dialer
        dialer.start()
        return {"ok": True, "far_install": way.install_id}

    def hangup(self, far_install: str | None = None) -> int:
        with self._lock:
            if far_install is None:
                stopping = list(self._dialers.values())
                self._dialers.clear()
            else:
                one = self._dialers.pop(str(far_install), None)
                stopping = [one] if one is not None else []
        for dialer in stopping:
            dialer.stop()
            call = self.registry.get(dialer.far_install)
            if call is not None:
                call.close("hung_up")
        return len(stopping)

    def dial_once(self, way: CallWay) -> Any:
        """One dial: the held :class:`PairCall`, ``stop:<reason>``, or a word to back off on."""

        from ..serve_socket.client import ServeSocketClient
        from ..serve_socket.hello import ServeCertificatePinMismatch, ServeHelloProtocolError

        call_id = mint_id()
        own = self.own
        client = ServeSocketClient(way.host, int(way.port), timeout_seconds=_DIAL_TIMEOUT, tls=True,
                                   cert_fingerprint=way.cert_fingerprint)
        try:
            client.connect()
            reply = client.device_hello(device_id=way.device_id, token=way.token, client=_CLIENT_NAME,
                                        pair_call={"call": call_id, "install": own.install_id})
        except ServeCertificatePinMismatch:
            client.close()
            return "stop:certificate_rejected"
        except ServeHelloProtocolError:
            client.close()
            return "refused"
        except (OSError, ValueError):
            client.close()
            return "unreachable"
        if not isinstance(reply, dict) or reply.get("event") != "pair_call_accepted" or reply.get("call") != call_id:
            client.close()
            reason = reply.get("reason") if isinstance(reply, dict) else None
            return f"refused:{reason}" if reason else "refused"
        # After the pin, before the call is used: machine, namespace, then the install id.
        address = answer_address_refusal(reply, expect_machine_id=way.machine_id)
        install = reply.get("install") if isinstance(reply.get("install"), dict) else {}
        if address is None and install.get("install_id") != way.install_id:
            address = MISMATCH_INSTALL
        if address is not None:
            client.close()
            return f"stop:{address}"
        sock, ahead = client.detach()
        far = Endpoint(way.machine_id, own.namespace, way.install_id)
        call = PairCall(sock, call_id=call_id, dialer_install=own.install_id, own=own, far=far, outbound=True,
                        initial=ahead, on_lane_open=self._on_lane_open, log=self._log)
        call.start()
        self.registry.add(call)
        return call

    # ── accept and attach (the hello hook) ──────────────────────────────────

    def accept(self, connection: Any, reader: Any, offer: Any) -> str | None:
        """A paired device's hello that names ``pair_call``: its socket becomes a call. A refusal, or None."""

        if not isinstance(offer, dict):
            return REJECT_REVERSE_LANE_REFUSED
        call_id, install = offer.get("call"), offer.get("install")
        if not isinstance(call_id, str) or not ID_PATTERN.match(call_id):
            return REJECT_REVERSE_LANE_REFUSED
        if not isinstance(install, str) or not install.strip() or len(install) > _ID_LIMIT:
            return REJECT_REVERSE_LANE_REFUSED
        with self._lock:
            if self._closed:
                return REJECT_REVERSE_LANE_REFUSED
        own = self.own
        if install == own.install_id or not connection.machine_id:
            return REJECT_REVERSE_LANE_REFUSED
        # The far machine is the credential row's (the hello was refused unless it named it).
        far = Endpoint(str(connection.machine_id), str(connection.namespace or own.namespace), install)
        try:
            connection.emit({"event": "pair_call_accepted", "call": call_id,
                             "install": {**install_address(), "install_id": own.install_id}})
        except Exception:
            return REJECT_REVERSE_LANE_REFUSED
        call = PairCall(connection.sock, call_id=call_id, dialer_install=install, own=own, far=far,
                        outbound=False, initial=reader.take_buffered(), on_lane_open=self._on_lane_open,
                        log=self._log)
        call.far_device_id = connection.device_id
        call.start()
        self.registry.add(call)
        return None

    def attach(self, connection: Any, reader: Any, far_install: Any) -> str | None:
        """The machine owner's Eternia onto a new lane of the call to *far_install*."""

        call = self.registry.get(str(far_install or ""))
        if call is None:
            return REJECT_REVERSE_LANE_ABSENT
        try:
            lane_id = call.open_lane("eternia")
            connection.sock.settimeout(None)
            connection.emit({"event": "call_attached", "call": call.call_id, "lane_id": lane_id,
                             "install": call.far.describe()})
        except Exception:
            return REJECT_REVERSE_LANE_ABSENT
        call.bridge(lane_id, connection.sock, reader.take_buffered())
        return None

    # ── lanes the far side opens ────────────────────────────────────────────

    def admitter(self) -> Any:
        with self._lock:
            if self._admitter is None:
                if self._admitter_factory is None:
                    raise RuntimeError("this serve has no call lane admitter")
                self._admitter = self._admitter_factory()
            return self._admitter

    def _on_lane_open(self, call: PairCall, lane_id: str, purpose: str) -> None:
        admitter = self.admitter()
        near, far = socket.socketpair()
        call.bridge(lane_id, near)
        binding = LaneBinding(call.call_id, lane_id, call.far)

        def serve() -> None:
            try:
                admitter.admit(far, ("pair-call", call.far.install_id), binding=binding)
            finally:
                _close_quietly(far)

        threading.Thread(target=serve, name="pair-call-admit", daemon=True).start()

    # ── both ────────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        with self._lock:
            dialers = [dialer.status() for dialer in self._dialers.values()]
        return {"calls": self.registry.describe(), "dialing": dialers}

    def close(self, reason: str = "shutdown") -> None:
        with self._lock:
            self._closed = True
            dialers = list(self._dialers.values())
            self._dialers.clear()
            admitter, self._admitter = self._admitter, None
        for dialer in dialers:
            dialer.stop(reason)
        for dialer in dialers:
            dialer.join(2.0)
        self.registry.close(reason)
        if admitter is not None:
            admitter.close(reason)
