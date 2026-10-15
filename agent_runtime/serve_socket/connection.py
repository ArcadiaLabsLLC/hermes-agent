"""``SocketConnection`` — one accepted, authenticated client: its framed writer,
its payload for the connections census, and its close.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

__layer__ = "stores"

__all__ = [
    "SocketConnection",
]


# ── connections ──────────────────────────────────────────────────────────────


@dataclass
class SocketConnection:
    """One authenticated (or pending) client on the socket lane."""

    key: str
    sock: Any
    peer: str
    connected_at: str
    #: D12 — the local address the kernel bound this ACCEPTED connection to,
    #: read once at accept and never re-read. It is the only MEASURED answer
    #: this install has to "which of my addresses can be reached from over
    #: there": every other candidate it publishes is an inference (a routing
    #: table read, R-D8, or a datagram probe, R-D2). ``None`` when the socket
    #: could not answer or the sockaddr is not an IP one — never a guess.
    reached_at: dict[str, Any] | None = None
    client: str | None = None
    client_build: str | None = None
    authenticated: bool = False
    #: WHICH paired device this is, and the tier its record holds — both ``None``
    #: on the loopback lane, forever. ``call_authorization.caller_for_connection``
    #: reads exactly these two fields to mint a ``device`` caller, and reads them
    #: through ``getattr`` so this module and that one need not import each
    #: other. Set once, in ``_handshake``, after the proof verified.
    device_id: str | None = None
    device_tier: str | None = None
    #: WHICH paired INSTALL this is (gateway Stage 6), or ``None`` on every
    #: other connection this runtime ever accepts. ``caller_for_connection``
    #: reads it through ``getattr`` to mint a ``peer`` caller, and reads it
    #: BEFORE the device pair, refusing a connection that somehow carries both.
    #: Set once, in ``_handshake``, after the proof verified.
    peer_install_id: str | None = None
    #: ONE-SHOT, and the only secrets this dataclass ever holds. Set by
    #: ``_handshake`` when a pairing code was redeemed, read and CLEARED by the
    #: ``hello_payload`` builder on the very next statement. Both are
    #: deliberately absent from ``payload()`` — the block that renders a
    #: connection to an operator, to a log, and to every other attached client.
    pairing_token: str | None = None
    peer_secret: str | None = None
    #: The expiry that rides with :attr:`peer_secret`, read and cleared in the
    #: same statement it is (``serve._pairing_block``). Not a secret, and kept
    #: off ``payload()`` anyway: it is meaningless without the credential it
    #: describes, and a field that outlived the one-shot would be a stale answer
    #: waiting to be read.
    peer_secret_expires_at: str | None = None
    subscribed: bool = False
    frames_out: int = 0
    bytes_out: int = 0
    closed: bool = False
    close_reason: str | None = None
    _write_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _stats_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    #: The transport name every frame this connection answers is tagged with.
    transport: str = "socket"

    def emit(self, frame: dict[str, Any], *, lock_timeout: float | None = None) -> None:
        """Write ONE NDJSON frame. Atomic per connection, mirroring _FrameWriter.

        Raises on a dead or wedged socket — the caller (a pump thread, a pool
        worker) decides what that means for its own lane.

        ``lock_timeout`` bounds the wait for the per-connection write lock. It
        exists for the BROADCAST path: a subscriber whose ``sendall`` is parked
        against a reader that stopped reading holds this lock for up to the
        socket timeout, and a drain announcement must not queue behind it.
        """

        payload = json.dumps(frame, ensure_ascii=False, default=str) + "\n"
        data = payload.encode("utf-8")
        if lock_timeout is None:
            acquired = self._write_lock.acquire()
        else:
            acquired = self._write_lock.acquire(timeout=lock_timeout)
        if not acquired:
            raise TimeoutError("connection write lock is busy")
        try:
            if self.closed:
                raise ConnectionError("connection closed")
            self.sock.sendall(data)
        finally:
            self._write_lock.release()
        with self._stats_lock:
            self.frames_out += 1
            self.bytes_out += len(data)

    def try_emit(self, frame: dict[str, Any], *, lock_timeout: float = 0.5) -> bool:
        try:
            self.emit(frame, lock_timeout=lock_timeout)
            return True
        except Exception:
            return False

    def payload(self) -> dict[str, Any]:
        with self._stats_lock:
            payload = {
                "connection": self.key,
                "client": self.client,
                "client_build": self.client_build,
                "authenticated": self.authenticated,
                "subscribed": self.subscribed,
                "connected_at": self.connected_at,
                "frames_out": self.frames_out,
                "bytes_out": self.bytes_out,
            }
            if self.reached_at is not None:
                # D12, additive and only on a row that HAS one. This is the
                # accepting install's own read path: the greeting hands the
                # measurement to the far side, but R-D7 makes this install's
                # launcher the consumer that promotes it to a published
                # endpoint, and a launcher reads this block — never a greeting
                # addressed to somebody else. Not a secret: it is this
                # machine's own LAN address, which every attached client on
                # that interface already knows.
                payload["reached_at"] = dict(self.reached_at)
            if self.device_id is not None:
                # ADDITIVE, and only on a row that has one — so every existing
                # `connections` consumer reads the shape it was written against.
                # A device id is not a secret (the device names it in its own
                # hello, in the clear under TLS), and "which of my paired devices
                # is attached right now" is the question this block exists to
                # answer once there is more than one client.
                payload["device_id"] = self.device_id
                payload["device_tier"] = self.device_tier
            if self.peer_install_id is not None:
                # Additive on a PEER row only, same rule and same reason: an
                # install id is not a secret (the peer names it in its own
                # hello, in the clear under TLS), and "which paired install is
                # attached right now" is the question an operator asks the
                # moment a cross-install call misbehaves. No tier key beside it,
                # because a peer holds an allowlist rather than a tier — a
                # ``peer_tier: null`` here would invite a reader to look for one.
                payload["peer_install_id"] = self.peer_install_id
            return payload

    def close(self, reason: str | None = None, *, linger_seconds: float = 0.0) -> None:
        # Deliberately NOT under the write lock: a connection is closed exactly
        # when a writer may be stuck inside ``sendall``, and waiting for that
        # lock would make teardown as slow as the wedged client. Shutting the
        # socket down is what unblocks that writer.
        with self._stats_lock:
            if self.closed:
                return
            self.closed = True
            self.close_reason = reason
        if linger_seconds > 0:
            self._linger(float(linger_seconds))
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _linger(self, linger_seconds: float) -> None:
        """Half-close, drain the receive buffer briefly, so the last frame survives."""

        # Closing a socket that still has UNREAD data in its receive buffer
        # makes the stack send an RST instead of a FIN, and an RST can
        # discard data already queued for the peer — so the client loses the
        # very frame that explains why it was closed. This is not
        # theoretical: a rejected client pipelines its next op immediately,
        # which is exactly the unread data that triggers it.
        #
        # Half-close (FIN out, keep reading), drain briefly, then close.
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        deadline = time.monotonic() + linger_seconds
        try:
            self.sock.settimeout(0.05)
            while time.monotonic() < deadline:
                if not self.sock.recv(65536):
                    break
        except OSError:
            pass
