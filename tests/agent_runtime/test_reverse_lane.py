"""A computer drives a phone's engine over the lane the PHONE dialled (D3 holds: no listener).

Row ``MC-PHONE-DRIVEN-THE-PHONE-DIALS-OUT-SO-A-COMPUTER-CAN-REACH-ITS-ENGINE`` (Eternia), review
w1118a.79's corrections. The PHONE here is the real ``serve_loop`` (stdio only — it binds no socket
at all), so its dispatcher, its authorization and its greeting are the ones a phone runs. The
COMPUTER is its two real listeners (``ServeSocketServer``: loopback with a root token, gateway with
TLS and the device store) on their own store root, with the reverse lanes' hello hook; its owner's
Eternia is a ``ServeSocketClient`` on the loopback lane. Real sockets, real TLS, a real pin, real
HMAC proofs throughout.

Killing mutations (each named at its line):

* ``call_authorization._computer_arm``: admit the chat grant by the console tier, and the
  never-served test sees sign-in and key set answered;
* ``authorize_call``: ask the computer arm after the read opening, and the look test sees a read
  verb outside the allowlist answered;
* ``reverse_lane.lanes.lane_authenticator``: verify against the lane id the hello claims instead of
  the binding, and the wrong-lane test is admitted;
* ``ReverseLanes._grants_revoked``: drop the lane close, and the grant-off test stays connected.
"""

from __future__ import annotations

import json
import queue
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime.serve_rpc import registry
from agent_runtime.gateway_tls import ensure_certificate, server_ssl_context
from agent_runtime.reverse_lane import grants
from agent_runtime.reverse_lane.lanes import ReverseLanes, handoff
from agent_runtime.serve_gateway_auth import (
    DeviceCredential,
    PairingCode,
    mint_pairing_code,
    redeem_pairing_code,
    revoke_device,
)
from agent_runtime.serve_gateway_auth.proof import reverse_lane_proof
from agent_runtime.serve_socket import ServeSocketClient
from agent_runtime.serve_socket.server import ServeSocketServer
from hermes_cli.harness_parts.serve import gateway_listener, serve_loop

WAIT = 20.0
ROOT_TOKEN = "computer-root-token-" + "a" * 40


# ── the phone: the real serve loop, over its pipe ────────────────────────────


class _Pipe:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        item = self._queue.get()
        if item is None:
            raise StopIteration
        return item

    def send(self, message: dict) -> None:
        self._queue.put(json.dumps(message) + "\n")

    def close(self) -> None:
        self._queue.put(None)


class _Sink:
    def __init__(self) -> None:
        self._parts: list[str] = []
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._parts.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def frames(self) -> list[dict]:
        with self._lock:
            text = "".join(self._parts)
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def wait_for(self, predicate, timeout: float = WAIT) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in self.frames():
                if predicate(frame):
                    return frame
            time.sleep(0.01)
        raise AssertionError("no matching frame")


class _Phone:
    def __init__(self, pipe: _Pipe, sink: _Sink) -> None:
        self.pipe, self.sink = pipe, sink
        self._ids = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._ids += 1
        rid = f"phone-{self._ids}"
        self.pipe.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        return self.sink.wait_for(lambda f: f.get("id") == rid and ("result" in f or "error" in f))


@pytest.fixture
def phone():
    pipe, sink = _Pipe(), _Sink()
    thread = threading.Thread(
        target=serve_loop, args=(pipe, sink),
        kwargs={"dispatch": lambda argv: 0, "liveness_pump_interval_seconds": 60.0},
        name="phone-serve-under-test", daemon=True,
    )
    thread.start()
    sink.wait_for(lambda f: f.get("event") == "ready")
    try:
        yield _Phone(pipe, sink)
    finally:
        pipe.close()
        thread.join(WAIT)


def _phone_root() -> Path:
    from agent_runtime import paths

    return paths.store_root()


# ── the computer: its two listeners and the reverse lanes' hook ──────────────


class _Computer:
    def __init__(self, root: Path) -> None:
        self.root = root
        certificate = ensure_certificate(root)
        assert certificate.ok
        self.fingerprint = certificate.fingerprint
        self.lanes = ReverseLanes(root)
        hook = lambda admitter, connection, reader, message: handoff(  # noqa: E731
            self.lanes, admitter, connection, reader, message)
        common = dict(boot_id="computer-boot", dispatch_line=lambda line, c: None,
                      hello_payload=lambda message, c: {"event": "hello_ok", "transport": c.transport},
                      handoff=hook, reject_penalty_seconds=0.0)
        self.gateway = ServeSocketServer(
            root, token_provider=lambda: None, authenticator=gateway_listener._gateway_authenticator(root),
            ssl_context=server_ssl_context(root), host="127.0.0.1", transport_name="gateway", **common)
        self.loopback = ServeSocketServer(root, token_provider=lambda: ROOT_TOKEN, host="127.0.0.1", **common)
        self.gateway_port = self.gateway.bind()
        self.loopback_port = self.loopback.bind()
        self.gateway.start_accepting()
        self.loopback.start_accepting()

    def pair_phone(self, tier: str = ca.TIER_READ) -> DeviceCredential:
        code = mint_pairing_code(self.root, tier=tier, name="phone")
        assert isinstance(code, PairingCode)
        credential = redeem_pairing_code(self.root, code.code)
        assert isinstance(credential, DeviceCredential)
        return credential

    def close(self) -> None:
        self.lanes.close()
        self.gateway.close()
        self.loopback.close()

    def wait_parked(self, device_id: str) -> None:
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            if any(p["device_id"] == device_id for p in self.lanes.status()["parked"]):
                return
            time.sleep(0.02)
        raise AssertionError(f"no lane parked for {device_id}")

    @contextmanager
    def attach(self, device_id: str):
        """The owner's Eternia: the loopback hello with ``reverse_attach``; yields (client, lane id)."""

        client = ServeSocketClient("127.0.0.1", self.loopback_port, timeout_seconds=WAIT)
        client.connect()
        try:
            reply = client.hello(token=ROOT_TOKEN, client="eternia-computer", reverse_attach=device_id)
            assert reply is not None
            yield client, reply
        finally:
            client.close()


@pytest.fixture
def computer(tmp_path):
    computer = _Computer(tmp_path / "computer-root")
    try:
        yield computer
    finally:
        computer.close()


def _rpc(client: ServeSocketClient, method: str, params: dict | None = None) -> dict:
    rid = f"c-{secrets.token_hex(4)}"
    client.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    for _ in range(200):
        frame = client.read_frame()
        if frame is None:
            raise AssertionError(f"the lane closed before a reply to {method}")
        if frame.get("id") == rid and ("result" in frame or "error" in frame):
            return frame
    raise AssertionError(f"no reply to {method}")


def _grant_and_dial(phone: _Phone, computer: _Computer, level: str = grants.GRANT_LOOK):
    device = computer.pair_phone()
    credential = grants.grant_computer(_phone_root(), computer_install_id="computer-install",
                                       pairing_device_id=device.device_id, level=level)
    answer = phone.rpc("runtime.gateway.reverse.dial", {
        "computer_install_id": "computer-install", "host": "127.0.0.1", "port": computer.gateway_port,
        "cert_fingerprint": computer.fingerprint, "device_id": device.device_id, "token": device.token})
    assert "result" in answer, answer
    assert answer["result"]["computer_id"] == credential.computer_id
    computer.wait_parked(device.device_id)
    return device, credential


@contextmanager
def _driven(phone: _Phone, computer: _Computer, level: str = grants.GRANT_LOOK):
    """Grant, dial, attach and say the lane hello; yields the computer's client on the phone."""

    device, credential = _grant_and_dial(phone, computer, level)
    with computer.attach(device.device_id) as (client, attached):
        assert attached["event"] == "reverse_attached", attached
        reply = client.lane_hello(computer_id=credential.computer_id, token=credential.token,
                                  lane_id=attached["lane_id"], client="eternia-computer")
        assert reply is not None and reply.get("event") == "hello_ok", reply
        yield client, reply, device, credential


def _scope_denied(frame: dict) -> bool:
    error = frame.get("error") or {}
    return "result" not in frame and (error.get("data") or {}).get("reason") == ca.REASON_SCOPE_DENIED


# ── the route ────────────────────────────────────────────────────────────────


def test_the_computer_reaches_the_phones_engine_and_look_reads_but_never_sends(phone, computer):
    with _driven(phone, computer) as (client, hello_ok, _device, credential):
        # The phone's own greeting, on the remote door's transport.
        assert hello_ok["transport"] == "gateway"
        assert "paired" not in hello_ok
        assert "result" in _rpc(client, "runtime.health")
        directory = _rpc(client, "runtime.agent.directory")
        assert not _scope_denied(directory), directory
        # A console verb outside the look allowlist: the phone's own refusal.
        assert _scope_denied(_rpc(client, "runtime.chat.message", {"persona_instance_id": "x", "message": "hi"}))
        # A READ verb outside the allowlist is refused too: the arm runs before the read opening.
        # MUTATION: ask the computer arm after the read opening and this read is answered.
        assert _scope_denied(_rpc(client, "runtime.characters.list"))
        status = phone.rpc("runtime.gateway.reverse.lanes")["result"]
        assert [d["state"] for d in status["dialing"]] == ["connected"]
        assert status["dialing"][0]["computer_id"] == credential.computer_id


def test_the_computer_reads_the_phone_agents_files_as_one_tree_at_look(phone, computer, tmp_path):
    """Row ``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE``: the look grant
    browses, reads and searches the phone agent's roots over the lane, and nothing outside them.

    MUTATION (the stated ``computer=`` reach): leave ``runtime.agent.files.*`` out, and every
    call here is refused ``scope_denied``.
    """

    from tests.agent_runtime.test_agent_files import INSTANCE, _agent, _folder

    project = _folder(tmp_path, "notes", {"todo.md": "buy milk\n", "sub/plan.md": "phone plan\n"})
    _agent(tmp_path, {"notes": project})
    with _driven(phone, computer) as (client, *_):
        tree = _rpc(client, "runtime.agent.files.tree", {"persona_instance_id": INSTANCE, "depth": 3})
        assert [e["path"] for e in tree["result"]["entries"]] == [
            "notes", "notes/sub", "notes/sub/plan.md", "notes/todo.md"], tree
        read = _rpc(client, "runtime.agent.files.read", {"persona_instance_id": INSTANCE, "path": "notes/todo.md"})
        assert read["result"]["content"] == "buy milk\n", read
        grep = _rpc(client, "runtime.agent.files.grep", {"persona_instance_id": INSTANCE, "pattern": "plan"})
        assert [m["path"] for m in grep["result"]["matches"]] == ["notes/sub/plan.md"], grep
        outside = _rpc(client, "runtime.agent.files.read", {"persona_instance_id": INSTANCE, "path": "/etc/hostname"})
        assert outside["error"]["data"]["reason"] == "invalid_path", outside


def test_a_look_computer_is_handed_a_picture_from_the_phones_chats_by_handle(phone, computer, tmp_path):
    """Hermes row RT-FU-A-COMPUTER-USING-A-PHONES-AGENTS-IS-HANDED-THE-PICTURES-IN-THE-CHATS-IT-MAY-READ:
    over the real lane, the look grant lists the phone's chat picture and fetches it by handle.

    MUTATION (the stated ``computer=`` reach): leave ``runtime.media.index`` / ``.get`` out, and
    both calls here are refused ``scope_denied``. Which rows the grant sees is pinned in
    ``test_serve_rpc_media``.
    """

    import base64

    from agent_runtime import chat_live_log, media_handles

    chat_live_log.reset_chat_live_log_state()
    media_handles.reset_digest_memo()
    chat_live_log.capture_chat_live_log_root(head_home=tmp_path / "phone-home")
    payload = b"\x89PNG\r\n\x1a\n" + b"phone-picture" * 20
    shot = tmp_path / "phone-home" / "artifacts" / "chat.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(payload)
    logs = tmp_path / "phone-home" / chat_live_log.CHAT_LIVE_LOG_DIRNAME
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "persona_chat_phone.jsonl").write_text(json.dumps(
        {"ts": "2026-11-22T00:00:00Z", "kind": "message", "role": "agent", "text": f"here\n\nMEDIA:{shot}"}) + "\n",
        encoding="utf-8")
    try:
        with _driven(phone, computer) as (client, *_):
            index = _rpc(client, "runtime.media.index")
            assert "result" in index, index
            handles = [row["handle"] for row in index["result"]["artifacts"] if row["reference"] == str(shot)]
            assert len(handles) == 1, index
            picture = _rpc(client, "runtime.media.get", {"handle": handles[0]})
            assert base64.b64decode(picture["result"]["data"]) == payload, picture
    finally:
        chat_live_log.reset_chat_live_log_state()
        media_handles.reset_digest_memo()


def test_run_chats_reaches_the_attach_read_with_its_own_scope_and_new_chat_by_agent_and_look_neither(phone, computer):
    """Hermes row RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT:
    over the real lane, Run chats is answered ``runtime.agent.idle_instances`` and the attach read,
    under its grant's own scope whether it names one or not (RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-
    OWN-CHAT-SCOPE); Look is refused both. Which chats the scope opens is pinned in
    ``test_operator_conversation_attachment``.

    MUTATION (the stated ``computer=`` reach): leave the two reads out, and both are refused
    ``scope_denied`` here at Run chats.
    """

    attach = {"install_id": "i", "persona_id": "p", "persona_instance_id": "personainst_p", "session_id": "s"}
    with _driven(phone, computer, grants.GRANT_CHAT) as (client, *_):
        idle = _rpc(client, "runtime.agent.idle_instances", {})
        assert not _scope_denied(idle), idle
        for named in ({}, {"client_scope": "c" * 64}):
            read = _rpc(client, "runtime.operator.conversation.read", {**attach, **named})
            assert not _scope_denied(read), read
            assert read.get("error", {}).get("data", {}).get("reason") != "client_scope_required", read


def test_look_is_refused_the_attach_read_and_new_chat_by_agent(phone, computer):
    with _driven(phone, computer) as (client, *_):
        assert _scope_denied(_rpc(client, "runtime.agent.idle_instances", {}))
        assert _scope_denied(_rpc(client, "runtime.operator.conversation.read", {"client_scope": "c" * 64}))


NEVER_SERVED = (
    # The review's three, by name.
    "runtime.provider.signin.begin",
    "runtime.provider.key.set",
    "runtime.gateway.devices.list",
    # The rest of sign-in, keys and provider settings.
    "runtime.provider.signin.complete",
    "runtime.provider.signin.poll",
    "runtime.provider.signout",
    "runtime.provider.configure",
    "runtime.provider.env_token.remove",
    "runtime.provider.source.set",
    "runtime.default_model.set",
    # This lane's own verbs: the phone's credential on the computer.
    "runtime.gateway.reverse.dial",
    "runtime.gateway.reverse.hangup",
    "runtime.gateway.reverse.lanes",
)

#: No verb on this wire reaches the secure store or a namespace switch or delete: the secure
#: store's callbacks run in-process (host calls, never frames) and a namespace is the host's
#: boot line. Sent anyway, by the names a client would guess, and never served.
NOT_ON_THE_WIRE = ("vault.get", "vault.set", "runtime.secure_store.read", "runtime.namespace.use",
                   "runtime.namespace.delete")


def test_the_chat_grant_never_reaches_sign_in_keys_pairing_settings_namespaces_or_the_secure_store(phone, computer):
    """Review w1118a.79's done-when: at the chat grant each is refused over the lane.

    MUTATION (``call_authorization._computer_arm``): admit the chat grant by the console tier, and
    sign-in and key set are answered here.
    """

    with _driven(phone, computer, grants.GRANT_CHAT) as (client, *_):
        for name in sorted(ca.LOCAL_CONSOLE_METHODS) + list(NEVER_SERVED):
            frame = _rpc(client, name)
            assert _scope_denied(frame), (name, frame)
        for name in NOT_ON_THE_WIRE:
            frame = _rpc(client, name)
            assert "result" not in frame and "error" in frame, (name, frame)
        # The chat grant does reach a chat verb: refused for its params, not its caller.
        assert not _scope_denied(_rpc(client, "runtime.chat.message", {}))
        # The remote door's ops refusals hold on the lane: no drain, no shutdown.
        client.send({"op": "drain", "id": "op-drain"})
        frame = client.read_frame()
        assert frame is not None and frame.get("error") == "op_not_available_on_gateway", frame


def test_an_account_computer_reaches_console_verbs_over_the_lane_and_never_a_local_console_verb(phone, computer):
    """Hermes row RT-PHONE-DRIVEN-A-COMPUTER-ON-THE-PHONES-OWN-ACCOUNT-…: the account level over the real lane.

    MUTATION (``call_authorization._computer_arm``): answer the account level from the chat
    allowlist, and Skills and the level read are refused here.
    """

    with _driven(phone, computer, grants.GRANT_ACCOUNT) as (client, *_):
        for name in sorted(ca.LOCAL_CONSOLE_METHODS):
            frame = _rpc(client, name)
            assert _scope_denied(frame), (name, frame)
        for name in ("runtime.skills.catalog", "runtime.level.get", "runtime.provider.key.set"):
            assert not _scope_denied(_rpc(client, name, {})), name


def test_a_proof_answered_for_another_lane_is_refused_bad_proof(phone, computer):
    """MUTATION (``lane_authenticator``): verify against the lane id the hello claims, not the
    binding, and this hello is admitted."""

    device, credential = _grant_and_dial(phone, computer)
    with computer.attach(device.device_id) as (client, attached):
        assert attached["event"] == "reverse_attached"
        wrong = "f" * 32 if attached["lane_id"] != "f" * 32 else "e" * 32
        greeting = client._challenge_nonce(3)
        client.send({"op": "hello", "client": "eternia-computer", "device_id": credential.computer_id,
                     "lane_id": wrong,
                     "proof": reverse_lane_proof(credential.token, greeting, lane_id=wrong,
                                                 device_id=credential.computer_id)})
        reply = client.read_frame()
        assert reply == {"event": "hello_rejected", "reason": "bad_proof"}


def test_turning_the_grant_off_closes_the_open_lane_at_once(phone, computer):
    """MUTATION (``ReverseLanes._grants_revoked``): drop the lane close and the computer stays on."""

    with _driven(phone, computer) as (client, _hello, _device, credential):
        assert grants.revoke_grant(_phone_root(), credential.computer_id)
        client.set_timeout(5.0)
        closed = False
        while not closed:
            try:
                closed = client.read_frame() is None
            except socket.timeout:  # noqa: UP041 - still open: the grant's lane outlived it
                pytest.fail("the computer's lane stayed open after the phone turned the grant off")
            except OSError:
                closed = True
        assert phone.rpc("runtime.gateway.reverse.lanes")["result"]["dialing"] == []


def test_a_downgrade_closes_the_live_lane_and_the_redial_is_stamped_look_with_the_same_credential(phone, computer):
    """Hermes row RT-FU-A-PHONE-CHANGING-A-COMPUTERS-LEVEL-KEEPS-ITS-CREDENTIAL-AND-ITS-ACCEPT: Run chats to
    Look in place closes the computer's live lane at once, and its redial with the SAME credential is
    admitted and stamped look.

    MUTATION (``grants.change_level``): skip the level notice, and the lane stamped chat stays open.
    """

    with _driven(phone, computer, grants.GRANT_CHAT) as (client, _hello, device, credential):
        assert not _scope_denied(_rpc(client, "runtime.chat.message", {}))
        held = grants.change_level(_phone_root(), computer_install_id="computer-install",
                                   pairing_device_id=device.device_id, level=grants.GRANT_LOOK)
        assert held is not None and held.computer_id == credential.computer_id
        client.set_timeout(5.0)
        closed = False
        while not closed:
            try:
                closed = client.read_frame() is None
            except socket.timeout:  # noqa: UP041 - still open: a connection kept the chat stamp
                pytest.fail("the computer's lane stayed open, stamped chat, after the phone set Look")
            except OSError:
                closed = True
    computer.wait_parked(device.device_id)
    with computer.attach(device.device_id) as (client, attached):
        assert attached["event"] == "reverse_attached", attached
        reply = client.lane_hello(computer_id=credential.computer_id, token=credential.token,
                                  lane_id=attached["lane_id"], client="eternia-computer")
        assert reply is not None and reply.get("event") == "hello_ok", reply
        assert _scope_denied(_rpc(client, "runtime.chat.message", {}))
        assert not _scope_denied(_rpc(client, "runtime.agent.directory"))


def test_an_unpair_on_the_computer_refuses_the_next_dial_and_the_phone_drops_its_grant(phone, computer):
    device, credential = _grant_and_dial(phone, computer)
    revoke_device(computer.root, device.device_id)
    # The parked lane belongs to a device that is no longer paired: the owner finds it away.
    with computer.attach(device.device_id) as (_client, attached):
        assert attached == {"event": "hello_rejected", "reason": "reverse_lane_absent"}
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and grants.grant_for_install(_phone_root(), "computer-install"):
        time.sleep(0.05)
    # The phone redialled, was refused bad_proof (unpaired), and deleted its grant for that computer.
    assert grants.grant_for_install(_phone_root(), "computer-install") is None


def test_a_re_pair_starts_with_no_grant(phone, computer):
    old = computer.pair_phone()
    grants.grant_computer(_phone_root(), computer_install_id="computer-install",
                          pairing_device_id=old.device_id, level=grants.GRANT_CHAT)
    new = computer.pair_phone()
    answer = phone.rpc("runtime.gateway.reverse.dial", {
        "computer_install_id": "computer-install", "host": "127.0.0.1", "port": computer.gateway_port,
        "cert_fingerprint": computer.fingerprint, "device_id": new.device_id, "token": new.token})
    assert answer["error"]["data"]["reason"] == "no_grant"
    assert grants.grant_for_install(_phone_root(), "computer-install") is None


# ── the computer's doors ─────────────────────────────────────────────────────


def test_only_a_paired_device_parks_and_only_the_owner_attaches(computer):
    device = computer.pair_phone()
    # A park asked on the loopback lane by the owner: refused.
    client = ServeSocketClient("127.0.0.1", computer.loopback_port, timeout_seconds=WAIT)
    client.connect()
    try:
        nonce = client._challenge_nonce(3)
        from agent_runtime.serve_socket.hello import hello_proof

        client.send({"op": "hello", "client": "x", "proof": hello_proof(ROOT_TOKEN, nonce, port=computer.loopback_port),
                     "reverse_lane": "a" * 32})
        assert client.read_frame() == {"event": "hello_rejected", "reason": "reverse_lane_refused"}
    finally:
        client.close()
    # An attach asked on the gateway by a device: refused.
    client = ServeSocketClient("127.0.0.1", computer.gateway_port, timeout_seconds=WAIT,
                               cert_fingerprint=computer.fingerprint)
    client.connect()
    try:
        nonce = client._challenge_nonce(3)
        from agent_runtime.serve_gateway_auth import device_proof

        client.send({"op": "hello", "client": "x", "device_id": device.device_id,
                     "proof": device_proof(device.token, nonce, port=computer.gateway_port, device_id=device.device_id),
                     "reverse_attach": device.device_id})
        assert client.read_frame() == {"event": "hello_rejected", "reason": "reverse_lane_refused"}
    finally:
        client.close()
    # The owner attaching to a device with no lane parked: away.
    with computer.attach(device.device_id) as (_client, reply):
        assert reply == {"event": "hello_rejected", "reason": "reverse_lane_absent"}


# ── the caller ───────────────────────────────────────────────────────────────


class _Conn:
    def __init__(self, **stamps) -> None:
        self.transport, self.key, self.authenticated = "gateway", "conn-1", True
        self.device_id = self.device_tier = self.peer_install_id = None
        self.computer_id = self.computer_grant = None
        self.__dict__.update(stamps)


def test_a_lane_connection_is_a_computer_caller_and_two_stamps_are_nobody():
    caller = ca.caller_for_connection(_Conn(computer_id="cmp-1", computer_grant="look"))
    assert caller.kind == ca.CALLER_COMPUTER and caller.computer_grant == "look"
    both = _Conn(computer_id="cmp-1", computer_grant="chat", device_id="dev-1", device_tier="console")
    assert ca.caller_for_connection(both).kind == ca.CALLER_UNKNOWN
    assert ca.caller_for_connection(_Conn(computer_id="cmp-1", computer_grant="console")).kind == ca.CALLER_UNKNOWN
    assert ca.caller_for_connection(_Conn()).kind == ca.CALLER_UNKNOWN  # gateway with no stamp


def test_the_look_allowlist_is_reads_and_the_chat_allowlist_adds_only_chat_verbs():
    assert not registry.COMPUTER_LOOK_METHOD_ALLOWLIST & ca.LOCAL_CONSOLE_METHODS
    assert not registry.COMPUTER_CHAT_METHOD_ALLOWLIST & ca.LOCAL_CONSOLE_METHODS
    extra = registry.COMPUTER_CHAT_METHOD_ALLOWLIST - registry.COMPUTER_LOOK_METHOD_ALLOWLIST
    assert "runtime.chat.message" in extra
    assert not any(name.startswith("runtime.provider.") for name in registry.COMPUTER_CHAT_METHOD_ALLOWLIST)


def test_a_send_under_a_look_grant_is_refused_in_words_the_composer_shows():
    """Eternia row MC-PHONE-DRIVEN-A-COMPUTER-RUNS-A-CHAT-TURN-ON-A-PHONES-AGENT: the computer's
    composer shows hermes' refusal as written, so a chat verb under a look grant says what the
    phone allows and where the switch is; other refusals keep the verb's name."""

    look = ca.caller_for_connection(_Conn(computer_id="cmp-1", computer_grant="look"))
    send = ca.authorize_call(ca.TIER_CONSOLE, look, method="runtime.chat.message",
                             computer_reach=registry.method_computer_reach("runtime.chat.message"))
    assert not send.ok and send.reason == ca.REASON_SCOPE_DENIED
    assert send.detail.startswith("This phone lets this computer look at its agents but not chat")
    assert "Run chats" in send.detail
    other = ca.authorize_call(ca.TIER_CONSOLE, look, method="runtime.provider.key.set")
    assert not other.ok and other.detail.startswith("runtime.provider.key.set is not open")
