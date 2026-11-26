"""``runtime.gateway.reverse.*`` — the phone's grant and outbound lane, the computer's offers and accepts.

Row ``MC-PHONE-DRIVEN-THE-PHONE-DIALS-OUT-SO-A-COMPUTER-CAN-REACH-ITS-ENGINE``
(``agent_runtime.reverse_lane``). While Eternia is in front on the phone it asks its engine
to dial each paired computer the phone granted; the engine refuses ``no_grant`` for a
computer with no grant, or one granted under an older pairing (the grant is bound to the
pairing, so a re-pair starts with none).

* ``dial`` — params ``computer_install_id``, ``host``, ``port``, ``cert_fingerprint`` (the
  computer's pin), ``device_id`` and ``token`` (this phone's credential on that computer;
  held in memory for the redials, never written or logged — the dispatcher logs no params).
* ``hangup`` — param ``computer_install_id`` (optional: every computer when absent). The
  app calls it when it leaves the foreground, and on the phone's Disconnect.
* ``lanes`` — what is parked and attached here (as a computer) and what this engine is
  dialling (as a phone); the offers held and phones accepted (computer) and the grants made
  (phone). No token in any of it.

The grant (row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS``, plan §15):

* ``grant`` (phone) — params as ``dial`` plus ``machine_id`` (the computer's, from the account record:
  the grant is bound to it) and ``level`` (``account``, the one level: hermes row
  ``RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN``): mint the
  computer's credential and offer it over the phone's own pinned connection
  (``agent_runtime.reverse_lane.offer``). The minted token is never in the answer.
* ``revoke`` (phone) — param ``computer_install_id``: delete that computer's grant (the switch
  turned off, or the phone unpaired it); its open lane closes at once, and the computer is told
  (``withdraw``, naming the grant ids removed) over the phone's pinned device connection when this
  serve knows the way to it.
* ``reoffer`` (phone) — params as ``grant``: ask the computer what it ``held`` from this phone and
  grant and offer again only when neither its accept nor its live offer names the phone's current
  grant (hermes row ``RT-FU-YOUR-PHONE-OFFERS-AGAIN-TO-A-COMPUTER-THAT-NO-LONGER-HOLDS-ITS-GRANT``).
  Answers ``state`` ``held`` or ``offered``, or the refusal's reason (``no_grant`` when the phone
  holds no grant for it: the verb re-sends a grant, it never makes a first one).
* ``offer`` (computer) — answered to a paired DEVICE only, as that device: hold its offer
  until this computer's Eternia takes it. Params ``computer_id``, ``token``, ``level``,
  ``phone_install_id``.
* ``held`` (computer) — answered to a paired DEVICE only, as that device, with no params: the
  grant id (``computer_id``) of this computer's accept of that device and of the live offer it
  holds from it, each or ``None``. Nothing of another device, and no token, level or time.
* ``withdraw`` (computer) — answered to a paired DEVICE only, as that device, param
  ``computer_ids`` (the grant ids the phone's revoke removed): forget that device's accept and any
  offer it still holds here, each only when it names one of them; naming none drops nothing.
* ``accept`` / ``decline`` (computer) — param ``device_id``. The computer's Eternia calls
  ``accept`` by itself, with no press, for an offer from a phone on its own account (owner
  2026-11-23: "No, drop Accept"; Eternia row
  ``MC-ACCOUNT-ONLY-YOUR-COMPUTER-USES-YOUR-PHONES-AGENTS-WITHOUT-PRESSING-ACCEPT``). ``accept``
  hands the token to Eternia ONCE and writes down the non-secret accept.

**Security.** Every verb but ``offer``, ``held`` and ``withdraw`` is in ``LOCAL_CONSOLE_METHODS``: only
this install's owner grants, dials, accepts or reads, and no device, peer or computer reaches
them. ``offer``, ``held`` and ``withdraw`` are read-tier verbs that answer only a paired device caller, as
itself: its device id is the transport's, never a param, and a channel, a peer or a computer is
refused by its allowlist arm before the tier is read.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    TIER_CONSOLE,
    TIER_READ,
)
from agent_runtime.param_readers import read_text
from agent_runtime.serve_rpc.params import ParamRefused
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, RpcContext, defer_or_inline, err, ok
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_gateway_reverse_accept",
    "_runtime_gateway_reverse_decline",
    "_runtime_gateway_reverse_dial",
    "_runtime_gateway_reverse_grant",
    "_runtime_gateway_reverse_held",
    "_runtime_gateway_reverse_offer",
    "_runtime_gateway_reverse_reoffer",
    "_runtime_gateway_reverse_revoke",
    "_runtime_gateway_reverse_withdraw",
    "_runtime_gateway_reverse_hangup",
    "_runtime_gateway_reverse_lanes",
    "_runtime_gateway_call_calls",
    "_runtime_gateway_call_dial",
    "_runtime_gateway_call_hangup",
    "_runtime_gateway_call_listen",
    "_runtime_gateway_call_unlisten",
]

_TEXT_LIMIT = 256
#: ``offer``'s refusal for any caller but a plain paired device.
REASON_NOT_A_DEVICE = "not_a_device"


def _refuse(key: str, sentence: str) -> ParamRefused:
    return ParamRefused(f"invalid params: {sentence}", RpcRefusal.PARAM_TYPE_INVALID)


def _lanes(context: RpcContext | None) -> Any:
    door = getattr(context, "reverse_lanes", None)
    return door() if door is not None else None


def _unbound(rid: Any) -> dict:
    return err(rid, ERR_CONFLICT, "This engine has no reverse lanes running.", {"reason": "reverse_lanes_unbound"})


_COMPUTER_KEYS = ("computer_install_id", "host", "cert_fingerprint", "device_id", "token")


def _computer_params(params: Any) -> dict:
    """The phone's way to one paired computer: its install, address, pin and the phone's credential."""

    params = params if isinstance(params, dict) else {}
    texts = {key: read_text(params, key, refuse=_refuse, required=True, limit=_TEXT_LIMIT, empty_ok=False)
             for key in _COMPUTER_KEYS}
    port = params.get("port")
    if type(port) is not int or not 0 < port < 65536:
        raise _refuse("port", "port must be an integer from 1 to 65535")
    texts["port"] = port
    return texts


def _lane_store_root(context: RpcContext | None, lanes: Any) -> Any:
    if lanes is not None:
        return lanes.store_root
    from agent_runtime import paths

    return paths.store_root()


@method("runtime.gateway.reverse.dial", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_dial(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    try:
        texts = _computer_params(params)
        port = texts.pop("port")
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    answer = lanes.dial(port=port, **texts)
    if not answer.get("ok"):
        reason = str(answer.get("reason") or "refused")
        return err(rid, ERR_CONFLICT, "This phone has not let that computer use its agents.", {"reason": reason})
    return ok(rid, {"computer_id": answer["computer_id"], "state": answer["state"]})


@method("runtime.gateway.reverse.hangup", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_hangup(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    params = params if isinstance(params, dict) else {}
    try:
        install = read_text(params, "computer_install_id", refuse=_refuse, limit=_TEXT_LIMIT)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return ok(rid, {"stopped": 0})
    return ok(rid, {"stopped": lanes.hangup(install or None)})


@method("runtime.gateway.reverse.lanes", tier=TIER_READ)
def _runtime_gateway_reverse_lanes(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    lanes = _lanes(context)
    if lanes is None:
        return ok(rid, {"parked": [], "attached": [], "dialing": []})
    return ok(rid, lanes.status())


def _grant_params(params: Any) -> tuple[dict, str]:
    """``grant``'s and ``reoffer``'s params: the way to the computer, its ``level`` and ``machine_id``."""

    from agent_runtime.hello_address import clean_machine_id
    from agent_runtime.reverse_lane.grants import GRANT_LEVELS

    texts = _computer_params(params)
    if (params or {}).get("level") not in GRANT_LEVELS:
        raise _refuse("level", f"level must be one of {', '.join(GRANT_LEVELS)}")
    # The computer's machine id, from this phone's account record: the grant is bound to it.
    machine_id = clean_machine_id((params or {}).get("machine_id"))
    if machine_id is None:
        raise _refuse("machine_id", "machine_id must name the computer's machine (mach_…)")
    return texts, machine_id


@method("runtime.gateway.reverse.grant", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_grant(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The phone's switch, on: grant one paired computer at ``level`` (``account``) and offer it its credential."""

    from agent_runtime.gateway_identity import read_install_identity
    from agent_runtime.reverse_lane.offer import grant_and_offer

    try:
        texts, machine_id = _grant_params(params)
        level = params["level"]
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    root = _lane_store_root(context, lanes)
    phone_install_id = read_install_identity(root).install_id
    if not phone_install_id:
        return err(rid, ERR_CONFLICT, "This phone has no install identity yet.", {"reason": "no_install_id"})

    def run() -> dict:
        answer = grant_and_offer(root, level=level, phone_install_id=phone_install_id,
                                 computer_machine_id=machine_id, **texts)
        if answer.get("ok") and lanes is not None:
            way = dict(texts)
            lanes.remember_way(way.pop("computer_install_id"), machine_id=machine_id, **way)
        if not answer.get("ok"):
            reason = str(answer.get("reason") or "refused")
            return err(rid, ERR_CONFLICT, "The computer did not take this phone's offer.", {"reason": reason})
        return ok(rid, {"computer_id": answer["computer_id"], "level": answer["level"], "state": answer["state"]})

    # It dials the computer: the worker lane, never the reader's thread.
    return defer_or_inline(rid, "runtime.gateway.reverse.grant", context, run)


@method("runtime.gateway.reverse.reoffer", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_reoffer(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Offer one paired computer this phone's grant again, only when it no longer holds it (``offer.reoffer``)."""

    from agent_runtime.gateway_identity import read_install_identity
    from agent_runtime.reverse_lane.offer import reoffer

    try:
        texts, machine_id = _grant_params(params)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    root = _lane_store_root(context, lanes)
    phone_install_id = read_install_identity(root).install_id
    if not phone_install_id:
        return err(rid, ERR_CONFLICT, "This phone has no install identity yet.", {"reason": "no_install_id"})

    def run() -> dict:
        answer = reoffer(root, phone_install_id=phone_install_id, computer_machine_id=machine_id, **texts)
        if not answer.get("ok"):
            reason = str(answer.get("reason") or "refused")
            return err(rid, ERR_CONFLICT, "The computer did not take this phone's offer.", {"reason": reason})
        if lanes is not None:
            way = dict(texts)
            lanes.remember_way(way.pop("computer_install_id"), machine_id=machine_id, **way)
        return ok(rid, {"computer_id": answer["computer_id"], "level": answer["level"], "state": answer["state"]})

    # It dials the computer: the worker lane, never the reader's thread.
    return defer_or_inline(rid, "runtime.gateway.reverse.reoffer", context, run)


@method("runtime.gateway.reverse.revoke", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_revoke(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The phone's switch, off (or the phone unpaired that computer): its grant goes, its lane closes,
    and the computer is told to forget its accept (``withdraw``) when this serve knows the way to it."""

    from agent_runtime.reverse_lane.grants import revoke_install_grants
    from agent_runtime.reverse_lane.offer import withdraw_accept

    try:
        install = read_text(params if isinstance(params, dict) else {}, "computer_install_id", refuse=_refuse,
                            required=True, limit=_TEXT_LIMIT, empty_ok=False)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    revoked = revoke_install_grants(_lane_store_root(context, lanes), install)
    way = None
    if lanes is not None:
        lanes.hangup(install)
        way = lanes.take_way(install)
    if way is None:
        # No grant or dial named this computer in this serve's life: nothing to tell it with (the
        # offline edge the row's review triaged out; its owner's Decline or an unpair drops the line).
        return ok(rid, {"revoked": len(revoked), "withdrawn": False})

    def run() -> dict:
        # MUTATION: skip this call and test_reverse_grant's switch-off test reads the accept still there.
        answer = withdraw_accept(**way.params(), computer_ids=revoked)
        result: dict[str, Any] = {"revoked": len(revoked), "withdrawn": bool(answer.get("ok"))}
        if not answer.get("ok"):
            result["withdraw_reason"] = str(answer.get("reason") or "computer_refused")
        return ok(rid, result)

    # It dials the computer: the worker lane, never the reader's thread.
    return defer_or_inline(rid, "runtime.gateway.reverse.revoke", context, run)


def _offering_device(context: RpcContext | None) -> str | None:
    """The paired device this offer comes from, read off the transport's caller; else ``None``."""

    caller = getattr(context, "caller", None)
    if caller is None or caller.kind != CALLER_DEVICE or caller.device_kind == DEVICE_KIND_CHANNEL:
        return None
    return caller.device_id or None


@method("runtime.gateway.reverse.offer", tier=TIER_READ)
def _runtime_gateway_reverse_offer(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A paired phone offers this computer the credential it minted for it; held until its Eternia takes it."""

    device_id = _offering_device(context)
    # MUTATION: accept any caller here and the owner-offers test holds an offer from the stdio owner.
    if device_id is None:
        # Its own word, not the gate's ``scope_denied``: the gate admitted the call (a read), and
        # this handler is what knows an offer needs a device behind it.
        return err(rid, ERR_CONFLICT, "Only a paired device offers its agents to this computer.",
                   {"reason": REASON_NOT_A_DEVICE})
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    params = params if isinstance(params, dict) else {}
    offer = lanes.offers.hold(device_id=device_id, computer_id=params.get("computer_id"),
                              level=params.get("level"), phone_install_id=params.get("phone_install_id"),
                              token=params.get("token"))
    if offer is None:
        return _refuse("offer", "an offer names computer_id, level, phone_install_id and its token").frame(rid)
    lanes.emit_event({"event": "reverse_offer_held", "device_id": device_id})
    return ok(rid, {"held": True})


@method("runtime.gateway.reverse.held", tier=TIER_READ)
def _runtime_gateway_reverse_held(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A paired phone asks what this computer holds from it: the grant ids of its accept and live offer.

    Hermes row ``RT-FU-YOUR-PHONE-OFFERS-AGAIN-TO-A-COMPUTER-THAT-NO-LONGER-HOLDS-ITS-GRANT``. Keyed only by the
    device the transport authenticated, never a param; the accept is read through ``list_accepts``, so an
    unpaired or retired row is never named; the offer only while it is live (``OFFER_TTL_SECONDS``)."""

    from agent_runtime.reverse_lane.accepts import list_accepts

    device_id = _offering_device(context)
    # MUTATION: accept any caller here and test_reverse_grant's held-callers test answers the stdio owner.
    if device_id is None:
        return err(rid, ERR_CONFLICT, "Only a paired device asks what this computer holds from it.",
                   {"reason": REASON_NOT_A_DEVICE})
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    offer = lanes.offers.peek(device_id)
    # MUTATION: read the first accept, not this device's, and the held-callers test answers B of A's accept.
    accept = next((a for a in list_accepts(lanes.store_root) if a.device_id == device_id), None)
    return ok(rid, {"accepted": accept.computer_id if accept is not None else None,
                    "offered": offer.computer_id if offer is not None else None})


_GRANT_IDS_LIMIT = 16


def _named_grant_ids(params: Any) -> list[str]:
    """``withdraw``'s ``computer_ids``: the grant ids the phone's revoke removed (absent: none)."""

    ids = (params if isinstance(params, dict) else {}).get("computer_ids", [])
    if not isinstance(ids, list) or len(ids) > _GRANT_IDS_LIMIT or not all(
            isinstance(cid, str) and 0 < len(cid) <= _TEXT_LIMIT for cid in ids):
        raise _refuse("computer_ids", f"computer_ids must be a list of at most {_GRANT_IDS_LIMIT} grant ids")
    return ids


@method("runtime.gateway.reverse.withdraw", tier=TIER_READ)
def _runtime_gateway_reverse_withdraw(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A paired phone switched this computer off: forget its accept (and any offer still held).

    Row ``RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT``. Keyed only by the device
    the transport authenticated, never a param, and it only removes that device's own rows — and of
    those only the ones naming a grant id in ``computer_ids`` (hermes row
    ``RT-FU-YOUR-PHONE-OFFERS-AGAIN-TO-A-COMPUTER-THAT-NO-LONGER-HOLDS-ITS-GRANT``): a withdraw that lands
    after a newer offer, or after the new accept, leaves them. Naming none drops nothing (no fallback)."""

    from agent_runtime.reverse_lane.accepts import forget_accept

    device_id = _offering_device(context)
    # MUTATION: accept any caller here and the owner-withdraw test forgets an accept nobody withdrew.
    if device_id is None:
        return err(rid, ERR_CONFLICT, "Only a paired device withdraws its agents from this computer.",
                   {"reason": REASON_NOT_A_DEVICE})
    try:
        named = _named_grant_ids(params)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    # MUTATION: drop by device alone (``offers.drop`` / no ``naming``) and test_reverse_grant's older-id
    # withdraw test finds the newer offer and the current accept gone.
    dropped = lanes.offers.drop_naming(device_id, named)
    forgot = forget_accept(lanes.store_root, device_id, naming=named)
    if dropped or forgot:
        lanes.emit_event({"event": "reverse_accept_withdrawn", "device_id": device_id})
    return ok(rid, {"withdrawn": forgot, "declined": dropped})


def _device_param(params: Any) -> str:
    return read_text(params if isinstance(params, dict) else {}, "device_id", refuse=_refuse, required=True,
                     limit=_TEXT_LIMIT, empty_ok=False)


@method("runtime.gateway.reverse.accept", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_accept(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """This computer's Eternia takes a phone's offer, with no press for a phone on its own account (owner
    2026-11-23: "No, drop Accept"): the token, once, for Eternia's credential store."""

    from agent_runtime.reverse_lane.accepts import record_accept
    from agent_runtime.serve_gateway_auth import lookup_device

    try:
        device_id = _device_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    offer = lanes.offers.take(device_id)
    record = lookup_device(lanes.store_root, device_id) if offer is not None else None
    if offer is None or record is None or record.revoked or record.expired:
        return err(rid, ERR_CONFLICT, "That phone has no offer waiting here.", {"reason": "no_offer"})
    if not record.machine_id:
        return err(rid, ERR_CONFLICT, "That phone has no offer waiting here.", {"reason": "no_offer"})
    accept = record_accept(lanes.store_root, offer, machine_id=record.machine_id)
    return ok(rid, {**accept.describe(), "token": offer.token})


@method("runtime.gateway.reverse.decline", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_decline(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """This computer's owner declines a phone's offer, or forgets one it accepted."""

    from agent_runtime.reverse_lane.accepts import forget_accept

    try:
        device_id = _device_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    dropped = lanes.offers.drop(device_id)
    forgot = forget_accept(lanes.store_root, device_id)
    return ok(rid, {"declined": dropped, "forgot": forgot})


# ── the call (RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST) ──

_CALL_KEYS = ("install_id", "host", "cert_fingerprint", "token")
#: This device's credential on the far one: its pairing there (``device_id``), or the grant a phone made it
#: (``computer_id``, the far side being that phone's listener). Exactly one.
_CALL_CREDENTIALS = {"device_id": "device", "computer_id": "grant"}


@method("runtime.gateway.call.dial", tier=TIER_CONSOLE)
def _runtime_gateway_call_dial(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Keep trying to call one of your other devices (``agent_runtime.pair_call``), from this side.

    Params: the far device's ``install_id``, ``host``, ``port``, ``cert_fingerprint`` (its pin) and
    ``machine_id`` (from the account record), and ``device_id`` / ``token`` (this device's credential on
    it, held in memory only) — or, a computer calling a phone's listener, ``computer_id`` / ``token`` (the
    grant that phone made this computer) in place of ``device_id``. The far device dials too; the first
    call to connect is the call.
    """

    from agent_runtime.hello_address import clean_machine_id
    from agent_runtime.pair_call.calls import CallWay

    params = params if isinstance(params, dict) else {}
    try:
        texts = {key: read_text(params, key, refuse=_refuse, required=True, limit=_TEXT_LIMIT, empty_ok=False)
                 for key in _CALL_KEYS}
        port = params.get("port")
        if type(port) is not int or not 0 < port < 65536:
            raise _refuse("port", "port must be an integer from 1 to 65535")
        machine_id = clean_machine_id(params.get("machine_id"))
        if machine_id is None:
            raise _refuse("machine_id", "machine_id must name the far device's machine (mach_…)")
        named = [key for key in _CALL_CREDENTIALS if params.get(key) is not None]
        if len(named) != 1:
            raise _refuse("device_id", "name exactly one of device_id or computer_id")
        credential_id = read_text(params, named[0], refuse=_refuse, required=True, limit=_TEXT_LIMIT,
                                  empty_ok=False)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    answer = lanes.calls.dial(CallWay(port=port, machine_id=machine_id, device_id=credential_id,
                                      credential=_CALL_CREDENTIALS[named[0]], **texts))
    if not answer.get("ok"):
        return err(rid, ERR_CONFLICT, "This engine is shutting down.", {"reason": str(answer.get("reason"))})
    return ok(rid, {"far_install": answer["far_install"]})


@method("runtime.gateway.call.hangup", tier=TIER_CONSOLE)
def _runtime_gateway_call_hangup(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    params = params if isinstance(params, dict) else {}
    try:
        install = read_text(params, "install_id", refuse=_refuse, limit=_TEXT_LIMIT)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return ok(rid, {"stopped": 0})
    return ok(rid, {"stopped": lanes.calls.hangup(install or None)})


@method("runtime.gateway.call.calls", tier=TIER_READ)
def _runtime_gateway_call_calls(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The calls up (one per far install, with its ``generation``: a new number means re-read its state)
    and the dialers trying. No token in any of it."""

    lanes = _lanes(context)
    if lanes is None:
        return ok(rid, {"calls": [], "dialing": [], "listening": None})
    return ok(rid, lanes.calls.status())


@method("runtime.gateway.call.listen", tier=TIER_CONSOLE)
def _runtime_gateway_call_listen(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A phone listens for the call while its Eternia is in front and signed in (``agent_runtime.pair_call.listener``).

    Params (both optional): ``host`` (default every interface) and ``port`` (0, the default: any free port).
    Answers the ``listening`` block — ``host``, ``port``, ``cert_fingerprint`` (the pin a computer dials with) —
    or ``error:<why>``. Only a computer holding a grant this phone minted gets in; Eternia calls ``unlisten``
    when it leaves the front, on sign-out and on an account change.
    """

    params = params if isinstance(params, dict) else {}
    try:
        host = read_text(params, "host", refuse=_refuse, limit=_TEXT_LIMIT)
        port = params.get("port", 0)
        if type(port) is not int or not 0 <= port < 65536:
            raise _refuse("port", "port must be an integer from 0 to 65535")
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    if lanes is None:
        return _unbound(rid)
    block = lanes.calls.listen(host=host or None, port=port)
    if block.get("outcome") != "listening":
        return err(rid, ERR_CONFLICT, "This engine could not open its listener.",
                   {"reason": "listener_unavailable", "outcome": str(block.get("outcome"))})
    return ok(rid, block)


@method("runtime.gateway.call.unlisten", tier=TIER_CONSOLE)
def _runtime_gateway_call_unlisten(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Close this phone's listener; a call already up stays up (hang it up with ``hangup``)."""

    lanes = _lanes(context)
    if lanes is None:
        return ok(rid, {"closed": False})
    return ok(rid, {"closed": lanes.calls.unlisten()})
