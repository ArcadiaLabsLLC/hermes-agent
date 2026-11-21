"""The phone's outbound lane to one granted computer: dial, park, wait, serve, redial.

The phone opens every connection (D3 2026-09-30: a phone runs no listener). Each round:

1. a pinned TLS dial to the computer's gateway, the phone's own device hello with a
   fresh ``reverse_lane`` id — the computer parks the connection;
2. wait for the computer's ``reverse_attached`` (its owner's Eternia attached);
3. hand the socket to the phone's listener-less admitter, which runs the ordinary hello
   with the proof bound to this round's lane id, then serves the computer until it leaves;
4. dial again, with a new lane id.

A refused device credential (``bad_proof``) means the computer unpaired this phone: the
grant for that computer is deleted, so it never comes back with a re-pair (review
w1118a.79). A certificate that no longer matches the pin stops the dialler: it needs a
re-pair. Anything else backs off and tries again.
"""

from __future__ import annotations

import secrets
import socket
import threading
from typing import Any

from ..serve_socket.client import ServeSocketClient
from ..serve_socket.hello import ServeCertificatePinMismatch, ServeHelloProtocolError
from ..serve_socket.vocabulary import REJECT_BAD_PROOF
from . import grants as _grants
from .lanes import _close_quietly as _close

__layer__ = "lanes"

__all__ = ["ReverseDialer"]

_DIAL_TIMEOUT = 10.0
#: How long a parked wait reads before it looks at the stop flag again.
_PARKED_POLL = 1.0
_BACKOFF_FIRST = 1.0
_BACKOFF_MAX = 30.0
_CLIENT_NAME = "eternia-phone-reverse-lane"

STATE_DIALING = "dialing"
STATE_PARKED = "parked"
STATE_CONNECTED = "connected"
STATE_STOPPED = "stopped"


class ReverseDialer:
    """One granted computer's dial loop, on its own thread."""

    def __init__(self, lanes: Any, *, grant: Any, host: str, port: int, cert_fingerprint: str,
                 device_id: str, token: str) -> None:
        self._lanes = lanes
        self.computer_id = grant.computer_id
        self.computer_install_id = grant.computer_install_id
        self._host = str(host)
        self._port = int(port)
        self._pin = str(cert_fingerprint or "").strip().lower()
        self._device_id = str(device_id)
        #: The phone's own credential on the computer, held for the redials and never logged.
        self._token = str(token)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._client: ServeSocketClient | None = None
        self.state = STATE_DIALING
        self.stopped_reason: str | None = None
        self.lanes_served = 0
        self._thread = threading.Thread(target=self._run, name="reverse-lane-dialer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, reason: str = "hung_up") -> None:
        self._finish(reason)
        with self._lock:
            client = self._client
        if client is not None:
            client.close()

    def join(self, timeout: float) -> None:
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def status(self) -> dict[str, Any]:
        return {"computer_install_id": self.computer_install_id, "computer_id": self.computer_id,
                "state": self.state, "stopped_reason": self.stopped_reason, "lanes_served": self.lanes_served}

    def _finish(self, reason: str) -> None:
        if not self._stop.is_set():
            self.stopped_reason = reason
        self.state = STATE_STOPPED
        self._stop.set()

    def _run(self) -> None:
        backoff = _BACKOFF_FIRST
        try:
            while not self._stop.is_set():
                outcome = self._round()
                if outcome == "served":
                    backoff = _BACKOFF_FIRST
                    continue
                if outcome is not None and outcome.startswith("stop:"):
                    self._finish(outcome[5:])
                    break
                if self._stop.wait(backoff):
                    break
                backoff = min(_BACKOFF_MAX, backoff * 2)
        finally:
            self.state = STATE_STOPPED
            self._lanes.forget_dialer(self)

    def _round(self) -> str | None:
        """One dial. ``served`` after a lane ended, ``stop:<reason>``, or None to back off."""

        grant = _grants.grant_for_install(self._lanes.store_root, self.computer_install_id)
        if grant is None or grant.computer_id != self.computer_id:
            return "stop:grant_gone"
        lane_id = secrets.token_hex(16)
        client = ServeSocketClient(self._host, self._port, timeout_seconds=_DIAL_TIMEOUT,
                                   tls=True, cert_fingerprint=self._pin)
        with self._lock:
            self._client = client
        self.state = STATE_DIALING
        try:
            client.connect()
            reply = client.device_hello(device_id=self._device_id, token=self._token,
                                        client=_CLIENT_NAME, reverse_lane=lane_id)
        except ServeCertificatePinMismatch:
            client.close()
            return "stop:certificate_rejected"
        except ServeHelloProtocolError as exc:
            client.close()
            return self._refused(exc.frame)
        except (OSError, ValueError):
            client.close()
            return None
        if not isinstance(reply, dict) or reply.get("event") != "reverse_lane_parked":
            client.close()
            return self._refused(reply)
        self.state = STATE_PARKED
        if not self._wait_attached(client):
            client.close()
            return None
        sock, ahead = client.detach()
        with self._lock:
            self._client = None
        if self._stop.is_set():
            _close(sock)
            return None
        self.state = STATE_CONNECTED
        try:
            admitter = self._lanes.admitter()
            # Blocks while the computer is connected; the proof is bound to THIS lane id.
            admitter.admit(sock, (self._host, self._port), binding=lane_id, initial_bytes=ahead)
        finally:
            _close(sock)
        self.lanes_served += 1
        return "served"

    def _refused(self, frame: Any) -> str | None:
        reason = frame.get("reason") if isinstance(frame, dict) else None
        if frame is not None and isinstance(frame, dict) and frame.get("event") == "hello_rejected" \
                and reason == REJECT_BAD_PROOF:
            # The computer no longer knows this phone: it unpaired us, so the grant goes too.
            _grants.revoke_install_grants(self._lanes.store_root, self.computer_install_id)
            return "stop:unpaired"
        return None

    def _wait_attached(self, client: ServeSocketClient) -> bool:
        client.set_timeout(_PARKED_POLL)
        while not self._stop.is_set():
            try:
                frame = client.read_frame()
            except socket.timeout:  # noqa: UP041
                continue
            except OSError:
                return False
            if frame is None:
                return False
            if frame.get("event") == "reverse_attached":
                return True
        return False

