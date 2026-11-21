"""RT-PETS-PAIRING-GATEWAY-ID-AND-UNPAIR-HAVE-THEIR-OWN-CALLS-ON-THE-RUNNING-HERMES: the gateway verbs' typed calls.

``runtime.gateway.id`` / ``.introduce`` / ``.peers.join`` / ``.peers.revoke`` / ``.devices.list`` each run the verb's own handler in
process (``stage42_operation_result``), so the claims here are: the method answers the envelope the verb prints
(one body, two doors), a refusal is the verb's own word on ``error.data``, the typed params reach the verb as
its flags, and only this install's own console may call any of the five (review w1118a.77).

Killing mutations, each seen red:

* drop the ``operation_result_sink`` branch in ``harness_support._print_stage42`` -> every method finds no
  envelope (and the verb prints to stdout), so ``test_gateway_id_answers_the_verbs_own_envelope`` is red;
* drop ``"not_found"`` from ``gateway_actions._ERROR_CODES`` -> the unknown-peer revoke answers 4090,
  ``test_revoking_an_install_nobody_paired_is_not_found`` red;
* drop ``flags["port"] = port`` in ``_runtime_gateway_peers_join`` -> the verb never sees the port,
  ``test_join_hands_the_verb_its_flags`` red;
* drop ``"runtime.gateway.peers.revoke"`` (or ``"runtime.gateway.devices.list"``) from ``LOCAL_CONSOLE_METHODS`` ->
  a console-tier device may unpair (or read the paired-device list), ``test_only_this_installs_console_may_call_them``
  red.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.call_authorization import (
    LOCAL_CONSOLE,
    LOCAL_CONSOLE_METHODS,
    STDIO_OWNER,
    TIER_CONSOLE,
    TIER_READ,
    RpcCaller,
    authorize_call,
)
from agent_runtime.gateway_endpoints import candidates as endpoint_candidates

PEER = "inst_aaaaaaaaaaaa"
METHODS = (
    "runtime.gateway.id",
    "runtime.gateway.introduce",
    "runtime.gateway.peers.join",
    "runtime.gateway.peers.revoke",
    "runtime.gateway.devices.list",
)


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    """The runtime root inside this test's tmp dir: these methods mint and revoke credentials."""

    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    resolved = paths.store_root().resolve()
    assert resolved == root.resolve() or root.resolve() in resolved.parents
    return paths.store_root()


@pytest.fixture(autouse=True)
def gateway_configured(monkeypatch):
    from hermes_cli.harness_parts.serve import gateway_listener

    for home in (gateway_listener, endpoint_candidates):
        monkeypatch.setattr(home, "gateway_listen_config", lambda: ("10.0.0.4", 8765))


def _rpc(method: str, **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "g", "method": method, "params": params},
                                    serve_rpc.RpcContext(caller=STDIO_OWNER))


def _cli(capsys, *argv: str) -> dict:
    from hermes_cli import harness

    parser = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["harness", "gateway", *argv, "--json"])
    args.func(args)
    out = capsys.readouterr().out
    return json.loads(out[out.find("{"):])


def _without_volatile(envelope: dict) -> dict:
    return {key: value for key, value in envelope.items() if key not in {"generated_at", "error_id"}}


def test_gateway_id_answers_the_verbs_own_envelope(root, capsys):
    from agent_runtime.gateway_identity import ensure_install_identity

    ensure_install_identity(root)
    reply = _rpc("runtime.gateway.id")
    assert "error" not in reply, reply
    result = reply["result"]
    assert result["kind"] == "gateway_install"
    assert _without_volatile(result) == _without_volatile(_cli(capsys, "id"))
    assert capsys.readouterr().out == "", "the typed door printed to stdout"


def test_gateway_id_with_no_identity_is_the_verbs_not_found(root):
    reply = _rpc("runtime.gateway.id")
    assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND
    assert reply["error"]["data"]["code"] == "not_found"
    assert "install identity" in reply["error"]["message"]
    assert not (root / "gateway" / "install.json").exists(), "a read must never mint"


def test_introduce_mints_both_halves_through_the_verb(root):
    reply = _rpc("runtime.gateway.introduce", for_install="inst_bbbbbbbbbbbb", for_device="dev_1",
                 correlation="grant_1")
    result = reply["result"]
    assert result["kind"] == "gateway_introduction"
    assert result["correlation"] == "grant_1"
    assert result["for_install_id"] == "inst_bbbbbbbbbbbb" and result["for_device_id"] == "dev_1"
    assert len(result["peer"]["peer_code"]) == 8 and len(result["device"]["code"]) == 8
    assert json.loads(result["peer"]["join_payload"])["peer_code"] == result["peer"]["peer_code"]
    assert result["grant_payload"]["peer_join_payload"] == result["peer"]["join_payload"]


def test_introduce_with_nobody_to_scope_to_is_the_verbs_refusal(root):
    reply = _rpc("runtime.gateway.introduce", note="nobody")
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "no_requester"
    assert reply["error"]["data"]["code"] == "invalid_payload"


def _paired(root):
    from agent_runtime.gateway_peers import record_peer

    record_peer(root, peer_install_id=PEER, secret="f" * 64, display_name="mac",
                endpoints=[{"host": "10.0.0.9", "port": 9000}], cert_fingerprint="ab" * 32)


def test_revoke_revokes_this_installs_edge_through_the_verb(root, monkeypatch):
    from agent_runtime import gateway_announce
    from agent_runtime.gateway_peers import lookup_peer

    told = []
    monkeypatch.setattr(gateway_announce, "announce_to_peers",
                        lambda store, payload, only=None: told.append((payload, only)) or [])
    _paired(root)
    result = _rpc("runtime.gateway.peers.revoke", peer_install_id=PEER)["result"]
    assert result["kind"] == "gateway_peer"
    assert result["revoked"] is True and result["scope"] == "this_install_only"
    assert result["announced"] is False
    assert told == [({"revoked_you": True}, [PEER])]
    assert lookup_peer(root, PEER).revoked is True


def test_revoking_an_install_nobody_paired_is_not_found(root, monkeypatch):
    from agent_runtime import gateway_announce

    monkeypatch.setattr(gateway_announce, "announce_to_peers", lambda store, payload, only=None: [])
    reply = _rpc("runtime.gateway.peers.revoke", peer_install_id="inst_zzzzzzzzzzzz")
    assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND
    assert reply["error"]["data"]["reason"] == "unknown_peer"


def test_devices_list_answers_the_verbs_own_envelope(root, capsys):
    from agent_runtime.serve_gateway_auth import mint_pairing_code, redeem_pairing_code

    redeem_pairing_code(root, mint_pairing_code(root, name="phone", tier="console").code, device_name="phone")
    result = _rpc("runtime.gateway.devices.list")["result"]
    assert result["kind"] == "list" and result["item_kind"] == "gateway_device" and result["count"] == 1
    assert "token" not in json.dumps(result) and "verifier" not in json.dumps(result)
    assert _without_volatile(result) == _without_volatile(_cli(capsys, "devices", "list"))


def test_join_hands_the_verb_its_flags(monkeypatch):
    from hermes_cli.harness_parts.gateway_commands import join
    from hermes_cli.harness_support import _object_envelope, _print_stage42

    seen = []

    def verb(args):
        seen.append(args)
        _print_stage42(_object_envelope("gateway_peer", {"peer_install_id": PEER}), args=args)
        return 0

    monkeypatch.setattr(join, "cmd_gateway_peers_join", verb)
    result = _rpc("runtime.gateway.peers.join", payload='{"peer_code":"ABCD2345"}', expect_fingerprint="ab" * 32,
                  correlation="grant_1", host="10.0.0.9", port=9000)["result"]
    assert result["peer_install_id"] == PEER
    (args,) = seen
    assert (args.payload, args.expect_fingerprint, args.correlation, args.host, args.port) == (
        '{"peer_code":"ABCD2345"}', "ab" * 32, "grant_1", "10.0.0.9", 9000)


def test_a_join_payload_that_is_not_json_is_the_verbs_refusal_and_dials_nothing(monkeypatch):
    from agent_runtime import serve_socket

    def explode(*args, **kwargs):
        raise AssertionError("a refused payload opened a connection")

    monkeypatch.setattr(serve_socket.client, "ServeSocketClient", explode)
    reply = _rpc("runtime.gateway.peers.join", payload="{not json")
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "payload_not_json"


@pytest.mark.parametrize("params", [{}, {"payload": 7}, {"payload": "ABCD2345", "host": "10.0.0.9"},
                                    {"payload": "ABCD2345", "host": "10.0.0.9", "port": "9000"},
                                    {"payload": "ABCD2345", "host": "10.0.0.9", "port": 0}])
def test_a_malformed_join_is_refused_before_the_verb(params, monkeypatch):
    from hermes_cli.harness_parts.gateway_commands import join

    monkeypatch.setattr(join, "cmd_gateway_peers_join", lambda args: pytest.fail("the verb ran"))
    assert _rpc("runtime.gateway.peers.join", **params)["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS


def test_revoke_needs_an_install_id():
    assert _rpc("runtime.gateway.peers.revoke")["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS


@pytest.mark.parametrize("method", METHODS)
def test_only_this_installs_console_may_call_them(method):
    """A paired CONSOLE device is the case that matters: right strength, wrong kind."""

    assert method in LOCAL_CONSOLE_METHODS
    tier = serve_rpc.method_tier(method)
    for caller in (RpcCaller(kind="device", device_id="dev_1", device_tier=TIER_CONSOLE),
                   RpcCaller(kind="device", device_id="dev_2", device_tier=TIER_READ),
                   RpcCaller(kind="peer", peer_install_id=PEER)):
        verdict = authorize_call(tier, caller, method=method)
        assert verdict.ok is False and verdict.reason == "scope_denied", (method, caller.kind)
    assert authorize_call(tier, STDIO_OWNER, method=method).ok is True
    assert authorize_call(tier, LOCAL_CONSOLE, method=method).ok is True


def test_the_manifest_publishes_them_with_their_tiers_and_params():
    published = serve_rpc.manifest()
    assert set(METHODS) <= set(published["methods"])
    assert published["tiers"]["runtime.gateway.id"] == TIER_READ
    assert published["tiers"]["runtime.gateway.devices.list"] == TIER_READ
    for method in METHODS[1:4]:
        assert published["tiers"][method] == TIER_CONSOLE
    assert published["params"]["runtime.gateway.peers.revoke"] == ["peer_install_id"]
    assert published["params"]["runtime.gateway.peers.join"] == [
        "correlation", "expect_fingerprint", "host", "payload", "port"]
