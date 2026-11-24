"""Every per-connection map is keyed on the caller the transport PROVED, never a bare ``conn-N``.

Hermes row ``RT-FU-A-PHONE-AND-THE-LOCAL-APP-ON-THE-SAME-CONNECTION-NUMBER-GET-EACH-OTHERS-ANSWERS``:
the loopback listener, the gateway listener and each reverse lane minted ``conn-N`` from their own
counts, so a paired phone and the local app both held ``conn-1`` and got each other's answers.
``RpcCaller.route_owner`` is the one writer of the routing key, ``_sink_for`` checks a cached sink
before a reply leaves, and one count per process numbers every admitter. The real-socket halves
are in ``test_serve_gateway_lane.py``. Killing mutations are named on each test; reds recorded in
the landing commit.
"""

from __future__ import annotations

import socket
import threading
from types import SimpleNamespace

import pytest

from agent_runtime.address import Kind
from agent_runtime.call_authorization import (
    ROUTE_MACHINE_NOT_PROVEN,
    ROUTE_MACHINE_OUTSIDE_SPEC,
    ROUTE_MACHINE_UNPROVEN,
    RpcCaller,
    caller_for_connection,
)
from agent_runtime.serve_socket import admit
from hermes_cli.harness_parts.serve.frames import _SafeSink
from hermes_cli.harness_parts.serve.subscriptions import SubscriptionLanes


def _connection(key: str = "conn-1", transport: str = "socket", **stamps) -> SimpleNamespace:
    return SimpleNamespace(key=key, transport=transport, authenticated=True, client=None, **stamps)


# ── (5) the key names the proven caller, inside the address order ───────────


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        (_connection(), "machine:unproven:not_proven/namespace:unproven/local_console/conn-1"),
        (
            _connection(transport="gateway", device_id="dev_a", device_tier="console"),
            "machine:unproven:not_proven/namespace:unproven/device:dev_a/conn-1",
        ),
        (_connection(transport="gateway", peer_install_id="inst_b"), "machine:unproven:not_proven/namespace:unproven/peer:inst_b/conn-1"),
        (
            _connection(transport="gateway", computer_id="cmp_c", computer_grant="account"),
            "machine:unproven:not_proven/namespace:unproven/computer:cmp_c/conn-1",
        ),
        (_connection(transport="gateway"), "machine:unproven:not_proven/namespace:unproven/unknown:gateway/conn-1"),
    ],
    ids=["local_console", "device", "peer", "computer", "unknown"],
)
def test_the_route_owner_names_each_callers_proven_id_after_an_unproven_machine(connection, expected):
    """MUTATION: ``route_owner`` returns ``self.connection_key`` (the bare key) -> red."""

    assert caller_for_connection(connection).route_owner() == expected


@pytest.mark.parametrize(
    ("stamps", "who"),
    [
        ({}, "local_console"),
        ({"transport": "gateway", "device_id": "dev_a", "device_tier": "console"}, "device:dev_a"),
        ({"transport": "gateway", "peer_install_id": "inst_b"}, "peer:inst_b"),
        ({"transport": "gateway", "computer_id": "cmp_c", "computer_grant": "account"}, "computer:cmp_c"),
    ],
    ids=["local_console", "device", "peer", "computer"],
)
def test_route_owner_writes_the_whole_address(stamps, who):
    """The machine the handshake stamped off the credential row, then the serve's namespace, every
    time (owner 2026-11-24: "2 keep it all , its a consistent standard like how ip addresses and
    ports work"; hermes ``RT-ACCOUNT-ONLY-A-CONNECTION-FROM-ANOTHER-MACHINE-…``).

    MUTATION: drop the namespace segment in ``route_owner`` -> red.
    MUTATION: keep writing ``ROUTE_MACHINE_UNPROVEN`` for a stamped machine -> red."""

    connection = _connection(machine_id="mach_row", namespace="acct-0123456789abcdef", **stamps)
    owner = caller_for_connection(connection).route_owner()
    assert owner == f"machine:mach_row/namespace:acct-0123456789abcdef/{who}/conn-1"
    assert ROUTE_MACHINE_UNPROVEN == f"{Kind.MACHINE.value}:unproven"
    assert caller_for_connection(None).route_owner() == "stdio"


def test_a_channel_that_proves_no_machine_routes_outside_spec():
    """A channel (the owner's external gateway, no device of yours) is stamped no machine, and its key
    says why: outside the spec, not a proof that failed (owner 2026-11-24: "1 maybe they should be
    unproven reason: outside of spec but still function as usual?").

    MUTATION: drop the channel arm in ``RpcCaller._route_machine`` -> red."""

    channel = _connection(transport="gateway", device_id="dev_ch", device_tier="console",
                          device_kind="channel", namespace="base")
    assert caller_for_connection(channel).route_owner() == (
        "machine:unproven:outside_spec/namespace:base/device:dev_ch/conn-1")
    assert ROUTE_MACHINE_OUTSIDE_SPEC.startswith(ROUTE_MACHINE_UNPROVEN + ":")
    assert ROUTE_MACHINE_NOT_PROVEN.startswith(ROUTE_MACHINE_UNPROVEN + ":")


@pytest.mark.parametrize(
    "stamps",
    [
        {"transport": "gateway", "device_id": "dev_d", "device_tier": "console", "device_kind": "device"},
        {},
    ],
    ids=["gateway_device", "local_console"],
)
def test_a_caller_that_should_prove_a_machine_and_did_not_routes_not_proven(stamps):
    """MUTATION: answer ``ROUTE_MACHINE_OUTSIDE_SPEC`` for every machine-less caller -> red."""

    owner = caller_for_connection(_connection(namespace="base", **stamps)).route_owner()
    assert owner.startswith("machine:unproven:not_proven/namespace:base/"), owner


def test_a_gateway_device_that_is_not_a_channel_is_never_outside_spec():
    """The channel is read off the row's kind, never the transport.

    MUTATION: read the channel off ``transport == "gateway"`` in ``_route_machine`` -> red."""

    for kind in ("device", None):
        device = _connection(transport="gateway", device_id="dev_e", device_tier="console", device_kind=kind)
        assert caller_for_connection(device).route_owner().startswith(ROUTE_MACHINE_NOT_PROVEN + "/"), kind
    stamped = _connection(transport="gateway", device_id="dev_ch", device_tier="console",
                          device_kind="channel", machine_id="mach_row", namespace="base")
    assert caller_for_connection(stamped).route_owner() == "machine:mach_row/namespace:base/device:dev_ch/conn-1"


def test_a_device_and_the_local_app_on_one_number_get_two_route_owners():
    local = caller_for_connection(_connection())
    phone = caller_for_connection(_connection(transport="gateway", device_id="dev_a", device_tier="console"))
    assert local.connection_key == phone.connection_key == "conn-1"
    assert local.route_owner() != phone.route_owner()


# ── (3) the check before a reply leaves ───────────────────────────────────────


class _Lanes(SubscriptionLanes):
    def __init__(self) -> None:
        self.frames = object()
        self.boot_id = "boot-test"
        self.connection_sinks: dict[str, _SafeSink] = {}
        self.connection_sinks_lock = threading.Lock()
        self.logged: list[dict] = []

    def _service_log(self, record: dict) -> None:
        self.logged.append(record)


def test_a_cached_sink_for_another_connection_is_never_handed_out_and_the_mismatch_is_logged():
    """MUTATION: ``_sink_routes_to`` returns ``True`` (delete the identity/owner comparison) -> the
    asking connection is handed the other connection's sink, red."""

    lanes = _Lanes()
    asking = _connection()
    other = _connection(transport="gateway", device_id="dev_a", device_tier="console")
    owner = lanes._owner_of(asking)
    misfiled = _SafeSink(other)
    lanes.connection_sinks[owner] = misfiled

    sink = lanes._sink_for(asking)

    assert sink is not misfiled and sink._target is asking
    assert lanes.connection_sinks[owner] is sink
    [record] = [item for item in lanes.logged if item["event"] == "serve_reply_route_mismatch"]
    assert record["asking_owner"] == owner
    assert record["cached_owner"] == "machine:unproven:not_proven/namespace:unproven/device:dev_a/conn-1"
    assert record["cached"]["device_id"] == "dev_a"
    assert "token" not in repr(record)
    # The connection's own sink is stable and logs nothing more.
    assert lanes._sink_for(asking) is sink
    assert len(lanes.logged) == 1


def test_the_sink_cache_is_filed_under_the_route_owner():
    lanes = _Lanes()
    phone = _connection(transport="gateway", device_id="dev_a", device_tier="console")
    local = _connection()
    assert lanes._sink_for(phone) is not lanes._sink_for(local)
    assert set(lanes.connection_sinks) == {
        "machine:unproven:not_proven/namespace:unproven/device:dev_a/conn-1",
        "machine:unproven:not_proven/namespace:unproven/local_console/conn-1",
    }


# ── (4) one connection count per process ─────────────────────────────────────


class _Minted(Exception):
    pass


def test_two_admitters_never_mint_the_same_connection_key(monkeypatch, tmp_path):
    """MUTATION: restore the per-instance ``self._next_connection`` count -> both admitters mint
    ``conn-1``, red."""

    minted: list[str] = []

    def _record(**fields):
        minted.append(fields["key"])
        raise _Minted

    monkeypatch.setattr(admit, "SocketConnection", _record)

    def _admitter(name: str) -> admit.ConnectionAdmitter:
        return admit.ConnectionAdmitter(
            tmp_path,
            boot_id="boot-test",
            dispatch_line=lambda line, connection: None,
            hello_payload=lambda hello, connection: {},
            token_provider=lambda: None,
            transport_name=name,
        )

    for admitter in (_admitter("socket"), _admitter("gateway")):
        left, right = socket.socketpair()
        try:
            with pytest.raises(_Minted):
                admitter.admit(left, ("127.0.0.1", 0))
        finally:
            left.close()
            right.close()

    assert len(minted) == 2 and minted[0] != minted[1], minted


def test_route_owner_is_the_only_writer_of_the_key_format():
    """No second hand-written copy of the format under the serve package (the row's done-when grep)."""

    from pathlib import Path

    import hermes_cli.harness_parts.serve as serve_pkg

    root = Path(serve_pkg.__file__).parent
    offenders = [
        path.name
        for path in root.glob("*.py")
        if ROUTE_MACHINE_UNPROVEN in path.read_text(encoding="utf-8")
        or "connection_sinks.get(connection.key" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders
    assert RpcCaller().route_owner() == "stdio"
