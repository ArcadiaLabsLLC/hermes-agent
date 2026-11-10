"""RT-EXTERNAL-GATEWAY-SWITCH-GATE: a channel credential only while the external switch names us.

Plan ``docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md`` §2 D5
(owner ruling 2026-11-05: yes). The switch is ``<base>/namespace-active.json`` — the "Allow agent
use outside the launcher" record — and :func:`gateway_channel.external_access_on` reads it against
THIS process's ``HERMES_NAMESPACE``. The hello tests run a REAL serve with the gateway lane over
TLS; the process env is never namespaced (a namespaced test process would resolve stores the
isolation assertion refuses), so the switch reads a crafted env through the real record reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import gateway_channel, serve_rpc
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    TIER_CONSOLE,
    TRANSPORT_GATEWAY,
    RpcCaller,
)
from agent_runtime.serve_gateway_auth import (
    DeviceCredential,
    PairingCode,
    lookup_device,
    mint_pairing_code,
    redeem_pairing_code,
)
from agent_runtime.serve_socket import ServeSocketClient
from tests.agent_runtime.test_serve_gateway_lane import (
    WAIT,
    _store_root,
    device_client,
    gateway_on,  # fixture
    running_serve,
)

NAMESPACE = "acct-0123456789abcdef"
BOUND = "personainst_qa"


def _env(base: Path, namespace: str = NAMESPACE) -> dict[str, str]:
    return {"HERMES_NAMESPACE": namespace, "HERMES_DEPENDENCY_ROOT": str(base)}


def _record(base: Path, namespace: str | None) -> None:
    path = base / "namespace-active.json"
    if namespace is None:
        path.unlink(missing_ok=True)
        return
    base.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "namespace": namespace}), encoding="utf-8")


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """The real record reader, against a base root under ``tmp_path`` and THIS namespace."""

    base = tmp_path / "hermes-base"
    real = gateway_channel.external_access_on
    monkeypatch.setattr(gateway_channel, "external_access_on", lambda env=None: real(_env(base)))
    return base


def _channel_credential() -> DeviceCredential:
    code = mint_pairing_code(_store_root(), name="bot", kind=DEVICE_KIND_CHANNEL, bound_instances=[BOUND])
    assert isinstance(code, PairingCode)
    credential = redeem_pairing_code(_store_root(), code.code)
    assert isinstance(credential, DeviceCredential)
    return credential


# ── the predicate ────────────────────────────────────────────────────────────


def test_the_switch_is_on_only_while_the_record_names_this_namespace(tmp_path: Path):
    base = tmp_path / "base"
    _record(base, None)
    assert gateway_channel.external_access_on(_env(base)) is False
    _record(base, "acct-ffffffffffffffff")
    assert gateway_channel.external_access_on(_env(base)) is False
    _record(base, NAMESPACE)
    assert gateway_channel.external_access_on(_env(base)) is True
    # A base-root process (no namespace) never honours one: no record can name the base root.
    assert gateway_channel.external_access_on({"HERMES_DEPENDENCY_ROOT": str(base)}) is False
    (base / "namespace-active.json").write_text("{not json", encoding="utf-8")
    assert gateway_channel.external_access_on(_env(base)) is False


# ── the hello ────────────────────────────────────────────────────────────────


def test_a_channel_hello_is_refused_while_the_record_names_another_namespace(gateway_on, switch):
    """Killing mutation: skip the record read in ``serve_gateway_credentials._channel_switch_off``
    (return ``False``) → the hello is admitted and the first assertion reds."""

    credential = _channel_credential()
    _record(switch, "acct-ffffffffffffffff")
    with running_serve() as handle:
        with device_client(handle, credential) as (_connection, reply):
            assert (reply.get("event"), reply.get("reason")) == ("hello_rejected", "external_access_off"), reply
        _record(switch, NAMESPACE)
        with device_client(handle, credential) as (_connection, reply):
            assert reply["event"] == "hello_ok", reply


def test_a_plain_device_ignores_the_switch(gateway_on, switch):
    code = mint_pairing_code(_store_root(), name="phone")
    credential = redeem_pairing_code(_store_root(), code.code)
    _record(switch, None)
    with running_serve() as handle:
        with device_client(handle, credential) as (_connection, reply):
            assert reply["event"] == "hello_ok", reply


def test_a_channel_code_redeemed_while_the_switch_is_off_leaves_no_live_row(gateway_on, switch):
    _record(switch, NAMESPACE)
    code = mint_pairing_code(_store_root(), name="bot", kind=DEVICE_KIND_CHANNEL, bound_instances=[BOUND])
    _record(switch, None)
    with running_serve() as handle:
        connection = ServeSocketClient("127.0.0.1", handle.gateway_port, timeout_seconds=WAIT,
                                       cert_fingerprint=handle.fingerprint)
        connection.connect()
        try:
            reply = connection.pair_hello(pairing_code=code.code, client="bot")
        finally:
            connection.close()
    assert reply["event"] == "hello_rejected" and reply["reason"] == "external_access_off", reply
    from agent_runtime.serve_gateway_auth import list_devices

    [record] = list_devices(_store_root())
    assert record.revoked and record.kind == DEVICE_KIND_CHANNEL
    assert lookup_device(_store_root(), record.device_id).revoked


def test_a_channel_code_redeemed_while_the_switch_is_on_learns_its_binding(gateway_on, switch):
    _record(switch, NAMESPACE)
    code = mint_pairing_code(_store_root(), name="bot", kind=DEVICE_KIND_CHANNEL, bound_instances=[BOUND])
    with running_serve() as handle:
        connection = ServeSocketClient("127.0.0.1", handle.gateway_port, timeout_seconds=WAIT,
                                       cert_fingerprint=handle.fingerprint)
        connection.connect()
        try:
            reply = connection.pair_hello(pairing_code=code.code, client="bot")
        finally:
            connection.close()
    assert reply["event"] == "hello_ok", reply
    assert reply["paired"]["kind"] == "channel" and reply["paired"]["bound_instances"] == [BOUND]


# ── every call, too ──────────────────────────────────────────────────────────


def test_a_connected_channel_is_stopped_at_its_next_call_once_the_switch_goes_off(switch):
    caller = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_bot",
                       device_tier=TIER_CONSOLE, device_kind=DEVICE_KIND_CHANNEL, bound_instances=(BOUND,))
    _record(switch, None)
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "s-1", "method": "runtime.chat.message",
         "params": {"turn_request_id": "t", "persona_id": "qa", "persona_instance_id": BOUND, "message": "hi"}},
        context=serve_rpc.RpcContext(caller=caller))
    assert reply["error"]["data"]["reason"] == "external_access_off", reply


def test_a_channel_cannot_hold_the_office_stream(gateway_on, switch):
    _record(switch, NAMESPACE)
    credential = _channel_credential()
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, reply):
            assert reply["event"] == "hello_ok", reply
            connection.send({"op": "subscribe", "lane": "stream"})
            frame = connection.read_frame()
    assert frame["event"] == "subscribe_denied" and frame["reason"] == "channel_credential", frame
