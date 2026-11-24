"""A connection between two of your devices is dropped first when the other side is not the machine it
was paired with.

Hermes row ``RT-ACCOUNT-ONLY-A-CONNECTION-FROM-ANOTHER-MACHINE-THAN-THE-ONE-YOUR-DEVICE-PAIRED-WITH-IS-DROPPED-FIRST``
(owner 2026-11-23: "there are namespaces so it should use the namespaces to confirm the connection is going
to the right device" / "right it should be both" / "starting with machine id"). Real sockets, real TLS, a
real pin and real HMAC proofs: the gateway lane is the real ``serve_loop`` (``test_serve_gateway_lane``'s
harness), the reverse lane the real phone serve and computer listeners (``test_reverse_lane``'s), and the
route owner is read off a real ``ServeSocketServer``. Each test names its killing mutation; the reds are
recorded in the landing commit.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime.hello_address import (
    HELLO_MACHINE_MISMATCH,
    HELLO_NAMESPACE_MISMATCH,
    hello_fields,
    install_address,
)
from agent_runtime.reverse_lane import grants
from agent_runtime.serve_gateway_auth import device_proof, device_store_path
from agent_runtime.serve_socket import ServeSocketClient
from agent_runtime.serve_socket.hello import HelloAuthOutcome
from agent_runtime.serve_socket.server import ServeSocketServer
from tests.agent_runtime.test_reverse_lane import (  # noqa: F401
    _phone_root,
    computer,
    phone,
)
from tests.agent_runtime.test_serve_gateway_lane import (  # noqa: F401
    WAIT,
    _store_root,
    gateway_on,
    pair_device,
    running_serve,
)

OTHER_MACHINE = "mach_" + "0" * 32


def _raw_device_hello(handle, credential, **fields) -> dict:
    """A device hello this test writes field by field, with a RIGHT proof."""

    connection = ServeSocketClient("127.0.0.1", handle.gateway_port, timeout_seconds=WAIT, tls=True,
                                   cert_fingerprint=handle.fingerprint)
    connection.connect()
    try:
        nonce = connection._challenge_nonce(3)
        connection.send({"op": "hello", "client": "phone", "device_id": credential.device_id,
                         "proof": device_proof(credential.token, nonce, port=handle.gateway_port,
                                               device_id=credential.device_id), **fields})
        return connection.read_frame()
    finally:
        connection.close()


def _rejected_detail(handle, timeout: float = WAIT) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for row in handle.sink.frames():
            line = row.get("line", "") if row.get("event") == "stderr" else ""
            if line.startswith("{"):
                record = json.loads(line)
                if record.get("event") == "serve_socket_connection_rejected" and record.get("detail"):
                    return record["detail"]
        time.sleep(0.02)
    return None


@pytest.fixture
def proof_spy(monkeypatch):
    """Counts every device proof check the gateway authenticator makes."""

    import agent_runtime.serve_gateway_auth as auth

    calls: list[object] = []
    real = auth.verify_device_proof

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(auth, "verify_device_proof", spy)
    return calls


# ── the server: machine, then namespace, then the proof ─────────────────────


def test_a_device_hello_from_another_machine_is_refused_before_its_proof(gateway_on, proof_spy):
    """MUTATION: run the address check after ``verify_device_proof`` in
    ``serve_gateway_credentials._verify_device_proof`` -> the spy is called, red."""

    credential = pair_device()
    with running_serve() as handle:
        reply = _raw_device_hello(handle, credential, machine_id=OTHER_MACHINE,
                                  namespace=hello_fields()["namespace"])
        detail = _rejected_detail(handle)
        checked_before = list(proof_spy)
        # The right machine, through the same door, still connects: the row is the only difference.
        good = _raw_device_hello(handle, credential, **hello_fields())

    assert reply == {"event": "hello_rejected", "reason": "bad_proof"}, reply
    assert detail == HELLO_MACHINE_MISMATCH
    assert checked_before == []
    assert good["event"] == "hello_ok", good
    assert len(proof_spy) == 1


def test_a_device_hello_from_another_namespace_is_refused(gateway_on, proof_spy):
    """MUTATION: drop the namespace compare in ``hello_address.hello_address_refusal`` -> admitted, red."""

    credential = pair_device()
    with running_serve() as handle:
        reply = _raw_device_hello(handle, credential, machine_id=hello_fields()["machine_id"],
                                  namespace="acct-ffffffffffffffff")
        detail = _rejected_detail(handle)

    assert reply == {"event": "hello_rejected", "reason": "bad_proof"}, reply
    assert detail == HELLO_NAMESPACE_MISMATCH
    assert proof_spy == []


def test_a_row_with_no_machine_id_is_refused(gateway_on, proof_spy):
    """No legacy: a device row minted before the binding stops working and the device re-pairs.

    MUTATION: read an absent row machine id as a match in ``hello_address_refusal`` -> admitted, red."""

    credential = pair_device()
    path = device_store_path(_store_root())
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["devices"][credential.device_id].pop("machine_id")
    path.write_text(json.dumps(stored), encoding="utf-8")
    with running_serve() as handle:
        reply = _raw_device_hello(handle, credential, **hello_fields())

    assert reply == {"event": "hello_rejected", "reason": "bad_proof"}, reply
    assert proof_spy == []


def test_a_device_hello_naming_no_machine_is_refused(gateway_on):
    credential = pair_device()
    with running_serve() as handle:
        reply = _raw_device_hello(handle, credential, namespace=hello_fields()["namespace"])
    assert reply == {"event": "hello_rejected", "reason": "bad_proof"}, reply


def test_hello_ok_names_the_machine_and_namespace_it_answers_from(gateway_on):
    credential = pair_device()
    with running_serve() as handle:
        reply = _raw_device_hello(handle, credential, **hello_fields())
    assert reply["event"] == "hello_ok", reply
    assert {key: reply["install"][key] for key in ("machine_id", "namespace")} == install_address()
    assert reply["install"]["machine_id"].startswith("mach_")


# ── the route owner: the row's machine, never the frame's ───────────────────


class _Server:
    """A real listener whose dispatcher records each caller's route owner."""

    def __init__(self, root: Path, *, authenticator=None) -> None:
        self.owners: list[str] = []
        self.seen = threading.Event()

        def dispatch(line: str, connection) -> None:
            self.owners.append(ca.caller_for_connection(connection).route_owner())
            self.seen.set()

        self.server = ServeSocketServer(root, boot_id="b", dispatch_line=dispatch,
                                        hello_payload=lambda message, c: {"event": "hello_ok"},
                                        token_provider=lambda: "root-token-" + "a" * 40,
                                        authenticator=authenticator, host="127.0.0.1",
                                        reject_penalty_seconds=0.0)
        self.port = self.server.bind()
        self.server.start_accepting()

    def first_owner(self) -> str:
        assert self.seen.wait(WAIT)
        return self.owners[0]


def test_route_owner_takes_the_machine_from_the_row_not_the_hello_frame(tmp_path):
    """MUTATION: stamp ``message.get("machine_id")`` instead of ``outcome.machine_id`` in
    ``serve_socket.handshake.handshake`` -> the frame's machine is the route's, red."""

    def authenticator(message, nonce, port):
        return HelloAuthOutcome(ok=True, peer_install_id="inst_b", machine_id="mach_row")

    listener = _Server(tmp_path / "root", authenticator=authenticator)
    try:
        with ServeSocketClient("127.0.0.1", listener.port, timeout_seconds=WAIT) as client:
            client._challenge(3)
            client.send({"op": "hello", "client": "far", "machine_id": "mach_frame",
                         "namespace": "acct-ffffffffffffffff", "proof": "x"})
            assert client.read_frame()["event"] == "hello_ok"
            client.send({"jsonrpc": "2.0", "id": 1, "method": "runtime.health"})
            owner = listener.first_owner()
    finally:
        listener.server.close()

    namespace = install_address()["namespace"]
    assert owner.startswith(f"machine:mach_row/namespace:{namespace}/peer:inst_b/"), owner
    assert "frame" not in owner and "ffff" not in owner


def test_the_local_console_routes_under_this_machines_own_id(tmp_path):
    """Owner 2026-11-24: "Yes, use it" — the holder of this install's token is this computer's own Eternia.

    MUTATION: stamp ``None`` in the token arm of ``serve_socket.handshake.authenticate_hello`` -> the
    route reads ``machine:unproven``, red."""

    listener = _Server(tmp_path / "root")
    try:
        with ServeSocketClient("127.0.0.1", listener.port, timeout_seconds=WAIT) as client:
            assert client.hello(token="root-token-" + "a" * 40, client="eternia")["event"] == "hello_ok"
            client.send({"jsonrpc": "2.0", "id": 1, "method": "runtime.health"})
            owner = listener.first_owner()
    finally:
        listener.server.close()

    mine = install_address()
    assert owner.startswith(f"machine:{mine['machine_id']}/namespace:{mine['namespace']}/local_console/"), owner


# ── the dialers: the far answer must name the machine the caller handed them ─


def test_the_dialer_stops_when_the_computer_answers_from_another_machine(phone, computer):
    """MUTATION: drop the ``answer_address_refusal`` check in ``ReverseDialer._round`` -> the phone
    waits parked on a computer whose machine is not its grant's, red."""

    device = computer.pair_phone()
    grants.grant_computer(_phone_root(), computer_install_id="computer-install", pairing_device_id=device.device_id,
                          computer_machine_id=OTHER_MACHINE)
    answer = phone.rpc("runtime.gateway.reverse.dial", {
        "computer_install_id": "computer-install", "host": "127.0.0.1", "port": computer.gateway_port,
        "cert_fingerprint": computer.fingerprint, "device_id": device.device_id, "token": device.token})
    assert "result" in answer, answer
    deadline = time.monotonic() + WAIT
    status = {}
    while time.monotonic() < deadline:
        status = phone.rpc("runtime.gateway.reverse.lanes")["result"]
        if not status["dialing"]:
            break
        time.sleep(0.05)
    assert status["dialing"] == [], status
    assert [d["device_id"] for d in computer.lanes.status()["parked"]] == []


def test_a_lane_hello_from_another_machine_than_the_grants_is_refused(phone, computer):
    """The phone's lane admitter checks the grant's machine before the lane proof.

    MUTATION: drop the address check in ``reverse_lane.lanes.lane_authenticator`` -> admitted, red."""

    from agent_runtime.reverse_lane.lanes import lane_authenticator
    from agent_runtime.serve_gateway_auth.proof import reverse_lane_proof

    device = computer.pair_phone()
    credential = grants.grant_computer(_phone_root(), computer_install_id="computer-install",
                                       pairing_device_id=device.device_id, computer_machine_id=OTHER_MACHINE)
    lane_id, nonce = "a" * 32, "b" * 64
    hello = {"op": "hello", "device_id": credential.computer_id, **hello_fields(),
             "proof": reverse_lane_proof(credential.token, nonce, lane_id=lane_id, device_id=credential.computer_id)}
    outcome = lane_authenticator(_phone_root())(hello, nonce, lane_id)
    assert (outcome.ok, outcome.refusal_detail) == (False, HELLO_MACHINE_MISMATCH)
    right = {**hello, "machine_id": OTHER_MACHINE}
    admitted = lane_authenticator(_phone_root())(right, nonce, lane_id)
    assert (admitted.ok, admitted.machine_id) == (True, OTHER_MACHINE)


def test_the_offer_sends_nothing_to_a_computer_on_another_machine(phone, computer):
    """MUTATION: drop the ``answer_address_refusal`` arm in ``reverse_lane.offer._one_shot`` -> the
    offer is held on the computer, red."""

    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant", {
        "computer_install_id": "computer-install", "host": "127.0.0.1", "port": computer.gateway_port,
        "cert_fingerprint": computer.fingerprint, "device_id": device.device_id, "token": device.token,
        "machine_id": OTHER_MACHINE, "level": grants.GRANT_ACCOUNT})
    assert answer["error"]["data"]["reason"] == HELLO_MACHINE_MISMATCH, answer
    assert computer.lanes.offers.pending() == []
    assert grants.list_grants(_phone_root()) == []


def test_a_grant_naming_no_machine_is_refused(phone, computer):
    device = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.grant", {
        "computer_install_id": "computer-install", "host": "127.0.0.1", "port": computer.gateway_port,
        "cert_fingerprint": computer.fingerprint, "device_id": device.device_id, "token": device.token,
        "level": grants.GRANT_ACCOUNT})
    assert "error" in answer and grants.list_grants(_phone_root()) == [], answer


def test_dial_peer_sends_nothing_to_an_install_that_answers_from_another_machine(gateway_on, monkeypatch):
    """The far install accepts the peer hello, but its ``hello_ok`` names another machine than the row's.

    MUTATION: drop the ``answer_address_refusal`` check in ``gateway_peers.dial.Dial.attempt`` ->
    the dial answers a connection, red."""

    import agent_runtime.hello_address as hello_address
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.gateway_peers import dial_peer, record_peer
    from tests.agent_runtime.test_serve_gateway_peer_lane import pair_peer

    mine = install_address()
    monkeypatch.setattr(hello_address, "install_address",
                        lambda: {"machine_id": OTHER_MACHINE, "namespace": mine["namespace"]})
    identity = ensure_install_identity(_store_root())
    with running_serve() as handle:
        credential = pair_peer(peer_install_id=identity.install_id)
        record_peer(_store_root(), peer_install_id=identity.install_id, secret=credential.secret,
                    endpoints=[{"host": "127.0.0.1", "port": handle.gateway_port}],
                    cert_fingerprint=handle.fingerprint, machine_id=mine["machine_id"])
        with pytest.raises(ConnectionError, match=HELLO_MACHINE_MISMATCH):
            dial_peer(_store_root(), identity.install_id)
