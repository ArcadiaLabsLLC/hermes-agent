"""``runtime.gateway.id`` / ``.introduce`` / ``.peers.join`` / ``.peers.revoke`` / ``.devices.list`` — the gateway verbs' own calls.

RT-PETS-PAIRING-GATEWAY-ID-AND-UNPAIR-HAVE-THEIR-OWN-CALLS-ON-THE-RUNNING-HERMES. Eternia handed the running serve
a command line for each of these; each is now a typed method that runs the SAME verb handler in process
(``hermes_cli.harness_support.stage42_operation_result``), so there is one body per action and the CLI keeps it:

* ``runtime.gateway.id`` — ``harness gateway id`` (``gateway_identity_commands._cmd_gateway_id``);
* ``runtime.gateway.introduce`` — ``harness gateway introduce`` (``introduce.cmd_gateway_introduce``);
* ``runtime.gateway.peers.join`` — ``harness gateway peers join`` (``join.cmd_gateway_peers_join``);
* ``runtime.gateway.peers.revoke`` — ``harness gateway peers revoke`` (``peers.cmd_gateway_peers_revoke``);
* ``runtime.gateway.devices.list`` — ``harness gateway devices list`` (``devices.cmd_gateway_devices_list``).

A success answers the verb's own Stage-42 envelope, byte for byte the object ``--json`` prints. A refusal is
the verb's own error: its ``code`` (the family) and ``reason`` (the store's word) ride ``error.data``, and its
sentence is ``error.message``. JSON-RPC code: ``invalid_payload`` -32602, ``not_found`` 4001, else 4090.

**Security (review w1118a.77).** All five are in ``LOCAL_CONSOLE_METHODS``: the peer directory and pairing
are the desktop operator's own network map (the paired-device list too), and ``gateway id``'s answer carries the store root path
(``attach_root_observability``). A tier alone would let a paired console-tier device pair or unpair. The
pairing code in ``introduce``'s answer and in ``join``'s ``payload`` param is the verb's one appearance of it:
the dispatcher logs no params, and no event or receipt carries it.

Each runs on the worker lane (``defer_or_inline``): ``join`` dials another machine, ``revoke`` announces to
one, and the endpoint walk in ``id`` / ``introduce`` reads the routing table.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.param_readers import read_text
from agent_runtime.serve_rpc.params import ParamRefused
from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    defer_or_inline,
    err,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_gateway_devices_list",
    "_runtime_gateway_id",
    "_runtime_gateway_introduce",
    "_runtime_gateway_peers_join",
    "_runtime_gateway_peers_revoke",
]

#: A join payload is a JSON object of a few hundred bytes (``GRANT_PAYLOAD_MAX_BYTES`` bounds the grant that
#: carries it); anything near this is not one.
_PAYLOAD_LIMIT = 16 * 1024
_TEXT_LIMIT = 512

_ERROR_CODES = {"invalid_payload": ERR_INVALID_PARAMS, "not_found": ERR_NOT_FOUND}


def _refuse(key: str, sentence: str) -> ParamRefused:
    return ParamRefused(f"invalid params: {sentence}", RpcRefusal.PARAM_TYPE_INVALID)


def _verb_reply(rid: Any, envelope: dict) -> dict:
    """The verb's envelope as a reply: itself on success, its error as the RPC error."""

    if envelope.get("kind") != "error":
        return ok(rid, envelope)
    error = envelope.get("error") or {}
    code = str(error.get("code") or "runtime_unavailable")
    data = {"reason": str(error.get("reason") or code), "code": code,
            "retryable": bool(error.get("retryable")), "safe_details": error.get("safe_details") or {}}
    return err(rid, _ERROR_CODES.get(code, ERR_CONFLICT), str(error.get("message") or code), data)


def _run(rid: Any, name: str, context: RpcContext | None, handler: Callable[[], Callable], **flags) -> dict:
    from hermes_cli.harness_support import stage42_operation_result

    return defer_or_inline(rid, name, context, lambda: _verb_reply(rid, stage42_operation_result(handler(), **flags)))


def _texts(params: Any, *keys: str, required: tuple[str, ...] = (), limit: int = _TEXT_LIMIT) -> dict:
    params = params if isinstance(params, dict) else {}
    return {key: read_text(params, key, refuse=_refuse, required=key in required, limit=limit) for key in keys}


@method("runtime.gateway.id", tier=TIER_READ)
def _runtime_gateway_id(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness gateway id``: this install's identity, read without minting one. Params: none."""

    def handler():
        from hermes_cli.harness_parts.gateway_identity_commands import _cmd_gateway_id

        return _cmd_gateway_id

    return _run(rid, "runtime.gateway.id", context, handler)


@method("runtime.gateway.introduce", tier=TIER_CONSOLE)
def _runtime_gateway_introduce(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness gateway introduce``. Params: ``for_install`` / ``for_device`` (at least one), ``note``,
    ``correlation`` (the backend grant id). The answer carries the minted codes, once."""

    try:
        flags = _texts(params, "for_install", "for_device", "note", "correlation")
    except ParamRefused as refused:
        return refused.frame(rid)

    def handler():
        from hermes_cli.harness_parts.gateway_commands.introduce import cmd_gateway_introduce

        return cmd_gateway_introduce

    return _run(rid, "runtime.gateway.introduce", context, handler, **flags)


@method("runtime.gateway.peers.join", tier=TIER_CONSOLE)
def _runtime_gateway_peers_join(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness gateway peers join``. Params: ``payload`` (required: the join payload or a bare code — the
    pairing secret, a typed param and never a command line), ``expect_fingerprint``, ``correlation``,
    ``host`` + ``port`` (one candidate to dial; both or neither)."""

    params = params if isinstance(params, dict) else {}
    try:
        flags = _texts(params, "expect_fingerprint", "correlation", "host")
        flags["payload"] = read_text(params, "payload", refuse=_refuse, required=True, limit=_PAYLOAD_LIMIT)
        port = params.get("port")
        if port is not None and (type(port) is not int or not 0 < port < 65536):
            raise _refuse("port", "port must be an integer from 1 to 65535")
        if (flags["host"] is None) != (port is None):
            raise _refuse("host", "host and port name one candidate together; send both or neither")
        flags["port"] = port
    except ParamRefused as refused:
        return refused.frame(rid)

    def handler():
        from hermes_cli.harness_parts.gateway_commands.join import cmd_gateway_peers_join

        return cmd_gateway_peers_join

    return _run(rid, "runtime.gateway.peers.join", context, handler, **flags)


@method("runtime.gateway.peers.revoke", tier=TIER_CONSOLE)
def _runtime_gateway_peers_revoke(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness gateway peers revoke``: refuse a peer of THIS install from its next handshake, telling it
    first when it answers. Params: ``peer_install_id`` (required). An install nobody paired is ``not_found``."""

    try:
        flags = _texts(params, "peer_install_id", required=("peer_install_id",))
    except ParamRefused as refused:
        return refused.frame(rid)

    def handler():
        from hermes_cli.harness_parts.gateway_commands.peers import cmd_gateway_peers_revoke

        return cmd_gateway_peers_revoke

    return _run(rid, "runtime.gateway.peers.revoke", context, handler, **flags)


@method("runtime.gateway.devices.list", tier=TIER_READ)
def _runtime_gateway_devices_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness gateway devices list``: every paired device and channel credential, revoked included, as the
    verb's list envelope (no credential field exists on a row). Params: none."""

    def handler():
        from hermes_cli.harness_parts.gateway_commands.devices import cmd_gateway_devices_list

        return cmd_gateway_devices_list

    return _run(rid, "runtime.gateway.devices.list", context, handler)
