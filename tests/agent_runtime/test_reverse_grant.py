"""The phone's grant to a paired computer: the switch, the offer, the accept (two consents).

Row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS`` (Eternia), plan
``PHONE_DRIVEN_BY_A_COMPUTER_2026-11-21`` §4 and §15, review w1118a.79. The PHONE is the real
``serve_loop`` over its pipe (as in ``test_reverse_lane``); the COMPUTER is its two real listeners
with a dispatcher that runs the real ``handle_request`` with each connection's own caller, so the
offer arrives as the paired device that sent it, over real TLS under a real pin.

Killing mutations (each named at its line):

* ``reverse_lane.offer.grant_and_offer``: keep the grant when the offer did not land, and the
  unreachable-offer test finds a grant the computer never received;
* ``serve_rpc.reverse_lane._runtime_gateway_reverse_offer``: accept any caller, and the owner's
  own offer is held;
* ``reverse_lane.accepts.list_accepts``: answer a row whose device was unpaired, and the
  computer-unpair test still lists the phone as accepted;
* ``ReverseLanes.status``: skip the parked-lane eviction, and the hang-up test reads the phone
  still parked.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime.call_authorization import caller_for_connection
from agent_runtime.gateway_tls import ensure_certificate, server_ssl_context
from agent_runtime.reverse_lane import accepts, grants
from agent_runtime.reverse_lane.lanes import ReverseLanes, handoff
from agent_runtime.serve_gateway_auth import (
    DeviceCredential,
    PairingCode,
    mint_pairing_code,
    redeem_pairing_code,
    revoke_device,
)
from agent_runtime.serve_rpc.dispatch import handle_request
from agent_runtime.serve_rpc.protocol import RpcContext
from agent_runtime.serve_socket import ServeSocketClient
from agent_runtime.serve_socket.server import ServeSocketServer
from hermes_cli.harness_parts.serve import gateway_listener
from tests.agent_runtime.test_reverse_lane import ROOT_TOKEN, WAIT, _phone_root, phone  # noqa: F401

INSTALL = "computer-install"


class _Computer:
    """The computer's two listeners, dispatching real RPC as each connection's own caller."""

    def __init__(self, root: Path) -> None:
        self.root = root
        certificate = ensure_certificate(root)
        assert certificate.ok
        self.fingerprint = certificate.fingerprint
        self.lanes = ReverseLanes(root)
        hook = lambda admitter, connection, reader, message: handoff(  # noqa: E731
            self.lanes, admitter, connection, reader, message)
        common = dict(boot_id="computer-boot", dispatch_line=self._dispatch,
                      hello_payload=lambda message, c: {"event": "hello_ok", "transport": c.transport},
                      handoff=hook, reject_penalty_seconds=0.0)
        self.gateway = ServeSocketServer(
            root, token_provider=lambda: None, authenticator=gateway_listener._gateway_authenticator(root),
            ssl_context=server_ssl_context(root), host="127.0.0.1", transport_name="gateway", **common)
        self.gateway_port = self.gateway.bind()
        self.gateway.start_accepting()

    def _dispatch(self, line: str, connection) -> None:
        reply = handle_request(json.loads(line), RpcContext(
            connection_key=connection.key, transport=connection.transport, emit=connection.emit,
            caller=caller_for_connection(connection), reverse_lanes=lambda: self.lanes))
        connection.emit(reply)

    def owner(self, method: str, params: dict | None = None) -> dict:
        """The computer's owner's Eternia, on its own pipe (the stdio owner)."""

        return handle_request({"jsonrpc": "2.0", "id": "owner", "method": method, "params": params or {}},
                              RpcContext(reverse_lanes=lambda: self.lanes))

    def pair_phone(self) -> DeviceCredential:
        code = mint_pairing_code(self.root, tier=ca.TIER_READ, name="phone")
        assert isinstance(code, PairingCode)
        credential = redeem_pairing_code(self.root, code.code)
        assert isinstance(credential, DeviceCredential)
        return credential

    def close(self) -> None:
        self.lanes.close()
        self.gateway.close()


@pytest.fixture
def computer(tmp_path):
    computer = _Computer(tmp_path / "computer-root")
    try:
        yield computer
    finally:
        computer.close()


def _way(computer: _Computer, device: DeviceCredential, **extra) -> dict:
    return {"computer_install_id": INSTALL, "host": "127.0.0.1", "port": computer.gateway_port,
            "cert_fingerprint": computer.fingerprint, "device_id": device.device_id, "token": device.token,
            **extra}


def _grant(phone, computer: _Computer, level: str = grants.GRANT_LOOK):
    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level=level))
    return device, answer


def test_the_phone_grants_look_the_computer_accepts_and_the_phone_lists_the_record(phone, computer):
    device, answer = _grant(phone, computer)
    assert answer.get("result", {}).get("state") == "offered", answer
    # The minted token is never in the phone's own answer.
    assert "token" not in answer["result"]
    computer_id = answer["result"]["computer_id"]

    # The computer holds the offer as the device that sent it; its listing carries no token.
    offers = computer.owner("runtime.gateway.reverse.lanes")["result"]["offers"]
    assert [(o["device_id"], o["computer_id"], o["level"]) for o in offers] == \
        [(device.device_id, computer_id, "look")]
    assert "token" not in offers[0]

    # Second consent: the computer's owner accepts and gets the token once.
    accepted = computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})["result"]
    assert accepted["computer_id"] == computer_id and accepted["level"] == "look"
    token = accepted["token"]
    assert "error" in computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})
    status = computer.owner("runtime.gateway.reverse.lanes")["result"]
    assert status["offers"] == []
    assert [a["computer_id"] for a in status["accepted"]] == [computer_id]
    assert "token" not in status["accepted"][0]

    # The phone's engine lists the computer's record at read (look), bound to the pairing.
    listed = phone.rpc("runtime.gateway.reverse.lanes")["result"]["grants"]
    assert listed == [{"computer_install_id": INSTALL, "computer_id": computer_id, "level": "look",
                       "pairing_device_id": device.device_id}]
    # The token the computer holds is the one the phone verifies (and the phone stores no token).
    from agent_runtime.serve_gateway_auth.proof import reverse_lane_proof

    proof = reverse_lane_proof(token, "n" * 32, lane_id="a" * 32, device_id=computer_id)
    assert grants.verify_lane_proof(_phone_root(), computer_id, proof, "n" * 32, lane_id="a" * 32)
    assert token not in (Path(_phone_root()) / "gateway" / grants.REVERSE_GRANTS_FILENAME).read_text()

    # Turning the switch off deletes the record.
    assert phone.rpc("runtime.gateway.reverse.revoke", {"computer_install_id": INSTALL})["result"]["revoked"] == 1
    assert phone.rpc("runtime.gateway.reverse.lanes")["result"]["grants"] == []


def test_an_offer_that_does_not_land_leaves_no_grant_on_the_phone(phone, computer):
    """MUTATION (``grant_and_offer``): keep the grant here and this test finds it."""

    device = computer.pair_phone()
    computer.gateway.close()
    answer = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level="chat"))
    assert answer["error"]["data"]["reason"] == "computer_unreachable", answer
    assert grants.grant_for_install(_phone_root(), INSTALL) is None


def test_a_wrong_pin_refuses_the_offer_and_leaves_no_grant(phone, computer):
    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant",
                       {**_way(computer, device, level="look"), "cert_fingerprint": "0" * 64})
    assert answer["error"]["data"]["reason"] == "certificate_rejected", answer
    assert grants.grant_for_install(_phone_root(), INSTALL) is None
    assert computer.owner("runtime.gateway.reverse.lanes")["result"]["offers"] == []


def test_only_a_paired_device_offers(computer):
    """MUTATION (``_runtime_gateway_reverse_offer``): accept any caller and the owner's offer is held."""

    offer = {"computer_id": "cmp-x", "token": "a" * 64, "level": "chat", "phone_install_id": "phone-x"}
    frame = computer.owner("runtime.gateway.reverse.offer", offer)
    assert frame["error"]["data"]["reason"] == ca.REASON_SCOPE_DENIED
    assert computer.lanes.offers.pending() == []


@pytest.mark.parametrize("name", ["runtime.gateway.reverse.grant", "runtime.gateway.reverse.revoke",
                                  "runtime.gateway.reverse.accept", "runtime.gateway.reverse.decline"])
def test_the_grant_and_accept_verbs_answer_only_the_machine_owner(name):
    assert name in ca.LOCAL_CONSOLE_METHODS
    device = ca.RpcCaller(kind=ca.CALLER_DEVICE, device_id="d", device_tier=ca.TIER_CONSOLE,
                          device_kind=ca.DEVICE_KIND_DEVICE, transport="gateway")
    assert not ca.authorize_call(ca.TIER_CONSOLE, device, method=name).ok
    for grant in (grants.GRANT_LOOK, grants.GRANT_CHAT):
        computer = ca.RpcCaller(kind=ca.CALLER_COMPUTER, computer_id="c", computer_grant=grant, transport="gateway")
        assert not ca.authorize_call(ca.TIER_CONSOLE, computer, method=name).ok
    assert "runtime.gateway.reverse.offer" not in ca.COMPUTER_CHAT_METHOD_ALLOWLIST


def test_the_computer_declines_and_the_offer_is_gone(phone, computer):
    device, answer = _grant(phone, computer, grants.GRANT_CHAT)
    assert "result" in answer, answer
    assert computer.owner("runtime.gateway.reverse.decline", {"device_id": device.device_id})["result"]["declined"]
    assert "error" in computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})


def test_an_unpair_on_the_computer_drops_the_accept_and_refuses_the_phones_next_dial(phone, computer):
    """MUTATION (``list_accepts``): answer a row whose device was unpaired and it is still listed."""

    device, answer = _grant(phone, computer)
    computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})
    assert computer.owner("runtime.gateway.reverse.lanes")["result"]["accepted"]
    revoke_device(computer.root, device.device_id)
    assert computer.owner("runtime.gateway.reverse.lanes")["result"]["accepted"] == []
    assert accepts.list_accepts(computer.root) == []
    # The phone's next dial is refused as unpaired, and the phone deletes its grant.
    dialed = phone.rpc("runtime.gateway.reverse.dial", _way(computer, device))
    assert "result" in dialed, dialed
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and grants.grant_for_install(_phone_root(), INSTALL):
        time.sleep(0.05)
    assert grants.grant_for_install(_phone_root(), INSTALL) is None


def test_the_computer_reads_the_phone_away_once_it_hangs_up(phone, computer):
    """MUTATION (``ReverseLanes.status``): skip the eviction and the phone still reads parked."""

    device, answer = _grant(phone, computer)
    assert "result" in phone.rpc("runtime.gateway.reverse.dial", _way(computer, device))
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and not computer.lanes.status()["parked"]:
        time.sleep(0.02)
    status = computer.lanes.status()
    assert [p["device_id"] for p in status["parked"]] == [device.device_id]
    assert device.device_id in status["seen"]
    assert phone.rpc("runtime.gateway.reverse.hangup", {"computer_install_id": INSTALL})["result"]["stopped"] == 1
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and computer.lanes.status()["parked"]:
        time.sleep(0.05)
    assert computer.lanes.status()["parked"] == []


def test_the_owner_unpairing_the_computer_on_the_phone_ends_the_grant(phone, computer):
    """Unpairing on the phone side ends both directions: Eternia's unpair calls revoke."""

    device, answer = _grant(phone, computer)
    assert grants.grant_for_install(_phone_root(), INSTALL) is not None
    phone.rpc("runtime.gateway.reverse.revoke", {"computer_install_id": INSTALL})
    assert grants.grant_for_install(_phone_root(), INSTALL) is None
    dialed = phone.rpc("runtime.gateway.reverse.dial", _way(computer, device))
    assert dialed["error"]["data"]["reason"] == "no_grant"
