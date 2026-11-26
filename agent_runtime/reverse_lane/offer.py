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
its computer could not have received. The switch off is the same one-shot the other way
(``runtime.gateway.reverse.withdraw``): the computer forgets its accept of this phone, and the
offer it holds, only where they name a grant id the revoke removed.

The computer holds the offer in serve memory and the accept on disk, so it can lose its side
(a serve restart before its Eternia took the offer, its Eternia's decline) while the phone still
holds the grant. Hermes row ``RT-FU-YOUR-PHONE-OFFERS-AGAIN-TO-A-COMPUTER-THAT-NO-LONGER-HOLDS-ITS-GRANT``:
:func:`reoffer` asks the computer what it holds from this phone (``runtime.gateway.reverse.held``,
the same one-shot) and grants again ONLY when neither its accept nor its live offer names the
phone's current grant. A blind re-grant per call would loop: a new grant replaces the old
credential and closes the computer's granted call.
"""

from __future__ import annotations

import secrets
from typing import Any

from ..hello_address import answer_address_refusal
from ..serve_socket.client import ServeSocketClient
from ..serve_socket.hello import ServeCertificatePinMismatch, ServeHelloProtocolError
from . import grants as _grants

__layer__ = "lanes"

__all__ = ["HELD_METHOD", "OFFER_METHOD", "WITHDRAW_METHOD", "ask_held", "grant_and_offer", "reoffer",
           "withdraw_accept"]

OFFER_METHOD = "runtime.gateway.reverse.offer"
#: The phone's switch off, told to the computer (``withdraw_accept``).
WITHDRAW_METHOD = "runtime.gateway.reverse.withdraw"
#: The phone asks what the computer holds from it (``reoffer``).
HELD_METHOD = "runtime.gateway.reverse.held"
_TIMEOUT = 10.0
#: How long the offer's answer may take: a computer's first call after its serve started
#: loads its method families (seen live 2026-11-21: the first offer after a restart was
#: answered after the 10 s dial timeout, the retry at once).
_REPLY_TIMEOUT = 30.0
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


def _device_call(*, host: str, port: int, cert_fingerprint: str, device_id: str, token: str, machine_id: str,
         method: str, params: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Open the phone's pinned device connection to the computer, call *method* once, close.

    ``(None, result)`` when the computer answered a result; else ``(reason, {})``. After the pin and
    before the request, the computer's ``hello_ok`` must name *machine_id* and this namespace
    (``hello_address``, machine first): another machine holding the pin is sent nothing."""

    client = ServeSocketClient(host, int(port), timeout_seconds=_TIMEOUT, tls=True,
                               cert_fingerprint=str(cert_fingerprint or "").strip().lower())
    reason: str | None = None
    result: dict[str, Any] = {}
    try:
        client.connect()
        hello = client.device_hello(device_id=device_id, token=token, client=_CLIENT_NAME)
        if not isinstance(hello, dict) or hello.get("event") == "hello_rejected":
            refused = hello.get("reason") if isinstance(hello, dict) else None
            reason = "unpaired" if refused == "bad_proof" else "computer_refused"
        elif (address := answer_address_refusal(hello, expect_machine_id=machine_id)) is not None:
            reason = address
        else:
            client.set_timeout(_REPLY_TIMEOUT)
            rid = f"{method.rsplit('.', 1)[-1]}-{secrets.token_hex(4)}"
            client.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            reply = _offer_reply(client, rid)
            if reply is None:
                reason = "computer_unreachable"
            elif "error" in reply:
                data = (reply.get("error") or {}).get("data") or {}
                reason = str(data.get("reason") or "computer_refused")
            elif isinstance(reply.get("result"), dict):
                result = reply["result"]
    except ServeCertificatePinMismatch:
        reason = "certificate_rejected"
    except ServeHelloProtocolError as exc:
        frame = exc.frame if isinstance(exc.frame, dict) else {}
        reason = "unpaired" if frame.get("reason") == "bad_proof" else "computer_refused"
    except (OSError, ValueError):
        reason = "computer_unreachable"
    finally:
        client.close()
    return reason, result


def _one_shot(**way: Any) -> str | None:
    """:func:`_device_call` for a verb whose result says nothing: ``None`` when answered, else the refusal's reason."""

    return _device_call(**way)[0]


def grant_and_offer(store_root: Any, *, computer_install_id: str, computer_machine_id: str, host: str,
                    port: int, cert_fingerprint: str, device_id: str, token: str, level: str,
                    phone_install_id: str) -> dict[str, Any]:
    """Grant *computer_install_id* at *level* and offer it its credential. ``ok`` or ``reason``.

    A new grant replaces any the computer held (``grants.grant_computer``): one level, so there is
    nothing to change in place, and the computer's Eternia takes the new offer by itself.
    """

    credential = _grants.grant_computer(store_root, computer_install_id=computer_install_id,
                                        pairing_device_id=device_id, computer_machine_id=computer_machine_id,
                                        level=level)
    reason = _one_shot(host=host, port=port, cert_fingerprint=cert_fingerprint, device_id=device_id,
                       token=token, machine_id=computer_machine_id, method=OFFER_METHOD, params={
                           "computer_id": credential.computer_id, "token": credential.token,
                           "level": credential.level, "phone_install_id": phone_install_id})
    if reason is not None:
        # MUTATION: keep the grant here and the unreachable-offer test finds a grant the
        # computer never received.
        _grants.revoke_grant(store_root, credential.computer_id)
        if reason == "unpaired":
            _grants.revoke_install_grants(store_root, computer_install_id)
        return {"ok": False, "reason": reason}
    return {"ok": True, "computer_id": credential.computer_id, "level": credential.level, "state": "offered"}


def withdraw_accept(*, host: str, port: int, cert_fingerprint: str, device_id: str,
                    token: str, machine_id: str, computer_ids: list[str]) -> dict[str, Any]:
    """The phone's switch, off: tell the computer to forget its accept of this phone. ``ok`` or ``reason``.

    Row ``RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT``: the same one-shot as the
    offer, over the same pinned device connection. The computer keys the withdraw by the device the
    transport authenticated, and drops an offer or accept only when it names one of *computer_ids*
    (the grants the revoke removed), so a withdraw that lands after a newer offer leaves that offer;
    a withdraw that cannot land is not retried."""

    reason = _one_shot(host=host, port=port, cert_fingerprint=cert_fingerprint, device_id=device_id,
                       token=token, machine_id=machine_id, method=WITHDRAW_METHOD,
                       params={"computer_ids": [str(cid) for cid in computer_ids]})
    return {"ok": True} if reason is None else {"ok": False, "reason": reason}


def ask_held(*, host: str, port: int, cert_fingerprint: str, device_id: str, token: str,
             machine_id: str) -> dict[str, Any]:
    """What the computer holds from this phone: ``{ok, accepted, offered}`` (grant ids or ``None``), or ``reason``."""

    reason, result = _device_call(host=host, port=port, cert_fingerprint=cert_fingerprint, device_id=device_id,
                                  token=token, machine_id=machine_id, method=HELD_METHOD, params={})
    if reason is not None:
        return {"ok": False, "reason": reason}
    named = {key: (str(result[key]) if isinstance(result.get(key), str) and result[key] else None)
             for key in ("accepted", "offered")}
    return {"ok": True, **named}


def reoffer(store_root: Any, *, computer_install_id: str, computer_machine_id: str, host: str, port: int,
            cert_fingerprint: str, device_id: str, token: str, phone_install_id: str) -> dict[str, Any]:
    """Offer this computer its grant again, only when it no longer holds it. ``ok`` (``state``) or ``reason``.

    Re-sends a grant the phone already made: ``no_grant`` when the phone holds none for this computer
    under this pairing and machine (no new access). ``held`` when the computer's accept or live offer
    names the current grant (nothing minted: the computer's granted call stays up); else a new grant
    and offer (``offered``). A ``held`` refused ``bad_proof`` (the computer unpaired this phone) deletes
    the computer's grants, as an offer that hit it does."""

    current = _grants.grant_for_install(store_root, computer_install_id)
    if current is None or current.pairing_device_id != device_id or current.machine_id != computer_machine_id:
        return {"ok": False, "reason": "no_grant"}
    held = ask_held(host=host, port=port, cert_fingerprint=cert_fingerprint, device_id=device_id, token=token,
                    machine_id=computer_machine_id)
    if not held.get("ok"):
        reason = str(held.get("reason") or "computer_refused")
        if reason == "unpaired":
            # MUTATION: keep the grant here and test_reverse_grant's bad-proof test's next reoffer dials again.
            _grants.revoke_install_grants(store_root, computer_install_id)
        return {"ok": False, "reason": reason}
    # MUTATION: test only that an accept exists (not its id) and the older-accept test mints nothing.
    if current.computer_id in (held.get("accepted"), held.get("offered")):
        return {"ok": True, "computer_id": current.computer_id, "level": current.level, "state": "held"}
    return grant_and_offer(store_root, computer_install_id=computer_install_id,
                           computer_machine_id=computer_machine_id, host=host, port=port,
                           cert_fingerprint=cert_fingerprint, device_id=device_id, token=token,
                           level=current.level, phone_install_id=phone_install_id)
