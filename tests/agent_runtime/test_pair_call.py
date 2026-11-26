"""Any two of your devices keep one call between their engines, whichever opens it first.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST``. Two
engines, each on its own store root with its real gateway listener (TLS, the device store, the hello
hook) and its real lane admitter (``call_lane_authenticator``), each paired as a device on the other.
Real sockets, real TLS, a real pin, real HMAC proofs throughout; only the dispatcher behind each lane
is the test's, so a request's answer names the engine that applied it.

Killing mutations (each named at its line):

* ``registry.kept_call``: keep the later call; compare the ids in opposite order (``max``);
* ``PairCalls.accept``: give the accepted call no lane admitter (``on_lane_open=None``), and the
  dialled side's requests are never answered on the shared call;
* ``envelope.address_refusal``: check the namespace before the machine;
* ``PairCall._answer_for``: match an answer by request id alone;
* ``CallDialer._run``: the side that accepted a dropped call does not redial;
* ``call_lane_authenticator``: drop the grant arm, and the computer's Eternia is refused on the
  phone's lane.

The phone's call door (hermes row
``RT-ACCOUNT-ONLY-YOUR-PHONES-ENGINE-OPENS-A-PRIVATE-DOOR-IN-THE-APP-SO-ETERNIA-JOINS-ITS-CALLS``, owner
2026-11-26 "Option 2, private door"): the phone is the REAL embedded serve (``EmbeddedShell``), and its
Eternia is a client on the socket FILE that serve opens, over real AF_UNIX sockets:

* ``BootPhases._boot_socket_lane``: skip ``_boot_call_door`` (the embedded serve's door unopened, its
  ``socket`` block ``disabled``), and the phone's Eternia cannot reach its computer;
* ``BootPhases._open_call_door``: drop ``path`` from the ``socket`` block, and the greeting no longer
  names the door;
* ``BootPhases._open_call_door``: pass an authenticator that admits any hello, and a hello without the
  root's proof is admitted;
* ``BootPhases._open_call_door``: dispatch through ``_handle_socket_line``, and an ordinary method line
  on the door is answered.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.gateway_tls import ensure_certificate, server_ssl_context
from agent_runtime.hello_address import hello_fields, install_address
from agent_runtime.pair_call import dialer as dialer_module
from agent_runtime.pair_call.call import PairCall
from agent_runtime.pair_call.calls import CallWay, call_lane_authenticator, lane_device_hello
from agent_runtime.pair_call.envelope import MISMATCH_INSTALL, MISMATCH_MACHINE, MISMATCH_NAMESPACE, wrap
from agent_runtime.reverse_lane.lanes import ReverseLanes, handoff
from agent_runtime.serve_gateway_auth import DeviceCredential, PairingCode, mint_pairing_code, redeem_pairing_code
from agent_runtime.reverse_lane import grants
from agent_runtime.serve_socket import ServeSocketClient
from agent_runtime.serve_socket.admit import ConnectionAdmitter
from agent_runtime.serve_socket.server import ServeSocketServer
from hermes_cli.harness_parts.serve import gateway_listener

from tests.agent_runtime.test_reverse_lane import _Phone, _Pipe, _Sink, _phone_root, _rpc, phone

WAIT = 20.0
ROOT_TOKEN = "computer-root-token-" + "b" * 40


def _until(predicate, timeout: float = WAIT, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


class _Engine:
    """One device's engine: its gateway listener, its calls and a dispatcher that names it."""

    def __init__(self, root: Path, name: str) -> None:
        self.root, self.name = root, name
        certificate = ensure_certificate(root)
        assert certificate.ok
        self.fingerprint = certificate.fingerprint
        self.install = ensure_install_identity(root).install_id
        self.events: list[dict] = []
        self.served: list[tuple[str, str | None]] = []
        self.release = threading.Event()

        def dispatch(line: str, connection) -> None:
            message = json.loads(line)
            rid, method = message.get("id"), message.get("method")
            self.served.append((rid, method))
            if method == "test.hold":
                self.release.wait(WAIT)
                result = {"held": True, "served_by": name}
            else:
                result = {"served_by": name, "caller_device": connection.device_id}
            connection.emit({"jsonrpc": "2.0", "id": rid, "result": result})

        def lane_admitter() -> ConnectionAdmitter:
            return ConnectionAdmitter(
                root, boot_id=f"{name}-lanes", dispatch_line=dispatch,
                hello_payload=lambda message, c: {"event": "hello_ok", "transport": c.transport,
                                                  "install": install_address()},
                token_provider=lambda: None, authenticator=call_lane_authenticator(root),
                transport_name="gateway", reject_penalty_seconds=0.0)

        self.lanes = ReverseLanes(root, call_admitter_factory=lane_admitter, log=self.events.append)
        self.calls = self.lanes.calls
        hook = lambda admitter, connection, reader, message: handoff(
            self.lanes, admitter, connection, reader, message)
        self.gateway = ServeSocketServer(
            root, boot_id=f"{name}-boot", dispatch_line=lambda line, c: None,
            hello_payload=lambda message, c: {"event": "hello_ok", "install": install_address()},
            token_provider=lambda: None, authenticator=gateway_listener._gateway_authenticator(root),
            ssl_context=server_ssl_context(root), host="127.0.0.1", transport_name="gateway",
            handoff=hook, reject_penalty_seconds=0.0)
        self.port = self.gateway.bind()
        self.gateway.start_accepting()
        #: The machine owner's own lane (its Eternia attaches here with ``call_attach``).
        self.loopback = ServeSocketServer(
            root, boot_id=f"{name}-boot", dispatch_line=lambda line, c: None,
            hello_payload=lambda message, c: {"event": "hello_ok"}, token_provider=lambda: ROOT_TOKEN,
            host="127.0.0.1", handoff=hook, reject_penalty_seconds=0.0)
        self.loopback_port = self.loopback.bind()
        self.loopback.start_accepting()
        #: This engine's credential on each other engine, by that engine's name.
        self.credentials: dict[str, DeviceCredential] = {}

    def pair_on(self, other: _Engine) -> None:
        code = mint_pairing_code(other.root, name=self.name)
        assert isinstance(code, PairingCode)
        credential = redeem_pairing_code(other.root, code.code, **hello_fields())
        assert isinstance(credential, DeviceCredential)
        self.credentials[other.name] = credential

    def way_to(self, other: _Engine) -> CallWay:
        credential = self.credentials[other.name]
        return CallWay(host="127.0.0.1", port=other.port, cert_fingerprint=other.fingerprint,
                       machine_id=install_address()["machine_id"], install_id=other.install,
                       device_id=credential.device_id, token=credential.token)

    def call_to(self, other: _Engine) -> PairCall | None:
        return self.calls.registry.get(other.install)

    def lane_client(self, other: _Engine):
        call = self.call_to(other)
        assert call is not None
        lane = call.open_lane()
        client = call.client(lane)
        credential = self.credentials[other.name]
        reply = lane_device_hello(client, call=call, device_id=credential.device_id, token=credential.token)
        assert isinstance(reply, dict) and reply.get("event") == "hello_ok", reply
        return call, client

    def close(self) -> None:
        self.release.set()
        self.lanes.close()
        self.gateway.close()
        self.loopback.close()


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setattr(dialer_module, "_BACKOFF_FIRST", 0.05)
    monkeypatch.setattr(dialer_module, "_BACKOFF_MAX", 0.2)
    a, b = _Engine(tmp_path / "a-root", "a"), _Engine(tmp_path / "b-root", "b")
    try:
        a.pair_on(b)
        b.pair_on(a)
        low, high = sorted((a, b), key=lambda engine: engine.install)
        yield low, high
    finally:
        a.close()
        b.close()


def _one_shared_call(x: _Engine, y: _Engine) -> PairCall:
    """Both sides hold exactly one open call to the other, and it is the same call."""

    def same():
        cx, cy = x.call_to(y), y.call_to(x)
        return cx if cx is not None and cy is not None and cx.call_id == cy.call_id else None

    return _until(same, what="one shared call")


# ── one call per pair ────────────────────────────────────────────────────────


@pytest.mark.parametrize("first", ["low", "high"])
def test_two_engines_that_dial_each_other_keep_the_lower_dialers_call(pair, first):
    low, high = pair
    one, two = (low, high) if first == "low" else (high, low)
    earlier = one.calls.dial_once(one.way_to(two))
    assert isinstance(earlier, PairCall)
    _one_shared_call(low, high)
    later = two.calls.dial_once(two.way_to(one))
    assert isinstance(later, PairCall)
    _until(lambda: not (earlier.is_open and later.is_open), what="a duplicate closed")
    kept = _one_shared_call(low, high)
    assert kept.dialer_install == low.install
    assert high.call_to(low).dialer_install == low.install
    loser = later if first == "low" else earlier
    _until(lambda: not loser.is_open, what="the higher dialer's call closed")
    # Settled: nothing else is closed afterwards.
    time.sleep(0.3)
    assert _one_shared_call(low, high).call_id == kept.call_id


def test_the_kept_call_carries_both_sides_requests_and_both_answers(pair):
    low, high = pair
    low.calls.dial(low.way_to(high))
    high.calls.dial(high.way_to(low))
    shared = _one_shared_call(low, high)
    call, client = low.lane_client(high)
    assert call.call_id == shared.call_id
    answer = client.request("test.who", timeout=WAIT)
    assert answer["result"] == {"served_by": high.name, "caller_device": low.credentials[high.name].device_id}
    back_call, back = high.lane_client(low)
    assert back_call.call_id == shared.call_id
    answer = back.request("test.who", timeout=WAIT)
    assert answer["result"] == {"served_by": low.name, "caller_device": high.credentials[low.name].device_id}
    # Still the one call, carrying both directions.
    assert _one_shared_call(low, high).call_id == shared.call_id
    assert len(low.calls.status()["calls"]) == 1 and len(high.calls.status()["calls"]) == 1


# ── every frame names its receiver ───────────────────────────────────────────


def _raw(call: PairCall, frame: dict) -> None:
    with call._send_lock:
        call._sock.sendall((json.dumps(frame) + "\n").encode("utf-8"))


def test_a_frame_for_another_machine_is_dropped_before_its_namespace_is_read(pair):
    low, high = pair
    low.calls.dial_once(low.way_to(high))
    _one_shared_call(low, high)
    call, client = low.lane_client(high)
    request = lambda rid: json.dumps({"jsonrpc": "2.0", "id": rid, "method": "test.who"})
    far = call.far
    _raw(call, {"lane": client.lane_id, "to": "machine:machine_someone_else/namespace:elsewhere",
                "install": far.install_id, "line": request("wrong-machine")})
    _raw(call, {"lane": client.lane_id, "to": f"machine:{far.machine_id}/namespace:elsewhere",
                "install": far.install_id, "line": request("wrong-namespace")})
    _raw(call, {"lane": client.lane_id, "to": far.to(), "install": "another-install",
                "line": request("wrong-install")})
    _raw(call, wrap(client.lane_id, far, {"line": request("addressed")}))
    _until(lambda: ("addressed", "test.who") in high.served, what="the addressed request served")
    reasons = [e["reason"] for e in high.events if e.get("event") == "pair_call_address_mismatch"]
    assert reasons == [MISMATCH_MACHINE, MISMATCH_NAMESPACE, MISMATCH_INSTALL]
    served = {rid for rid, _ in high.served}
    assert not served & {"wrong-machine", "wrong-namespace", "wrong-install"}


def test_an_answer_on_another_lane_is_not_delivered(pair):
    low, high = pair
    low.calls.dial_once(low.way_to(high))
    shared = _one_shared_call(low, high)
    _call, first = low.lane_client(high)
    _call, second = low.lane_client(high)
    answers: list[dict] = []
    worker = threading.Thread(target=lambda: answers.append(first.request("test.hold", timeout=WAIT,
                                                                           request_id="r-1")))
    worker.start()
    _until(lambda: ("r-1", "test.hold") in high.served, what="the held request at the far engine")
    far_side = high.call_to(low)
    assert far_side.call_id == shared.call_id
    # An answer to r-1 arrives on the OTHER lane: it settles nothing.
    far_side.send_line(second.lane_id, json.dumps({"jsonrpc": "2.0", "id": "r-1", "result": {"forged": True}}))
    time.sleep(0.3)
    assert answers == []
    high.release.set()
    worker.join(WAIT)
    assert answers and answers[0]["result"] == {"held": True, "served_by": high.name}


# ── a drop ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("redialer", ["dialer", "accepter"])
def test_a_killed_call_fails_its_requests_and_both_sides_redial(pair, redialer):
    low, high = pair
    low.calls.dial(low.way_to(high))
    high.calls.dial(high.way_to(low))
    killed = _one_shared_call(low, high)
    dialled_by = low if killed.dialer_install == low.install else high
    accepted_by = high if dialled_by is low else low
    # Only one side can reach the other afterwards: the side that must redial keeps its way out,
    # and the other side's listener closes so only that side's dial can connect.
    must_redial = dialled_by if redialer == "dialer" else accepted_by
    _call, client = low.lane_client(high)
    answers: list[dict] = []
    worker = threading.Thread(target=lambda: answers.append(client.request("test.hold", timeout=WAIT)))
    worker.start()
    _until(lambda: any(method == "test.hold" for _, method in high.served), what="the request in flight")
    must_redial.gateway.close()
    held = low.call_to(high)
    held._sock.shutdown(socket.SHUT_RDWR)
    worker.join(WAIT)
    assert answers == [{"ok": False, "reason": "link_closed", "dispatched": True, "confirmed": False}]
    back = _one_shared_call(low, high)
    assert back.call_id != killed.call_id
    assert back.dialer_install == must_redial.install


# ── through a real serve: the phone dials, the computer's Eternia rides a lane ──


def test_a_computers_eternia_uses_the_phones_engine_on_a_lane_of_the_call_the_phone_opened(phone, tmp_path):
    from agent_runtime.gateway_identity import ensure_install_identity as identity

    computer = _Engine(tmp_path / "computer-root", "computer")
    try:
        code = mint_pairing_code(computer.root, name="phone")
        device = redeem_pairing_code(computer.root, code.code, **hello_fields())
        machine = install_address()["machine_id"]
        credential = grants.grant_computer(_phone_root(), computer_install_id=computer.install,
                                           pairing_device_id=device.device_id, level=grants.GRANT_ACCOUNT,
                                           computer_machine_id=machine)
        answer = phone.rpc("runtime.gateway.call.dial", {
            "install_id": computer.install, "host": "127.0.0.1", "port": computer.port,
            "cert_fingerprint": computer.fingerprint, "machine_id": machine,
            "device_id": device.device_id, "token": device.token})
        assert answer.get("result") == {"far_install": computer.install}, answer
        phone_install = identity(_phone_root()).install_id
        call = _until(lambda: computer.calls.registry.get(phone_install), what="the phone's call")
        assert call.far_device_id == device.device_id and not call.outbound
        eternia = ServeSocketClient("127.0.0.1", computer.loopback_port, timeout_seconds=WAIT)
        eternia.connect()
        try:
            attached = eternia.hello(token=ROOT_TOKEN, client="eternia-computer", call_attach=phone_install)
            assert attached["event"] == "call_attached" and attached["call"] == call.call_id, attached
            hello_ok = eternia.lane_hello(computer_id=credential.computer_id, token=credential.token,
                                          lane_id=attached["lane_id"], client="eternia-computer")
            assert hello_ok is not None and hello_ok.get("event") == "hello_ok", hello_ok
            assert hello_ok["transport"] == "gateway"
            assert "result" in _rpc(eternia, "runtime.health")
        finally:
            eternia.close()
        calls = phone.rpc("runtime.gateway.call.calls")["result"]["calls"]
        assert [(c["call"], c["far"]["install_id"], c["outbound"]) for c in calls] == [
            (call.call_id, computer.install, True)]
    finally:
        phone.rpc("runtime.gateway.call.hangup")
        computer.close()


# ── the phone's call door ────────────────────────────────────────────────────


class _DoorClient(ServeSocketClient):
    """The phone's Eternia on its engine's call door: the reference client over a socket FILE.

    The hello's proof binds port ``0`` (``CALL_DOOR_FILENAME``'s note): there is no port.
    """

    def __init__(self, path: Path) -> None:
        super().__init__("call-door", 0, timeout_seconds=WAIT)
        self._door = path

    def connect(self) -> None:
        from agent_runtime.serve_socket.vocabulary import MAX_SERVE_FRAME_BYTES
        from agent_runtime.serve_socket.wire import _LineReader

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(WAIT)
        sock.connect(str(self._door))
        self._sock = sock
        self._reader = _LineReader(sock, max_line_bytes=MAX_SERVE_FRAME_BYTES)


@pytest.fixture
def short_door(monkeypatch):
    """The door in a short folder: a bundled run's temp root alone passes AF_UNIX's 108-byte path limit.

    Only the folder moves; the file name and the join are production's (``call_door_path``'s own
    test pins that the door sits in the store root).
    """

    import shutil
    import tempfile

    from agent_runtime.serve_socket import server as server_module

    folder = Path(tempfile.mkdtemp(prefix="hd-", dir="/tmp"))
    real = server_module.call_door_path
    monkeypatch.setattr(server_module, "call_door_path", lambda store_root: real(folder))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def embedded_phone(short_door):
    """The phone: the real serve loop under the embedded shell, as ``EmbeddedServe`` runs it."""

    from hermes_cli.harness_parts.serve import serve_loop
    from hermes_cli.harness_parts.serve.shell import EmbeddedShell

    pipe, sink = _Pipe(), _Sink()
    thread = threading.Thread(
        target=serve_loop, args=(pipe, sink),
        kwargs={"dispatch": lambda argv: 0, "liveness_pump_interval_seconds": 60.0, "shell": EmbeddedShell()},
        name="embedded-phone-serve-under-test", daemon=True,
    )
    thread.start()
    ready = sink.wait_for(lambda f: f.get("event") == "ready")
    try:
        yield _Phone(pipe, sink), ready
    finally:
        pipe.close()
        thread.join(WAIT)


def _door() -> Path:
    from agent_runtime.serve_socket import server as server_module

    return server_module.call_door_path(_phone_root())


def _root_token() -> str:
    from agent_runtime.serve_auth import read_token

    token = read_token(_phone_root())
    assert token, "the embedded serve minted no root token"
    return token


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="the call door is a unix socket file")
def test_the_phones_eternia_reaches_its_computer_through_the_call_door_on_the_call_the_phone_opened(
        embedded_phone, tmp_path):
    phone, _ready = embedded_phone
    computer = _Engine(tmp_path / "computer-root", "computer")
    try:
        code = mint_pairing_code(computer.root, name="phone")
        device = redeem_pairing_code(computer.root, code.code, **hello_fields())
        answer = phone.rpc("runtime.gateway.call.dial", {
            "install_id": computer.install, "host": "127.0.0.1", "port": computer.port,
            "cert_fingerprint": computer.fingerprint, "machine_id": install_address()["machine_id"],
            "device_id": device.device_id, "token": device.token})
        assert answer.get("result") == {"far_install": computer.install}, answer
        _until(lambda: phone.rpc("runtime.gateway.call.calls")["result"]["calls"], what="the phone's call up")
        eternia = _DoorClient(_door())
        eternia.connect()
        try:
            attached = eternia.hello(token=_root_token(), client="eternia-phone", call_attach=computer.install)
            assert attached is not None and attached["event"] == "call_attached", attached
            # Every byte from here is the computer's: its lane admitter's challenge, over the call.
            challenge = eternia.read_frame()
            assert challenge is not None and challenge["event"] == "server_hello", challenge
            from agent_runtime.serve_gateway_auth.proof import call_lane_proof

            eternia.send({"op": "hello", "client": "eternia-phone", "device_id": device.device_id,
                          **hello_fields(),
                          "proof": call_lane_proof(device.token, challenge["nonce"], call_id=attached["call"],
                                                   lane_id=attached["lane_id"], device_id=device.device_id)})
            hello_ok = eternia.read_frame()
            assert hello_ok is not None and hello_ok.get("event") == "hello_ok", hello_ok
            assert _rpc(eternia, "test.where")["result"] == {"served_by": "computer",
                                                             "caller_device": device.device_id}
        finally:
            eternia.close()
        # One call between them, the one the phone opened: the door added no second connection.
        calls = phone.rpc("runtime.gateway.call.calls")["result"]["calls"]
        assert [(c["far"]["install_id"], c["outbound"]) for c in calls] == [(computer.install, True)]
    finally:
        phone.rpc("runtime.gateway.call.hangup")
        computer.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="the call door is a unix socket file")
def test_the_phones_greeting_names_its_call_door(embedded_phone):
    _phone, ready = embedded_phone
    assert ready["socket"]["outcome"] == "listening", ready["socket"]
    assert ready["socket"]["path"] == str(_door())
    assert _door().exists()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="the call door is a unix socket file")
def test_a_hello_without_the_roots_proof_is_refused_on_the_call_door(embedded_phone):
    eternia = _DoorClient(_door())
    eternia.connect()
    try:
        refused = eternia.hello(token="not-" + _root_token(), client="another-app")
        assert refused is not None and refused["event"] == "hello_rejected", refused
        assert refused["reason"] == "bad_proof"
    finally:
        eternia.close()
    # Positive control: the root's proof is admitted on the same door.
    eternia = _DoorClient(_door())
    eternia.connect()
    try:
        admitted = eternia.hello(token=_root_token(), client="eternia-phone")
        assert admitted is not None and admitted["event"] == "hello_ok", admitted
    finally:
        eternia.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="the call door is a unix socket file")
def test_an_ordinary_method_line_on_the_call_door_is_refused(embedded_phone):
    eternia = _DoorClient(_door())
    eternia.connect()
    try:
        admitted = eternia.hello(token=_root_token(), client="eternia-phone")
        assert admitted is not None and admitted["event"] == "hello_ok", admitted
        refused = _rpc(eternia, "runtime.health")
        assert "result" not in refused and refused["error"] == "call_door_calls_only", refused
    finally:
        eternia.close()
    # Positive control: the same method on the phone's own lane (the embedded link) is answered.
    phone, _ready = embedded_phone
    assert "result" in phone.rpc("runtime.health")
