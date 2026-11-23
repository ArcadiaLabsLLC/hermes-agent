"""The phone's grant to a paired computer: the switch, the offer, the accept.

Row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS`` (Eternia), plan
``PHONE_DRIVEN_BY_A_COMPUTER_2026-11-21`` §4 and §15, review w1118a.79. The PHONE is the real
``serve_loop`` over its pipe (as in ``test_reverse_lane``); the COMPUTER is its two real listeners
with a dispatcher that runs the real ``handle_request`` with each connection's own caller, so the
offer arrives as the paired device that sent it, over real TLS under a real pin. The one level is
``account`` (hermes row ``RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN``).

Killing mutations (each named at its line):

* ``reverse_lane.offer.grant_and_offer``: keep the grant when the offer did not land, and the
  unreachable-offer test finds a grant the computer never received;
* ``serve_rpc.reverse_lane._runtime_gateway_reverse_offer``: accept any caller, and the owner's
  own offer is held;
* ``reverse_lane.accepts.list_accepts``: answer a row whose device was unpaired, and the
  computer-unpair test still lists the phone as accepted;
* ``ReverseLanes.status``: skip the parked-lane eviction, and the hang-up test reads the phone
  still parked;
* ``serve_rpc.reverse_lane._runtime_gateway_reverse_revoke``: skip the withdraw (no way taken), and
  the switch-off test reads the computer's accept still there (red seen 2026-11-22);
* ``serve_rpc.reverse_lane._runtime_gateway_reverse_withdraw``: take the device id from the params
  when the caller is not a device, and the owner's withdraw forgets the phone's accept (red seen
  2026-11-22);
* ``call_authorization._computer_arm``: admit any grant word, and the retired-level test sees a
  computer stamped ``look`` answered a console verb;
* ``reverse_lane.accepts.list_accepts``: drop the level check, and the retired-level test still lists a
  stored ``look`` accept.
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


def _grant(phone, computer: _Computer, level: str = grants.GRANT_ACCOUNT):
    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level=level))
    return device, answer


def test_the_phone_grants_the_computer_accepts_and_the_phone_lists_the_record(phone, computer):
    device, answer = _grant(phone, computer)
    assert answer.get("result", {}).get("state") == "offered", answer
    # The minted token is never in the phone's own answer.
    assert "token" not in answer["result"]
    computer_id = answer["result"]["computer_id"]

    # The computer holds the offer as the device that sent it; its listing carries no token.
    offers = computer.owner("runtime.gateway.reverse.lanes")["result"]["offers"]
    assert [(o["device_id"], o["computer_id"], o["level"]) for o in offers] == \
        [(device.device_id, computer_id, "account")]
    assert "token" not in offers[0]

    # The computer's Eternia accepts (by itself: no press for a phone on its own account) and gets the token once.
    accepted = computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})["result"]
    assert accepted["computer_id"] == computer_id and accepted["level"] == "account"
    assert "client_scope" not in accepted
    token = accepted["token"]
    assert "error" in computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})
    status = computer.owner("runtime.gateway.reverse.lanes")["result"]
    assert status["offers"] == []
    assert [a["computer_id"] for a in status["accepted"]] == [computer_id]
    assert "token" not in status["accepted"][0]

    # The phone's engine lists the computer's record, bound to the pairing.
    listed = phone.rpc("runtime.gateway.reverse.lanes")["result"]["grants"]
    assert listed == [{"computer_install_id": INSTALL, "computer_id": computer_id, "level": "account",
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
    answer = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level="account"))
    assert answer["error"]["data"]["reason"] == "computer_unreachable", answer
    assert grants.grant_for_install(_phone_root(), INSTALL) is None


def test_a_wrong_pin_refuses_the_offer_and_leaves_no_grant(phone, computer):
    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant",
                       {**_way(computer, device, level="account"), "cert_fingerprint": "0" * 64})
    assert answer["error"]["data"]["reason"] == "certificate_rejected", answer
    assert grants.grant_for_install(_phone_root(), INSTALL) is None
    assert computer.owner("runtime.gateway.reverse.lanes")["result"]["offers"] == []


def test_only_a_paired_device_offers(computer):
    """MUTATION (``_runtime_gateway_reverse_offer``): accept any caller and the owner's offer is held."""

    offer = {"computer_id": "cmp-x", "token": "a" * 64, "level": "account", "phone_install_id": "phone-x"}
    frame = computer.owner("runtime.gateway.reverse.offer", offer)
    assert frame["error"]["data"]["reason"] == "not_a_device"
    assert computer.lanes.offers.pending() == []


@pytest.mark.parametrize("name", ["runtime.gateway.reverse.grant", "runtime.gateway.reverse.revoke",
                                  "runtime.gateway.reverse.accept", "runtime.gateway.reverse.decline"])
def test_the_grant_and_accept_verbs_answer_only_the_machine_owner(name):
    assert name in ca.LOCAL_CONSOLE_METHODS
    device = ca.RpcCaller(kind=ca.CALLER_DEVICE, device_id="d", device_tier=ca.TIER_CONSOLE,
                          device_kind=ca.DEVICE_KIND_DEVICE, transport="gateway")
    assert not ca.authorize_call(ca.TIER_CONSOLE, device, method=name).ok
    for grant in grants.GRANT_LEVELS:
        computer = ca.RpcCaller(kind=ca.CALLER_COMPUTER, computer_id="c", computer_grant=grant, transport="gateway")
        assert not ca.authorize_call(ca.TIER_CONSOLE, computer, method=name).ok


def test_the_computer_declines_and_the_offer_is_gone(phone, computer):
    device, answer = _grant(phone, computer)
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


# ── the account level (hermes row RT-PHONE-DRIVEN-A-COMPUTER-ON-THE-PHONES-OWN-ACCOUNT-IS-ANSWERED-LIKE-A-PAIRED-COMPUTER)


def _computer_caller(grant: str) -> ca.RpcCaller:
    return caller_for_connection(_LaneConn(grant))


class _LaneConn:
    def __init__(self, grant: str) -> None:
        self.transport, self.key, self.authenticated = "gateway", "conn-lane", True
        self.device_id = self.device_tier = self.peer_install_id = None
        self.computer_id, self.computer_grant = "cmp-1", grant


_CONSOLE_DEVICE = ca.RpcCaller(kind=ca.CALLER_DEVICE, device_id="d", device_tier=ca.TIER_CONSOLE,
                               device_kind=ca.DEVICE_KIND_DEVICE, transport="gateway")


def test_an_account_computer_is_answered_every_verb_a_console_device_is_and_no_local_console_verb():
    """Done-when: one test over the whole registry against the device arm's own answer.

    MUTATION (``call_authorization._computer_arm``): answer the account level from the chat
    allowlist, and the console verbs a console device is answered (``runtime.skills.catalog``,
    ``runtime.level.get``, ``runtime.provider.key.set`` …) come back refused here.
    """

    from agent_runtime.serve_rpc.registry import method_tiers

    account = _computer_caller(grants.GRANT_ACCOUNT)
    assert account.kind == ca.CALLER_COMPUTER and account.computer_grant == "account"
    tiers = method_tiers()
    assert len(tiers) > 100
    drift = [name for name, tier in tiers.items()
             if ca.authorize_call(tier, account, method=name).ok
             != ca.authorize_call(tier, _CONSOLE_DEVICE, method=name).ok]
    assert drift == []
    for name in sorted(ca.LOCAL_CONSOLE_METHODS):
        assert not ca.authorize_call(tiers.get(name, ca.TIER_CONSOLE), account, method=name).ok, name
    # What the chat grant never reached, the account level does: the owner's ruling.
    for name in ("runtime.skills.catalog", "runtime.level.get", "runtime.provider.key.set",
                 "runtime.operator.conversation.list"):
        if name in tiers:
            assert ca.authorize_call(tiers[name], account, method=name).ok, name


@pytest.mark.parametrize("retired", ["look", "chat", "console"])
def test_a_computer_stamped_with_any_word_but_account_is_refused_every_verb(retired):
    """Hermes row RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN: no level below
    account remains, so a computer caller carrying the retired ``look`` or ``chat`` (or any other word) is
    answered nothing, read verbs included: the arm fails closed.

    MUTATION (``call_authorization._computer_arm``): admit any grant word, and key set, Skills and the
    health read are answered here.
    """

    from agent_runtime.serve_rpc.registry import method_tiers

    caller = ca.RpcCaller(kind=ca.CALLER_COMPUTER, computer_id="cmp-1", computer_grant=retired, transport="gateway")
    tiers = method_tiers()
    answered = {name for name, tier in tiers.items() if ca.authorize_call(tier, caller, method=name).ok}
    assert answered == set(), (retired, sorted(answered)[:10])
    refusal = ca.authorize_call(ca.TIER_READ, caller, method="runtime.health")
    assert refusal.reason == ca.REASON_SCOPE_DENIED and retired in refusal.detail


def test_a_stored_look_or_chat_accept_is_dropped_on_read(computer):
    """A computer's accept row an older build stored at Look or Run chats is dropped on the next read, with
    no store migration; an account accept beside it stays.

    MUTATION (``accepts.list_accepts``): drop the level check, and the look and chat rows are listed.
    """

    from agent_runtime.store_file_io import write_secure_json

    phones = [computer.pair_phone() for _ in range(3)]
    rows = {device.device_id: {"computer_id": f"cmp-{level}", "level": level, "phone_install_id": "phone-x",
                               "accepted_at": "2026-11-22T00:00:00Z"}
            for device, level in zip(phones, ("look", "chat", "account"))}
    path = computer.root / "gateway" / accepts.REVERSE_ACCEPTS_FILENAME
    write_secure_json(path, {"contract": 1, "accepts": rows})
    assert [(a.device_id, a.level) for a in accepts.list_accepts(computer.root)] == [(phones[2].device_id, "account")]
    assert list(json.loads(path.read_text(encoding="utf-8"))["accepts"]) == [phones[2].device_id]
    assert [a["level"] for a in computer.owner("runtime.gateway.reverse.lanes")["result"]["accepted"]] == ["account"]


def test_a_regrant_replaces_the_grant_and_offers_afresh(phone, computer):
    """One level, so nothing changes in place: the phone's switch on again mints a new credential (the old
    one stops verifying at once) and offers it, and the computer's Eternia takes the new offer."""

    from agent_runtime.serve_gateway_auth.proof import reverse_lane_proof

    device, first = _grant(phone, computer)
    old_id = first["result"]["computer_id"]
    old_token = computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})["result"]["token"]
    again = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level="account"))["result"]
    assert again["state"] == "offered" and again["computer_id"] != old_id, again
    proof = reverse_lane_proof(old_token, "n" * 32, lane_id="a" * 32, device_id=old_id)
    assert grants.verify_lane_proof(_phone_root(), old_id, proof, "n" * 32, lane_id="a" * 32) is None
    accepted = computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})["result"]
    assert accepted["computer_id"] == again["computer_id"]
    assert [a.computer_id for a in accepts.list_accepts(computer.root)] == [again["computer_id"]]


def test_the_device_arm_and_the_account_level_share_one_predicate():
    assert ca.paired_device_answers(ca.TIER_CONSOLE, "runtime.provider.key.set", ca.TIER_CONSOLE)
    assert ca.paired_device_answers(ca.TIER_READ, "runtime.health", ca.TIER_READ)
    assert not ca.paired_device_answers(ca.TIER_READ, "runtime.provider.key.set", ca.TIER_CONSOLE)
    assert not ca.paired_device_answers(ca.TIER_CONSOLE, "runtime.gateway.reverse.grant", ca.TIER_CONSOLE)
    assert not ca.paired_device_answers("admin", "runtime.health", ca.TIER_READ)
    assert tuple(grants.GRANT_LEVELS) == ca.COMPUTER_GRANTS


def test_a_grant_naming_an_unknown_level_is_refused_and_leaves_no_grant(phone, computer):
    for level in ("look", "chat", "console", "admin", "", None):
        device = computer.pair_phone()
        answer = phone.rpc("runtime.gateway.reverse.grant", _way(computer, device, level=level))
        assert "result" not in answer and "level must be one of account" in answer["error"]["message"], answer
        assert grants.grant_for_install(_phone_root(), INSTALL) is None


def test_the_phone_grants_account_and_the_computer_accepts_it(phone, computer):
    device, answer = _grant(phone, computer, grants.GRANT_ACCOUNT)
    assert answer.get("result", {}).get("level") == "account", answer
    accepted = computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})["result"]
    assert accepted["level"] == "account"
    listed = phone.rpc("runtime.gateway.reverse.lanes")["result"]["grants"]
    assert [g["level"] for g in listed] == ["account"]
    # A revoke drops it like any grant.
    assert phone.rpc("runtime.gateway.reverse.revoke", {"computer_install_id": INSTALL})["result"]["revoked"] == 1
    assert phone.rpc("runtime.gateway.reverse.lanes")["result"]["grants"] == []


# ── the switch off, told to the computer (hermes row RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT)


def _accepted(phone, computer: _Computer, level: str = grants.GRANT_ACCOUNT) -> DeviceCredential:
    device, answer = _grant(phone, computer, level)
    assert "result" in answer, answer
    assert "result" in computer.owner("runtime.gateway.reverse.accept", {"device_id": device.device_id})
    assert [a["device_id"] for a in computer.owner("runtime.gateway.reverse.lanes")["result"]["accepted"]] == \
        [device.device_id]
    return device


def test_the_phones_switch_off_tells_the_computer_to_forget_its_accept(phone, computer):
    """Seen live 2026-11-22 (w1122b-emu): after the phone's Off the computer still read "You can use this
    phone's agents". MUTATION (``_runtime_gateway_reverse_revoke``): skip the withdraw and the accept stays."""

    device = _accepted(phone, computer)
    answer = phone.rpc("runtime.gateway.reverse.revoke", {"computer_install_id": INSTALL})["result"]
    assert answer == {"revoked": 1, "withdrawn": True}, answer
    assert computer.owner("runtime.gateway.reverse.lanes")["result"]["accepted"] == []
    assert accepts.list_accepts(computer.root) == []
    # The way to the computer went with the grant: a second Off has nothing to tell it with.
    again = phone.rpc("runtime.gateway.reverse.revoke", {"computer_install_id": INSTALL})["result"]
    assert again == {"revoked": 0, "withdrawn": False}


def test_only_the_paired_device_itself_withdraws_and_only_its_own_accept(phone, computer):
    """MUTATION (``_runtime_gateway_reverse_withdraw``): accept any caller and the owner's own withdraw
    forgets the phone's accept. The device id is the transport's: another paired device that withdraws
    removes nothing of this phone's."""

    from agent_runtime.reverse_lane.offer import withdraw_accept

    device = _accepted(phone, computer)
    owner = computer.owner("runtime.gateway.reverse.withdraw", {"device_id": device.device_id})
    assert owner["error"]["data"]["reason"] == "not_a_device", owner
    other = computer.pair_phone()
    sent = withdraw_accept(host="127.0.0.1", port=computer.gateway_port, cert_fingerprint=computer.fingerprint,
                           device_id=other.device_id, token=other.token)
    assert sent == {"ok": True}, sent
    assert [a.device_id for a in accepts.list_accepts(computer.root)] == [device.device_id]
    # A wrong credential never reaches the verb at all.
    refused = withdraw_accept(host="127.0.0.1", port=computer.gateway_port, cert_fingerprint=computer.fingerprint,
                              device_id=device.device_id, token="0" * 64)
    assert refused == {"ok": False, "reason": "unpaired"}, refused
    assert [a.device_id for a in accepts.list_accepts(computer.root)] == [device.device_id]


def test_the_withdraw_is_a_device_verb_never_a_local_console_or_computer_one():
    assert "runtime.gateway.reverse.withdraw" not in ca.LOCAL_CONSOLE_METHODS
    computer = ca.RpcCaller(kind=ca.CALLER_COMPUTER, computer_id="c", computer_grant=grants.GRANT_ACCOUNT,
                            transport="gateway")
    frame = handle_request({"jsonrpc": "2.0", "id": "w", "method": "runtime.gateway.reverse.withdraw", "params": {}},
                           RpcContext(caller=computer))
    assert frame["error"]["data"]["reason"] == "not_a_device", frame
