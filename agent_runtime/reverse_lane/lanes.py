"""The serve's reverse lanes, both roles, and the hello hook that parks and attaches them.

**Computer role.** A paired phone dials this install's gateway and says hello with its
device credential and ``reverse_lane: <lane id>``. :func:`handoff` PARKS that connection
by device id instead of serving it. Later the machine owner's Eternia says hello on the
loopback lane with this root's token and ``reverse_attach: <device id>``; :func:`handoff`
answers ``reverse_attached`` with the lane id, tells the phone, and from then on copies
bytes both ways between the two sockets and reads none of them. The computer's Hermes
never becomes a caller on the phone. The lane's TLS ends here, so the splice is trusted as
the machine owner's own process, not by cryptography (review w1118a.79).

**Phone role.** :meth:`ReverseLanes.dial` starts a :class:`~.dialer.ReverseDialer` per
granted computer: the phone opens the connection (D3: it never listens), parks it on the
computer, and when the computer attaches, hands the socket to a listener-less
:class:`~agent_runtime.serve_socket.admit.ConnectionAdmitter`. That runs the ordinary hello
over the lane, verified by :func:`lane_authenticator` against the phone's grant, with the
proof bound to the lane id, and mints a ``computer`` caller whose grant
``call_authorization`` answers from an allowlist.
"""

from __future__ import annotations

import re
import select
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..serve_socket.hello import HelloAuthOutcome
from ..serve_socket.vocabulary import (
    REJECT_BAD_PROOF,
    REJECT_REVERSE_LANE_ABSENT,
    REJECT_REVERSE_LANE_REFUSED,
)
from . import accepts as _accepts
from . import grants as _grants

__layer__ = "lanes"

__all__ = [
    "LANE_ID_PATTERN",
    "MAX_PARKED_LANES",
    "ReverseLanes",
    "handoff",
    "lane_authenticator",
]

#: A lane id: 32 lowercase hex characters, minted by the phone per dial.
LANE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
#: How many phones may hold a parked lane on one computer at once.
MAX_PARKED_LANES = 16
_COPY_CHUNK = 65536
#: The hello fields a computer's hello over a lane may carry besides its id and proof.
_FOREIGN_CREDENTIALS = ("pairing_code", "peer_code", "peer_install_id", "reverse_lane", "reverse_attach")


@dataclass
class _Parked:
    device_id: str
    lane_id: str
    sock: Any
    buffered: bytes
    parked_at: float = field(default_factory=time.time)
    attached: bool = False


def lane_authenticator(store_root: Path | str) -> Callable[[dict[str, Any], str, Any], HelloAuthOutcome]:
    """The phone's lane admitter's credential check: the grant's lane proof, nothing else."""

    def authenticate(message: dict[str, Any], nonce: str, binding: Any) -> HelloAuthOutcome:
        if not isinstance(binding, str) or not LANE_ID_PATTERN.match(binding):
            return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
        if any(message.get(name) for name in _FOREIGN_CREDENTIALS):
            return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
        # MUTATION: verify against the lane id the hello frame claims (`message.get("lane_id")`)
        # instead of `binding` and test_reverse_lane's wrong-lane test admits a proof answered
        # for another lane.
        grant = _grants.verify_lane_proof(store_root, message.get("device_id"), message.get("proof"),
                                          nonce, lane_id=binding)
        if grant is None:
            return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)
        return HelloAuthOutcome(ok=True, computer_id=grant.computer_id, computer_grant=grant.level)

    return authenticate


class ReverseLanes:
    """One serve's reverse lanes: parked and spliced (computer), dialled and admitted (phone)."""

    def __init__(self, store_root: Path | str, *, admitter_factory: Callable[[], Any] | None = None,
                 log: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._store_root = Path(store_root)
        self._admitter_factory = admitter_factory
        self._log = log
        self._lock = threading.Lock()
        self._parked: dict[str, _Parked] = {}
        self._splices: dict[str, tuple[Any, Any]] = {}
        self._admitter: Any = None
        self._dialers: dict[str, Any] = {}
        self._draining = False
        #: Phones' offers this computer's owner has not answered (``accepts``), in memory.
        self.offers = _accepts.ReverseOffers()
        #: When each phone's lane was last here, parked or attached (the Away line's time).
        self._seen: dict[str, float] = {}
        self._remove_listener = _grants.add_revoke_listener(self._grants_revoked)

    @property
    def store_root(self) -> Path:
        return self._store_root

    # ── computer role ───────────────────────────────────────────────────────

    def park(self, connection: Any, reader: Any, lane_id: str) -> str | None:
        """Hold *connection*'s socket as *connection*'s device's lane. A refusal reason, or None."""

        if not isinstance(lane_id, str) or not LANE_ID_PATTERN.match(lane_id):
            return REJECT_REVERSE_LANE_REFUSED
        device_id = str(connection.device_id)
        with self._lock:
            if self._draining:
                return REJECT_REVERSE_LANE_REFUSED
            old = self._parked.pop(device_id, None)
            if old is None and len(self._parked) >= MAX_PARKED_LANES:
                return REJECT_REVERSE_LANE_REFUSED
            self._parked[device_id] = _Parked(device_id, lane_id, connection.sock, reader.take_buffered())
            self._seen[device_id] = time.time()
        if old is not None:
            _close_quietly(old.sock)
        try:
            connection.sock.settimeout(None)
        except OSError:
            pass
        connection.emit({"event": "reverse_lane_parked", "lane_id": lane_id})
        self._emit({"event": "reverse_lane_parked", "device_id": device_id})
        return None

    def attach(self, connection: Any, reader: Any, device_id: str) -> str | None:
        """Splice the owner's *connection* onto *device_id*'s parked lane, on its own thread."""

        from ..serve_gateway_auth import lookup_device

        device_id = str(device_id or "").strip()
        with self._lock:
            parked = self._parked.pop(device_id, None) if device_id else None
        if parked is None:
            return REJECT_REVERSE_LANE_ABSENT
        record = lookup_device(self._store_root, device_id)
        # The grant is bound to the pairing: a device unpaired here since it parked has no lane.
        if record is None or record.revoked or record.expired or not _still_open(parked.sock):
            _close_quietly(parked.sock)
            return REJECT_REVERSE_LANE_ABSENT
        phone, owner = parked.sock, connection.sock
        try:
            owner.settimeout(None)
            phone.sendall(b'{"event":"reverse_attached"}\n')
            connection.emit({"event": "reverse_attached", "lane_id": parked.lane_id, "device_id": device_id})
        except Exception:
            _close_quietly(phone)
            return REJECT_REVERSE_LANE_ABSENT
        with self._lock:
            self._splices[device_id] = (phone, owner)
        self._emit({"event": "reverse_lane_attached", "device_id": device_id})
        owner_ahead = reader.take_buffered()

        def run() -> None:
            try:
                _splice(phone, parked.buffered, owner, owner_ahead)
            finally:
                with self._lock:
                    if self._splices.get(device_id) == (phone, owner):
                        self._splices.pop(device_id, None)
                    self._seen[device_id] = time.time()
                _close_quietly(phone)
                _close_quietly(owner)
                self._emit({"event": "reverse_lane_detached", "device_id": device_id})

        # Its own thread: the hello's thread returns, so the splice never holds a pending slot.
        threading.Thread(target=run, name="reverse-lane-splice", daemon=True).start()
        return None

    def drop_device(self, device_id: str) -> None:
        """Close a device's parked or spliced lane (it was unpaired here)."""

        with self._lock:
            parked = self._parked.pop(device_id, None)
            splice = self._splices.pop(device_id, None)
        if parked is not None:
            _close_quietly(parked.sock)
        for sock in splice or ():
            _close_quietly(sock)

    # ── phone role ──────────────────────────────────────────────────────────

    def admitter(self) -> Any:
        with self._lock:
            if self._admitter is None:
                if self._admitter_factory is None:
                    raise RuntimeError("this serve has no reverse lane admitter")
                self._admitter = self._admitter_factory()
            return self._admitter

    def dial(self, *, computer_install_id: str, host: str, port: int, cert_fingerprint: str,
             device_id: str, token: str) -> dict[str, Any]:
        """Dial a granted computer and keep a lane open to it until :meth:`hangup`."""

        from .dialer import ReverseDialer

        grant = _grants.grant_for_install(self._store_root, computer_install_id)
        if grant is not None and grant.pairing_device_id != str(device_id):
            # A re-pair: the grant was bound to the old pairing, and a new one starts with none.
            _grants.revoke_install_grants(self._store_root, computer_install_id)
            grant = None
        if grant is None:
            return {"ok": False, "reason": "no_grant"}
        with self._lock:
            if self._draining:
                return {"ok": False, "reason": "draining"}
        self.hangup(computer_install_id)
        dialer = ReverseDialer(self, grant=grant, host=host, port=int(port),
                               cert_fingerprint=cert_fingerprint, device_id=str(device_id), token=token)
        with self._lock:
            self._dialers[grant.computer_install_id] = dialer
        dialer.start()
        return {"ok": True, "computer_id": grant.computer_id, "state": dialer.state}

    def hangup(self, computer_install_id: str | None = None) -> int:
        """Stop dialling (one computer, or all) and close the lanes. Returns how many stopped."""

        with self._lock:
            if computer_install_id is None:
                stopping = list(self._dialers.values())
                self._dialers.clear()
            else:
                one = self._dialers.pop(str(computer_install_id), None)
                stopping = [one] if one is not None else []
        for dialer in stopping:
            dialer.stop()
        self._drop_lanes({dialer.computer_id for dialer in stopping}, reason="hung_up")
        return len(stopping)

    def _drop_lanes(self, computer_ids: set[str], *, reason: str) -> None:
        with self._lock:
            admitter = self._admitter
        if admitter is not None and computer_ids:
            admitter.drop_where(lambda c: getattr(c, "computer_id", None) in computer_ids, reason=reason)

    def forget_dialer(self, dialer: Any) -> None:
        with self._lock:
            if self._dialers.get(dialer.computer_install_id) is dialer:
                self._dialers.pop(dialer.computer_install_id, None)

    def _grants_revoked(self, computer_ids: list[str]) -> None:
        gone = set(computer_ids)
        with self._lock:
            stopping = [d for k, d in self._dialers.items() if d.computer_id in gone]
            for dialer in stopping:
                self._dialers.pop(dialer.computer_install_id, None)
        for dialer in stopping:
            dialer.stop("grant_revoked")
        # MUTATION: drop this line and test_reverse_lane's grant-off test keeps the computer connected.
        self._drop_lanes(gone, reason="grant_revoked")

    # ── both ────────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Both roles' state, and no secret: lanes, offers held, phones accepted, grants made.

        A parked lane whose phone hung up (it left the foreground, or pressed Disconnect) is
        evicted here, so the computer reads it Away at once rather than at its next attach.
        """

        with self._lock:
            # MUTATION: skip this eviction and the hang-up test still reads the phone parked.
            ended = [p for p in self._parked.values() if not _still_open(p.sock)]
            for lane in ended:
                self._parked.pop(lane.device_id, None)
                self._seen[lane.device_id] = time.time()
            parked = [{"device_id": p.device_id, "parked_at": p.parked_at} for p in self._parked.values()]
            attached = sorted(self._splices)
            dialers = [d.status() for d in self._dialers.values()]
            seen = dict(self._seen)
        for lane in ended:
            _close_quietly(lane.sock)
        return {
            "parked": parked,
            "attached": attached,
            "dialing": dialers,
            "seen": seen,
            "offers": [self._with_account(offer.describe()) for offer in self.offers.pending()],
            "accepted": [self._with_account(accept.describe())
                         for accept in _accepts.list_accepts(self._store_root)],
            "grants": [{"computer_install_id": g.computer_install_id, "computer_id": g.computer_id,
                        "level": g.level, "pairing_device_id": g.pairing_device_id}
                       for g in _grants.list_grants(self._store_root)],
        }

    def _with_account(self, row: dict[str, Any]) -> dict[str, Any]:
        """The phone's ACCOUNT device id beside its gateway device id: the label Eternia
        joins the row to the account's device list by (``DeviceRecord.account_device_id``)."""

        from ..serve_gateway_auth import lookup_device

        record = lookup_device(self._store_root, row["device_id"])
        account = getattr(record, "account_device_id", None) if record is not None else None
        return {**row, "account_device_id": account}

    def broadcast(self, frame: dict[str, Any]) -> int:
        with self._lock:
            admitter = self._admitter
        return admitter.broadcast(frame) if admitter is not None else 0

    def begin_drain(self) -> None:
        with self._lock:
            self._draining = True
            admitter = self._admitter
        if admitter is not None:
            admitter.begin_drain()

    def close(self, reason: str = "shutdown") -> None:
        self._remove_listener()
        with self._lock:
            dialers = list(self._dialers.values())
        self.hangup()
        for dialer in dialers:
            dialer.join(2.0)
        self.offers.clear()
        with self._lock:
            self._draining = True
            parked = list(self._parked.values())
            self._parked.clear()
            splices = list(self._splices.values())
            self._splices.clear()
            admitter, self._admitter = self._admitter, None
        for lane in parked:
            _close_quietly(lane.sock)
        for pair in splices:
            for sock in pair:
                _close_quietly(sock)
        if admitter is not None:
            admitter.close(reason)

    def emit_event(self, payload: dict[str, Any]) -> None:
        """One line on the serve's service log (never a secret)."""

        self._emit(payload)

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._log is not None:
            try:
                self._log(payload)
            except Exception:
                pass


# ── the hello hook ───────────────────────────────────────────────────────────

def handoff(lanes: ReverseLanes | None, admitter: Any, connection: Any, reader: Any,
            message: dict[str, Any]) -> bool:
    """The socket lanes' hello hook: park or attach a reverse lane, or leave the hello alone.

    Runs after the credential verified, with the serve's own *lanes*. Answers True when it
    took the socket (parked, attached, or refused and closed).
    """

    lane_id = message.get("reverse_lane")
    attach = message.get("reverse_attach")
    if lane_id is None and attach is None:
        return False
    refusal = REJECT_REVERSE_LANE_REFUSED
    if lanes is not None and Path(admitter._store_root) == lanes.store_root:
        if lane_id is not None and attach is None and _is_plain_device(connection):
            refusal = lanes.park(connection, reader, lane_id)
        elif attach is not None and lane_id is None and _is_machine_owner(connection):
            refusal = lanes.attach(connection, reader, str(attach))
    if refusal is not None:
        from ..serve_socket.handshake import reject

        reject(admitter, connection, refusal)
    return True


def _is_plain_device(connection: Any) -> bool:
    """A paired device on the gateway lane: not a channel, not a peer, not a lane caller."""

    from ..call_authorization import DEVICE_KIND_CHANNEL, TRANSPORT_GATEWAY

    return (connection.transport == TRANSPORT_GATEWAY and bool(connection.device_id)
            and connection.device_tier is not None and connection.device_kind != DEVICE_KIND_CHANNEL
            and connection.peer_install_id is None and connection.computer_id is None)


def _is_machine_owner(connection: Any) -> bool:
    """This root's token on the loopback lane, and nothing else."""

    return (connection.transport == "socket" and connection.device_id is None
            and connection.peer_install_id is None and connection.computer_id is None)


# ── sockets ──────────────────────────────────────────────────────────────────


def _still_open(sock: Any) -> bool:
    """A parked lane hears nothing until it is attached: anything readable means it ended."""

    try:
        readable, _, _ = select.select([sock], [], [], 0)
    except (OSError, ValueError):
        return False
    return not readable


def _close_quietly(sock: Any) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def _splice(phone: Any, phone_ahead: bytes, owner: Any, owner_ahead: bytes) -> None:
    """Copy bytes both ways until either side ends; read nothing."""

    def pump(source: Any, sink: Any, ahead: bytes) -> None:
        try:
            if ahead:
                sink.sendall(ahead)
            while True:
                chunk = source.recv(_COPY_CHUNK)
                if not chunk:
                    break
                sink.sendall(chunk)
        except Exception:
            pass
        finally:
            _close_quietly(source)
            _close_quietly(sink)

    other = threading.Thread(target=pump, args=(owner, phone, owner_ahead), name="reverse-lane-splice", daemon=True)
    other.start()
    pump(phone, owner, phone_ahead)
    other.join(5.0)
