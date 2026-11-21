"""The phone grants a paired computer and offers it the credential, all inside this engine.

Row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS`` (Eternia), plan §4 "the
reverse grant" as built (§15): the phone's Eternia asks its own engine to grant
(``runtime.gateway.reverse.grant``, local console only) and passes, in process, the phone's
own credential on that computer, as it does for a dial. The engine mints the computer's
credential (:func:`.grants.grant_computer`), opens its pinned TLS connection to the computer's
gateway as the phone's device, and offers the credential ONCE
(``runtime.gateway.reverse.offer``). The minted token never reaches the phone's Eternia, a
log or a disk: it exists here, on that one connection, and in the computer's held offer.

An offer that does not land deletes the grant it minted, so the phone never holds a grant
its computer could not have received.
"""

from __future__ import annotations

import secrets
from typing import Any

from ..serve_socket.client import ServeSocketClient
from ..serve_socket.hello import ServeCertificatePinMismatch, ServeHelloProtocolError
from . import grants as _grants

__layer__ = "lanes"

__all__ = ["OFFER_METHOD", "grant_and_offer"]

OFFER_METHOD = "runtime.gateway.reverse.offer"
_TIMEOUT = 10.0
_CLIENT_NAME = "eternia-phone-reverse-offer"
_MAX_FRAMES = 64


def _offer_reply(client: ServeSocketClient, rid: str) -> dict[str, Any] | None:
    for _ in range(_MAX_FRAMES):
        frame = client.read_frame()
        if frame is None:
            return None
        if frame.get("id") == rid and ("result" in frame or "error" in frame):
            return frame
    return None


def grant_and_offer(store_root: Any, *, computer_install_id: str, host: str, port: int,
                    cert_fingerprint: str, device_id: str, token: str, level: str,
                    phone_install_id: str) -> dict[str, Any]:
    """Grant *computer_install_id* at *level* and offer it its credential. ``ok`` or ``reason``."""

    credential = _grants.grant_computer(store_root, computer_install_id=computer_install_id,
                                        pairing_device_id=device_id, level=level)
    client = ServeSocketClient(host, int(port), timeout_seconds=_TIMEOUT, tls=True,
                               cert_fingerprint=str(cert_fingerprint or "").strip().lower())
    reason: str | None = None
    try:
        client.connect()
        hello = client.device_hello(device_id=device_id, token=token, client=_CLIENT_NAME)
        if not isinstance(hello, dict) or hello.get("event") == "hello_rejected":
            refused = hello.get("reason") if isinstance(hello, dict) else None
            reason = "unpaired" if refused == "bad_proof" else "computer_refused"
        else:
            rid = f"offer-{secrets.token_hex(4)}"
            client.send({"jsonrpc": "2.0", "id": rid, "method": OFFER_METHOD, "params": {
                "computer_id": credential.computer_id, "token": credential.token,
                "level": credential.level, "phone_install_id": phone_install_id}})
            reply = _offer_reply(client, rid)
            if reply is None:
                reason = "computer_unreachable"
            elif "error" in reply:
                data = (reply.get("error") or {}).get("data") or {}
                reason = str(data.get("reason") or "computer_refused")
    except ServeCertificatePinMismatch:
        reason = "certificate_rejected"
    except ServeHelloProtocolError as exc:
        frame = exc.frame if isinstance(exc.frame, dict) else {}
        reason = "unpaired" if frame.get("reason") == "bad_proof" else "computer_refused"
    except (OSError, ValueError):
        reason = "computer_unreachable"
    finally:
        client.close()
    if reason is not None:
        # MUTATION: keep the grant here and the unreachable-offer test finds a grant the
        # computer never received.
        _grants.revoke_grant(store_root, credential.computer_id)
        if reason == "unpaired":
            _grants.revoke_install_grants(store_root, computer_install_id)
        return {"ok": False, "reason": reason}
    return {"ok": True, "computer_id": credential.computer_id, "level": credential.level}
