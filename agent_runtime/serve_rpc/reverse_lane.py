"""``runtime.gateway.reverse.dial`` / ``.hangup`` / ``.lanes`` — the phone's outbound lane to a computer.

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
  dialling (as a phone).

**Security.** All three are in ``LOCAL_CONSOLE_METHODS``: only this install's owner dials
with its own credential, and no device, peer or computer reaches them.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.param_readers import read_text
from agent_runtime.serve_rpc.params import ParamRefused
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, RpcContext, err, ok
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_gateway_reverse_dial",
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


@method("runtime.gateway.reverse.dial", tier=TIER_CONSOLE)
def _runtime_gateway_reverse_dial(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    params = params if isinstance(params, dict) else {}
    try:
        texts = {key: read_text(params, key, refuse=_refuse, required=True, limit=_TEXT_LIMIT, empty_ok=False)
                 for key in ("computer_install_id", "host", "cert_fingerprint", "device_id", "token")}
        port = params.get("port")
        if type(port) is not int or not 0 < port < 65536:
            raise _refuse("port", "port must be an integer from 1 to 65535")
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
