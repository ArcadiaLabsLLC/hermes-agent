"""While Eternia is in front on your phone, your computer can open the call to it too.

Row ``RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-ETERNIA-IS-IN-FRONT``. The phone
listens (``runtime.gateway.call.listen``) and admits ONE hello: a computer holding a grant this phone minted,
on the grant's machine, naming ``pair_call``. Real sockets, real TLS, a real pin, real HMAC proofs throughout:
the phone is the real ``serve_loop`` (its own dispatcher, call admitter and lanes) or an ``_Engine`` on its
own store root; the computer is an ``_Engine`` with its real gateway, loopback and calls.

Killing mutations (each named at its line, each seen red 2026-11-24):

* ``grant_listener_authenticator``: answer through the desktop gateway's table, and a pairing code is admitted;
* ``grant_listener_authenticator``: drop the grant arm (refuse every hello), and the computer is refused;
* ``grant_listener_authenticator``: read the proof before the address, and the other-machine test sees it read;
* ``PairCalls.accept_granted``: drop the install test, and an offer naming another install becomes a call;
* ``ReverseLanes._grants_revoked``: drop ``calls.drop_granted``, and the call outlives its grant.
"""

from __future__ import annotations

import pytest

from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.hello_address import HELLO_MACHINE_MISMATCH, hello_fields, install_address
from agent_runtime.gateway_peers import mint_peer_code
from agent_runtime.pair_call import dialer as dialer_module
from agent_runtime.pair_call.calls import CallWay
from agent_runtime.pair_call.listener import grant_listener_authenticator
from agent_runtime.reverse_lane import grants
from agent_runtime.serve_gateway_auth import DeviceCredential, mint_pairing_code, redeem_pairing_code
from agent_runtime.serve_gateway_auth.proof import device_proof, grant_dial_proof
from agent_runtime.serve_socket import ServeSocketClient

from tests.agent_runtime.test_pair_call import ROOT_TOKEN, WAIT, _Engine, _rpc, _until
from tests.agent_runtime.test_reverse_lane import _phone_root, phone  # noqa: F401 - the fixture

LOOPBACK = "127.0.0.1"


@pytest.fixture(autouse=True)
def _fast_redial(monkeypatch):
    monkeypatch.setattr(dialer_module, "_BACKOFF_FIRST", 0.05)
    monkeypatch.setattr(dialer_module, "_BACKOFF_MAX", 0.2)


def _grant(phone_root, computer: _Engine, *, machine_id: str | None = None) -> grants.ReverseGrantCredential:
    """The phone grants *computer* (its Eternia's offer and accept are the reverse lane's, not this row's)."""
    return grants.grant_computer(phone_root, computer_install_id=computer.install, pairing_device_id="dev-phone",
                                 computer_machine_id=machine_id or install_address()["machine_id"])


def _way(computer_id: str, token: str, *, install: str, port: int, fingerprint: str) -> CallWay:
    return CallWay(host=LOOPBACK, port=port, cert_fingerprint=fingerprint, machine_id=install_address()["machine_id"],
                   install_id=install, device_id=computer_id, token=token, credential="grant")


@pytest.fixture
def door(tmp_path):
    """A phone engine listening, and a computer engine; the phone's listener charges no reject penalty."""
    phone_engine, computer = _Engine(tmp_path / "phone-root", "phone"), _Engine(tmp_path / "computer-root", "computer")
    phone_engine.calls._listener_options = {"server_options": {"reject_penalty_seconds": 0.0}}
    try:
        block = phone_engine.calls.listen(host=LOOPBACK)
        assert block["outcome"] == "listening", block
        yield phone_engine, computer, block
    finally:
        phone_engine.close()
        computer.close()


def _hello(block: dict, frame: dict) -> dict | None:
    """One raw hello on the phone's listener, over its pinned TLS: the frame's own fields, after the challenge."""
    client = ServeSocketClient(LOOPBACK, block["port"], timeout_seconds=WAIT, tls=True,
                               cert_fingerprint=block["cert_fingerprint"])
    client.connect()
    try:
        nonce = client._challenge_nonce(None)
        client.send({"op": "hello", "client": "probe", **hello_fields(), **frame(nonce, block["port"])})
        return client.read_frame()
    finally:
        client.close()


# ── the one way in ─────────────────────────────────────────────────────────────────────────────────


def test_a_computer_holding_this_phones_grant_opens_the_call_and_uses_the_phones_engine(phone, tmp_path):
    """Through the real phone serve: Eternia asks it to listen, the computer dials it with the grant, the call
    is up on both sides, and the computer's Eternia is answered by the phone's engine on a lane of it.
    Killing mutation: ``grant_listener_authenticator`` refuses every hello (drop the grant arm) — no call."""
    computer = _Engine(tmp_path / "computer-root", "computer")
    try:
        listening = phone.rpc("runtime.gateway.call.listen", {"host": LOOPBACK})["result"]
        assert listening["outcome"] == "listening" and listening["port"] > 0, listening
        assert phone.rpc("runtime.gateway.call.calls")["result"]["listening"] == listening
        credential = _grant(_phone_root(), computer)
        phone_install = ensure_install_identity(_phone_root()).install_id
        computer.calls.dial(_way(credential.computer_id, credential.token, install=phone_install,
                                 port=listening["port"], fingerprint=listening["cert_fingerprint"]))
        call = _until(lambda: computer.calls.registry.get(phone_install), what="the computer's call")
        assert call.outbound and call.far.install_id == phone_install
        calls = _until(lambda: phone.rpc("runtime.gateway.call.calls")["result"]["calls"], what="the phone's call")
        assert [(c["call"], c["far"]["install_id"], c["outbound"]) for c in calls] == [
            (call.call_id, computer.install, False)]
        eternia = ServeSocketClient(LOOPBACK, computer.loopback_port, timeout_seconds=WAIT)
        eternia.connect()
        try:
            attached = eternia.hello(token=ROOT_TOKEN, client="eternia-computer", call_attach=phone_install)
            assert attached["event"] == "call_attached" and attached["call"] == call.call_id, attached
            hello_ok = eternia.lane_hello(computer_id=credential.computer_id, token=credential.token,
                                          lane_id=attached["lane_id"], client="eternia-computer")
            assert hello_ok is not None and hello_ok.get("event") == "hello_ok", hello_ok
            assert "result" in _rpc(eternia, "runtime.health")
        finally:
            eternia.close()
        assert phone.rpc("runtime.gateway.call.unlisten")["result"] == {"closed": True}
        assert phone.rpc("runtime.gateway.call.calls")["result"]["listening"] is None
        # Closing the door leaves the call it let in up (Eternia hangs it up with ``hangup``).
        assert computer.calls.registry.get(phone_install) is call and call.is_open
    finally:
        phone.rpc("runtime.gateway.call.hangup")
        phone.rpc("runtime.gateway.call.unlisten")
        computer.close()


def test_a_pairing_code_a_peer_code_a_device_credential_or_no_credential_gets_the_one_refusal(door):
    """Nothing the desktop gateway answers is answered here, and the codes stay unspent. Killing mutation:
    answer through ``serve_gateway_credentials.authenticate_hello``, and the pairing code is admitted."""
    phone_engine, computer, block = door
    pairing = mint_pairing_code(phone_engine.root, name="stranger")
    peer = mint_peer_code(phone_engine.root)
    device_code = mint_pairing_code(phone_engine.root, name="device")
    device = redeem_pairing_code(phone_engine.root, device_code.code, **hello_fields())
    assert isinstance(device, DeviceCredential)
    offer = {"pair_call": {"call": "c" * 32, "install": computer.install}}
    frames = {
        "pairing code": lambda nonce, port: {"pairing_code": pairing.code, **offer},
        "peer code": lambda nonce, port: {"peer_code": peer.code, "peer_install_id": computer.install, **offer},
        "device credential": lambda nonce, port: {
            "device_id": device.device_id, **offer,
            "proof": device_proof(device.token, nonce, port=port, device_id=device.device_id)},
        "device credential as a grant proof": lambda nonce, port: {
            "device_id": device.device_id, **offer,
            "proof": grant_dial_proof(device.token, nonce, port=port, computer_id=device.device_id)},
        "no credential": lambda nonce, port: dict(offer),
    }
    for what, frame in frames.items():
        assert _hello(block, frame) == {"event": "hello_rejected", "reason": "bad_proof"}, what
    assert isinstance(redeem_pairing_code(phone_engine.root, pairing.code, **hello_fields()), DeviceCredential)
    assert phone_engine.calls.registry.calls() == []


def test_a_granted_computers_hello_without_the_call_or_with_a_lane_is_refused(door):
    """The grant opens the call and nothing else: a hello naming no ``pair_call``, or a reverse lane beside it."""
    phone_engine, computer, block = door
    credential = _grant(phone_engine.root, computer)

    def granted(**extra):
        return lambda nonce, port: {"device_id": credential.computer_id, **extra,
                                    "proof": grant_dial_proof(credential.token, nonce, port=port,
                                                              computer_id=credential.computer_id)}

    offer = {"call": "d" * 32, "install": computer.install}
    assert _hello(block, granted())["reason"] == "bad_proof"
    assert _hello(block, granted(pair_call=offer, reverse_lane="e" * 32))["reason"] == "bad_proof"
    assert _hello(block, granted(pair_call=offer, call_attach=computer.install))["reason"] == "bad_proof"
    assert phone_engine.calls.registry.calls() == []


def test_a_hello_from_another_machine_is_refused_before_the_grants_proof_is_read(tmp_path, monkeypatch):
    """Address order: the grant's machine first. Killing mutation: verify the proof before the address."""
    computer = _Engine(tmp_path / "computer-root", "computer")
    try:
        root = tmp_path / "phone-root"
        credential = _grant(root, computer, machine_id="mach_" + "0" * 32)
        read: list[str] = []
        real = grants.verify_dial_proof
        monkeypatch.setattr(grants, "verify_dial_proof", lambda *a, **k: read.append("proof") or real(*a, **k))
        nonce = "n" * 32
        outcome = grant_listener_authenticator(root)(
            {"device_id": credential.computer_id, **hello_fields(), "pair_call": {"call": "c" * 32},
             "proof": grant_dial_proof(credential.token, nonce, port=4242, computer_id=credential.computer_id)},
            nonce, 4242)
        assert not outcome.ok and outcome.refusal_detail == HELLO_MACHINE_MISMATCH and read == []
    finally:
        computer.close()


def test_an_offer_naming_another_install_than_the_grants_is_refused(door):
    """The grant names the computer's install; a call offered under another is refused. Killing mutation:
    drop the install test in ``PairCalls.accept_granted``."""
    phone_engine, computer, block = door
    credential = _grant(phone_engine.root, computer)
    client = ServeSocketClient(LOOPBACK, block["port"], timeout_seconds=WAIT, tls=True,
                               cert_fingerprint=block["cert_fingerprint"])
    client.connect()
    try:
        reply = client.grant_hello(computer_id=credential.computer_id, token=credential.token, client="probe",
                                   pair_call={"call": "f" * 32, "install": "inst-someone-else"})
    finally:
        client.close()
    assert reply == {"event": "hello_rejected", "reason": "reverse_lane_refused"}, reply
    assert phone_engine.calls.registry.calls() == []


def test_revoking_the_grant_ends_the_call_the_computer_opened(door):
    """The switch off on the phone: the computer's call goes at once. Killing mutation: drop
    ``self.calls.drop_granted(gone)`` in ``ReverseLanes._grants_revoked``."""
    phone_engine, computer, block = door
    credential = _grant(phone_engine.root, computer)
    computer.calls.dial(_way(credential.computer_id, credential.token, install=phone_engine.install,
                             port=block["port"], fingerprint=block["cert_fingerprint"]))
    call = _until(lambda: phone_engine.calls.registry.get(computer.install), what="the phone's call")
    assert call.far_computer_id == credential.computer_id and not call.outbound
    assert grants.revoke_grant(phone_engine.root, credential.computer_id)
    _until(lambda: not call.is_open, what="the call to close")
