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

* ``grant`` (phone) — params as ``dial`` plus ``level`` (``look`` | ``chat``): mint the
  computer's credential and offer it over the phone's own pinned connection
  (``agent_runtime.reverse_lane.offer``). The minted token is never in the answer.
* ``revoke`` (phone) — param ``computer_install_id``: delete that computer's grant (the switch
  turned off, or the phone unpaired it); its open lane closes at once.
* ``offer`` (computer) — answered to a paired DEVICE only, as that device: hold its offer
  until this computer's owner answers. Params ``computer_id``, ``token``, ``level``,
  ``phone_install_id``.
* ``accept`` / ``decline`` (computer) — param ``device_id``: the owner's answer. ``accept``
  hands the token to Eternia ONCE and writes down the non-secret accept.

**Security.** Every verb but ``offer`` is in ``LOCAL_CONSOLE_METHODS``: only this install's
owner grants, dials, accepts or reads, and no device, peer or computer reaches them.
``offer`` is a read-tier verb that answers only a paired device caller, as itself: its device
id is the transport's, never a param, and a channel, a peer or a computer is refused by its
allowlist arm before the tier is read.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    REASON_SCOPE_DENIED,
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
    "_runtime_gateway_reverse_offer",
    "_runtime_gateway_reverse_revoke",
    "_runtime_gateway_reverse_hangup",
    "_runtime_gateway_reverse_lanes",
]

_TEXT_LIMIT = 256


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


def _store_root(context: RpcContext | None, lanes: Any) -> Any:
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


@method("runtime.gateway.reverse.grant", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_grant(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The phone's switch, on: grant one paired computer at ``level`` and offer it its credential."""

    from agent_runtime.gateway_identity import read_install_identity
    from agent_runtime.reverse_lane.grants import GRANT_LEVELS
    from agent_runtime.reverse_lane.offer import grant_and_offer

    try:
        texts = _computer_params(params)
        level = (params or {}).get("level")
        if level not in GRANT_LEVELS:
            raise _refuse("level", f"level must be one of {', '.join(GRANT_LEVELS)}")
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    root = _store_root(context, lanes)
    phone_install_id = read_install_identity(root).install_id
    if not phone_install_id:
        return err(rid, ERR_CONFLICT, "This phone has no install identity yet.", {"reason": "no_install_id"})

    def run() -> dict:
        answer = grant_and_offer(root, level=level, phone_install_id=phone_install_id, **texts)
        if not answer.get("ok"):
            reason = str(answer.get("reason") or "refused")
            return err(rid, ERR_CONFLICT, "The computer did not take this phone's offer.", {"reason": reason})
        return ok(rid, {"computer_id": answer["computer_id"], "level": answer["level"], "state": "offered"})

    # It dials the computer: the worker lane, never the reader's thread.
    return defer_or_inline(rid, "runtime.gateway.reverse.grant", context, run)


@method("runtime.gateway.reverse.revoke", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_revoke(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The phone's switch, off (or the phone unpaired that computer): its grant goes, its lane closes."""

    from agent_runtime.reverse_lane.grants import revoke_install_grants

    try:
        install = read_text(params if isinstance(params, dict) else {}, "computer_install_id", refuse=_refuse,
                            required=True, limit=_TEXT_LIMIT, empty_ok=False)
    except ParamRefused as refused:
        return refused.frame(rid)
    lanes = _lanes(context)
    revoked = revoke_install_grants(_store_root(context, lanes), install)
    if lanes is not None:
        lanes.hangup(install)
    return ok(rid, {"revoked": len(revoked)})


def _offering_device(context: RpcContext | None) -> str | None:
    """The paired device this offer comes from, read off the transport's caller; else ``None``."""

    caller = getattr(context, "caller", None)
    if caller is None or caller.kind != CALLER_DEVICE or caller.device_kind == DEVICE_KIND_CHANNEL:
        return None
    return caller.device_id or None


@method("runtime.gateway.reverse.offer", tier=TIER_READ)
def _runtime_gateway_reverse_offer(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A paired phone offers this computer the credential it minted for it; held until the owner answers."""

    device_id = _offering_device(context)
    # MUTATION: accept any caller here and the owner-offers test holds an offer from the stdio owner.
    if device_id is None:
        return err(rid, ERR_CONFLICT, "Only a paired device offers its agents to this computer.",
                   {"reason": REASON_SCOPE_DENIED})
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


def _device_param(params: Any) -> str:
    return read_text(params if isinstance(params, dict) else {}, "device_id", refuse=_refuse, required=True,
                     limit=_TEXT_LIMIT, empty_ok=False)


@method("runtime.gateway.reverse.accept", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_accept(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """This computer's owner accepts a phone's offer: the token, once, for Eternia's credential store."""

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
    accept = record_accept(lanes.store_root, offer)
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
