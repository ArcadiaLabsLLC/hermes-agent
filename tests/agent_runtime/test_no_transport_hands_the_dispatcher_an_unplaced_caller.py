"""No transport hands the dispatcher a caller it could not place (``unknown``).

The premise ``authorize_call``'s refusal of an ``unknown`` caller rests on (hermes row
``RT-FU-HERMES-PAIRS-A-DEVICE-ONLY-AT-FULL-CONTROL-WITH-NO-VIEW-ONLY-LEVEL``): the read opening
used to answer ``unknown`` too, and closing it is free only if no live connection arrives as one.
Pinned over the REAL ``serve_loop`` on every lane a request reaches it by — stdio, the loopback
socket and the gateway listener — with the transport's one identity door
(``call_authorization.caller_for_connection``, which ``handle_message`` asks per frame) recorded,
and every way a hello can fail tried on the way: a frame before any hello, a wrong install token,
the install token on the gateway lane, an unpaired device. A rejected connection never joins the
connection table, so it never reaches the dispatcher at all.

Killing mutation (red seen 2026-11-23): drop ``connection.authenticated = True`` in
``serve_socket/handshake.py``'s accept path, and every socket and gateway request records
``unknown``.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime import call_authorization
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    CALLER_LOCAL_CONSOLE,
    CALLER_STDIO_OWNER,
    CALLER_UNKNOWN,
)
from agent_runtime.serve_socket import ServeSocketClient

from tests.agent_runtime.test_serve_gateway_lane import (
    WAIT,
    _rpc,
    device_client,
    gateway_on,  # noqa: F401 - the fixture, used by name
    pair_device,
    running_serve,
)


@pytest.fixture
def placed(monkeypatch) -> list[str]:
    """Every caller kind the transport hands the dispatcher, in order."""

    seen: list[str] = []
    real = call_authorization.caller_for_connection

    def _recording(connection):
        caller = real(connection)
        seen.append(caller.kind)
        return caller

    monkeypatch.setattr(call_authorization, "caller_for_connection", _recording)
    return seen


def _wait_for_reply(sink, rid: str) -> dict:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        for frame in sink.frames():
            if frame.get("id") == rid and "jsonrpc" in frame:
                return frame
        time.sleep(0.01)
    raise AssertionError(f"no reply to {rid!r} on stdio")


def _first_event(connection, *events: str) -> dict:
    """The first frame naming one of *events* (the server speaks first: a ``server_hello``)."""

    for _ in range(10):
        frame = connection.read_frame()
        if frame is None:
            raise AssertionError("connection closed before " + " or ".join(events))
        if frame.get("event") in events:
            return frame
    raise AssertionError("no " + " or ".join(events))


def _gateway_hello(handle, **hello) -> dict:
    connection = ServeSocketClient(
        "127.0.0.1", handle.gateway_port, timeout_seconds=WAIT, tls=True,
        cert_fingerprint=handle.fingerprint,
    )
    connection.connect()
    try:
        if "token" in hello:
            reply = connection.hello(token=hello["token"], client="probe")
        else:
            reply = connection.device_hello(device_id=hello["device_id"], token=hello["device_token"], client="probe")
        if reply.get("event") != "hello_ok":
            return reply
        return _rpc(connection, "runtime.health")
    finally:
        connection.close()


def test_no_transport_hands_the_dispatcher_an_unplaced_caller(gateway_on, placed):  # noqa: F811
    from agent_runtime.serve_auth import read_token
    from tests.agent_runtime.test_serve_socket_lane import _store_root

    credential = pair_device()
    with running_serve() as handle:
        # stdio: the owner's own pipe.
        handle.pipe.send({"jsonrpc": "2.0", "id": "s-1", "method": "runtime.health", "params": {}})
        _wait_for_reply(handle.sink, "s-1")

        # The loopback socket, a request before any hello: refused at the door.
        raw = ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT)
        raw.connect()
        try:
            raw.send({"jsonrpc": "2.0", "id": "early", "method": "runtime.health", "params": {}})
            assert _first_event(raw, "hello_rejected")["event"] == "hello_rejected"
        finally:
            raw.close()
        # The loopback socket, a wrong token, then the right one.
        wrong = ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT)
        wrong.connect()
        try:
            assert wrong.hello(token="0" * 64, client="probe")["event"] == "hello_rejected"
        finally:
            wrong.close()
        good = ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT)
        good.connect()
        try:
            assert good.hello(token=read_token(_store_root()) or "", client="probe")["event"] == "hello_ok"
            assert "result" in _rpc(good, "runtime.health")
        finally:
            good.close()

        # The gateway listener: the install token, an unpaired device, then a paired one.
        assert _gateway_hello(handle, token=read_token(_store_root()) or "")["event"] == "hello_rejected"
        assert _gateway_hello(handle, device_id="dev_never_paired", device_token=credential.token)["event"] == "hello_rejected"
        with device_client(handle, credential) as (connection, reply):
            assert reply["event"] == "hello_ok"
            assert "result" in _rpc(connection, "runtime.health")

    assert CALLER_UNKNOWN not in placed, placed
    assert {CALLER_LOCAL_CONSOLE, CALLER_DEVICE} <= set(placed), placed
    assert set(placed) <= {CALLER_STDIO_OWNER, CALLER_LOCAL_CONSOLE, CALLER_DEVICE}, placed
