""""Allow access" off — your devices still reach this computer, and none of them may use it.

Hermes row ``RT-ACCOUNT-ONLY-A-COMPUTER-WITH-ALLOW-ACCESS-OFF-STAYS-REACHABLE-BUT-LETS-NONE-OF-YOUR-DEVICES-USE-IT``.
``runtime.gateway.access.set`` writes ``remote_gateway_access``; ``call_authorization``'s access arm refuses
a device or peer ``access_off`` outside ``ACCESS_OFF_ANSWERS``; a change closes every open device, peer and
channel connection. Witnesses: the dispatcher's typed refusal, and a real gateway listener's connection table.
Each test names its killing mutation. (The park-while-off test lives in ``test_reverse_lane.py``, beside
the lane fixtures.)
"""

from __future__ import annotations

import time

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import (
    CALLER_COMPUTER,
    CALLER_DEVICE,
    CALLER_PEER,
    COMPUTER_GRANT_ACCOUNT,
    DEVICE_KIND_CHANNEL,
    LOCAL_CONSOLE,
    STDIO_OWNER,
    TIER_CONSOLE,
    TRANSPORT_GATEWAY,
    RpcCaller,
)
from agent_runtime.gateway_access import REASON_ACCESS_OFF, drop_remote_callers
from agent_runtime.serve_rpc.registry import method_tier

DEVICE = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev-phone",
                   device_tier=TIER_CONSOLE, device_kind="device")
CHANNEL = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev-bot", device_tier=TIER_CONSOLE,
                    device_kind=DEVICE_KIND_CHANNEL, bound_instances=("inst-1",))
PEER = RpcCaller(kind=CALLER_PEER, transport=TRANSPORT_GATEWAY, peer_install_id="inst-far")
COMPUTER = RpcCaller(kind=CALLER_COMPUTER, transport="reverse_lane", computer_id="cmp-1",
                     computer_grant=COMPUTER_GRANT_ACCOUNT)


def _call(method: str, params: dict | None = None, caller: RpcCaller = STDIO_OWNER, **context) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "a", "method": method, "params": params or {}},
                                    serve_rpc.RpcContext(caller=caller, **context))


def _reason(frame: dict) -> str | None:
    return ((frame.get("error") or {}).get("data") or {}).get("reason")


def _access(allow: bool) -> dict:
    reply = _call("runtime.gateway.access.set", {"allow": allow})
    assert "result" in reply, reply
    return reply["result"]


@pytest.fixture
def access_off():
    _access(False)
    yield


def test_access_off_refuses_a_device_a_read_verb_and_a_console_verb(access_off):
    """Mutation: drop the ``_access_arm`` call from ``authorize_call`` -> both are answered by tier, red."""
    assert method_tier("runtime.health") == "read" and method_tier("runtime.agent.directory") == "console"
    for name in ("runtime.health", "runtime.agent.directory"):
        reply = _call(name, caller=DEVICE)
        assert _reason(reply) == REASON_ACCESS_OFF, reply


def test_access_off_still_answers_a_device_its_reverse_offer(access_off):
    """Mutation: empty ``ACCESS_OFF_ANSWERS`` -> the phone's offer is refused ``access_off``, red."""
    for name in ("runtime.gateway.reverse.offer", "runtime.gateway.reverse.withdraw"):
        reply = _call(name, caller=DEVICE)
        assert _reason(reply) != REASON_ACCESS_OFF, reply
        assert _reason(reply) != "scope_denied", reply


def test_access_off_answers_a_peer_ping_and_refuses_its_chat_turn(access_off):
    """Mutation: place the access arm after the peer arm -> the peer's chat turn is admitted, red."""
    assert "result" in _call("peer.ping", caller=PEER)
    assert _reason(_call("peer.agent_chat.execute", {"target": "x", "message": "hi"}, caller=PEER)) == REASON_ACCESS_OFF


def test_access_off_leaves_the_console_and_a_computer_answered(access_off):
    """Mutation: apply the arm to every kind (drop ``is_remote_user``) -> the console is refused, red."""
    from agent_runtime.call_authorization import authorize_call

    for caller in (STDIO_OWNER, LOCAL_CONSOLE, COMPUTER):
        for tier, name in (("read", "runtime.health"), ("console", "runtime.agent.directory")):
            decision = authorize_call(tier, caller, method=name)
            assert decision.ok and decision.reason != REASON_ACCESS_OFF, (caller.kind, name, decision)


def test_access_off_refuses_a_channel_credential_its_chat_verb(access_off):
    """Mutation: exempt channels in ``_access_arm`` -> the bot's chat turn reaches the channel arm, red."""
    reply = _call("runtime.chat.message", {"persona_instance_id": "inst-1", "message": "hi"}, caller=CHANNEL)
    assert _reason(reply) == REASON_ACCESS_OFF, reply


def test_a_device_calling_access_set_is_refused():
    """Mutation: leave ``runtime.gateway.access.set`` out of ``LOCAL_CONSOLE_METHODS`` -> a console-tier
    device may switch this computer's access, red (access is ON here, so only that set refuses it)."""
    from hermes_cli.config import read_user_config_raw

    before = read_user_config_raw()
    reply = _call("runtime.gateway.access.set", {"allow": False}, caller=DEVICE)
    assert _reason(reply) == "scope_denied", reply
    assert read_user_config_raw() == before


def test_an_absent_key_answers_a_device_as_today():
    """Mutation: read an absent key as off in ``gateway_access_allowed`` -> the device is refused, red."""
    from agent_runtime.gateway_access import ACCESS_KEY
    from agent_runtime.harness_settings import harness_setting

    assert harness_setting(ACCESS_KEY, "absent") == "absent"
    assert _reason(_call("runtime.health", caller=DEVICE)) != REASON_ACCESS_OFF
    assert "result" in _call("runtime.health", caller=DEVICE)


def test_access_set_writes_the_flag_answers_changed_and_refuses_a_non_bool():
    assert _access(True) == {"access": True, "changed": False, "closed": 0}  # absent already answered allowed
    assert _access(False) == {"access": False, "changed": True, "closed": 0}
    assert _access(False)["changed"] is False
    assert _access(True)["changed"] is True
    for params in ({"allow": "false"}, {}, {"allow": False, "listen": "0.0.0.0"}):
        assert _reason(_call("runtime.gateway.access.set", params)) == "invalid_request"


# ── the close on change, on a real gateway listener ───────────────────────────


def test_turning_access_off_closes_an_open_device_subscription(tmp_path):
    """Mutation: skip the ``close_remote_callers`` call in ``_runtime_gateway_access_set`` -> the device's
    connection (and every subscription riding it) stays open after the off, red."""
    from tests.agent_runtime.test_reverse_lane import WAIT, _Computer

    from agent_runtime.serve_gateway_auth import device_proof
    from agent_runtime.serve_socket import ServeSocketClient

    computer = _Computer(tmp_path / "computer-root")
    try:
        device = computer.pair_phone()
        client = ServeSocketClient("127.0.0.1", computer.gateway_port, timeout_seconds=WAIT,
                                   cert_fingerprint=computer.fingerprint)
        client.connect()
        nonce = client._challenge_nonce(3)
        client.send({"op": "hello", "client": "phone", "device_id": device.device_id,
                     "proof": device_proof(device.token, nonce, port=computer.gateway_port, device_id=device.device_id)})
        assert (client.read_frame() or {}).get("event") == "hello_ok"
        assert len(computer.gateway.connections()) == 1

        door = lambda reason: drop_remote_callers((computer.loopback, computer.gateway), reason=reason)  # noqa: E731
        answer = _call("runtime.gateway.access.set", {"allow": False}, close_remote_callers=door)
        assert answer["result"] == {"access": False, "changed": True, "closed": 1}, answer
        deadline = time.monotonic() + WAIT
        while computer.gateway.connections() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert computer.gateway.connections() == []
        client.close()
    finally:
        computer.close()


# ── what a device reads at its hello, and the office stream ───────────────────


class _Conn:
    def __init__(self, **stamps) -> None:
        self.transport, self.key, self.authenticated = TRANSPORT_GATEWAY, "conn-1", True
        self.device_id = self.device_tier = self.device_kind = self.peer_install_id = None
        self.computer_id = self.computer_grant = None
        self.__dict__.update(stamps)


_PHONE_CONN = dict(device_id="dev-phone", device_tier=TIER_CONSOLE, device_kind="device")


def test_a_devices_and_a_peers_hello_says_access_and_the_consoles_does_not():
    """Mutation: answer ``{}`` from ``_access_block`` for every caller -> the device never learns it is off, red."""
    from hermes_cli.harness_parts.serve.manifest import _access_block

    assert _access_block(_Conn(**_PHONE_CONN)) == {"access": True}
    _access(False)
    assert _access_block(_Conn(**_PHONE_CONN)) == {"access": False}
    assert _access_block(_Conn(peer_install_id="inst-far")) == {"access": False}
    assert _access_block(_Conn(transport="socket")) == {}


def test_access_off_refuses_a_device_the_office_stream():
    """Mutation: drop the ``access_off`` refusal in ``_op_subscribe`` -> the device watches the office, red."""
    from hermes_cli.harness_parts.serve.handle_message import MessageHandling

    class _Session:
        drain_state = "stop-here"  # a subscribe that got past the access check is denied ``draining``

        def __init__(self) -> None:
            self.denied: list[str] = []

        def _deny_subscribe(self, sink, connection, lane, reason, **_):
            self.denied.append(reason)

    _access(False)
    session = _Session()
    MessageHandling._op_subscribe(session, {"op": "subscribe", "lane": "stream"}, None, _Conn(**_PHONE_CONN))
    assert session.denied == [REASON_ACCESS_OFF]
    _access(True)
    MessageHandling._op_subscribe(session, {"op": "subscribe", "lane": "stream"}, None, _Conn(**_PHONE_CONN))
    assert session.denied == [REASON_ACCESS_OFF, "draining"]
