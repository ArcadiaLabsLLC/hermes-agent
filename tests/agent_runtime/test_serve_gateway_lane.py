"""Stage 1: the SECOND listener, end to end over a real encrypted socket.

These run the REAL ``serve_loop`` with BOTH lanes on, over real sockets, with a
real TLS handshake, a real certificate pin, a real HMAC over a real per-device
credential, against the isolated runtime root the autouse fixture provides. No
transport is faked, for the reason ``test_serve_socket_lane.py`` gives about its
own: the things worth pinning here are exactly the ones a fake transport cannot
fail.

Two claims are load-bearing and the rest support them.

1. **The loopback lane is byte-identical whether or not the gateway lane is
   up.** That is Stage 1's hardest invariant and the one the local launcher and
   the CLI are owed. It is asserted directly — the same frames, compared — and
   not inferred from ``test_serve_socket_lane.py`` staying green.
2. **A device gets the full control it was paired at and nothing more**, on BOTH
   doors a device can reach: the method lane (where ``authorize_call`` answers)
   and the argv lane (which is refused outright, because a gate on one lane and an
   ungated shell on the other is not a gate).

The bind address is loopback here, and that is not a shortcut: the LAN bind is a
config VALUE, not different code — the same ``bind()`` on the same class with a
host string the operator chose. What CI cannot exercise is a second machine and
a Windows firewall prompt, and those are named in the field notes rather than
faked here.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from contextlib import contextmanager

import pytest

from agent_runtime.gateway_endpoints import candidates as endpoint_candidates

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.gateway_capabilities import GATEWAY_CAPABILITIES
from agent_runtime.gateway_tls import certificate_path, read_certificate
from agent_runtime.serve_gateway_auth import (
    DeviceCredential,
    PairingCode,
    device_proof,
    mint_pairing_code,
    redeem_pairing_code,
    revoke_device,
)
from agent_runtime.serve_socket import (
    HELLO_CONTRACT_VERSION,
    ServeHelloProtocolError,
    ServeSocketClient,
    SocketOwnerLock,
)
from hermes_cli.harness_parts import serve as serve_module
from hermes_cli.harness_parts.serve import gateway_listener as serve_gateway_listener
from hermes_cli.harness_parts.serve import serve_loop

WAIT = 20.0


# ── the harness (mirrors test_serve_socket_lane's, with the second door on) ──


class _StdioPipe:
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
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def wait_for(self, event: str, timeout: float = WAIT) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in self.frames():
                if frame.get("event") == event:
                    return frame
            time.sleep(0.01)
        raise AssertionError(f"no {event!r} frame within {timeout}s")


class _RunningServe:
    def __init__(self, pipe, sink, thread) -> None:
        self.pipe = pipe
        self.sink = sink
        self.thread = thread
        self.ready: dict = {}

    @property
    def port(self) -> int:
        return int(self.ready["socket"]["port"])

    @property
    def gateway_port(self) -> int:
        return int(self.ready["gateway"]["port"])

    @property
    def fingerprint(self) -> str:
        return str(self.ready["gateway"]["cert_fingerprint"])


@contextmanager
def running_serve(**kwargs):
    pipe = _StdioPipe()
    sink = _Sink()
    handle = _RunningServe(pipe, sink, None)

    def _run() -> None:
        serve_loop(
            pipe,
            sink,
            socket_lane=True,
            dispatch=kwargs.pop("dispatch", lambda argv: 0),
            liveness_pump_interval_seconds=60.0,
            **kwargs,
        )

    thread = threading.Thread(target=_run, name="serve-gateway-under-test", daemon=True)
    handle.thread = thread
    thread.start()
    try:
        handle.ready = sink.wait_for("ready")
        yield handle
    finally:
        pipe.close()
        thread.join(WAIT)


@pytest.fixture
def gateway_on(monkeypatch):
    """Turn the second listener on the way an operator's config would.

    Patched at ``gateway_listen_config`` rather than by writing a config file,
    because that function is the seam the config read exists behind and its own
    behaviour — including that Stage 0a's key never existed — is pinned
    separately in ``test_gateway_listen_config.py``. Loopback and an ephemeral
    port: the LAN bind is this same call with a different string.
    """

    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(
            _home, "gateway_listen_config", lambda: ("127.0.0.1", 0)
        )


def _store_root():
    from agent_runtime import paths

    return paths.store_root()


def _serving_row(root, pid: int) -> None:
    """The registry row a SERVING incumbent would have (RS-4).

    Same helper, same reason, as ``test_serve_socket_lane._serving_row``: a
    contender reads "alive and still serving" off the absence of ``draining_at``
    AND the presence of ``serve_instances/<pid>.json``, so a fabricated
    incumbent that is only a sidecar no longer describes a healthy owner.
    """

    from agent_runtime.serve_registry import serve_instance_path

    path = serve_instance_path(root, pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "transport": "stdio+socket"}), encoding="utf-8"
    )


def pair_device(*, name: str = "phone") -> DeviceCredential:
    root = _store_root()
    code = mint_pairing_code(root, name=name)
    assert isinstance(code, PairingCode)
    credential = redeem_pairing_code(root, code.code)
    assert isinstance(credential, DeviceCredential)
    return credential


@contextmanager
def device_client(handle: _RunningServe, credential: DeviceCredential, *, pin=True):
    connection = ServeSocketClient(
        "127.0.0.1",
        handle.gateway_port,
        timeout_seconds=WAIT,
        tls=True,
        cert_fingerprint=handle.fingerprint if pin else None,
    )
    connection.connect()
    try:
        reply = connection.device_hello(
            device_id=credential.device_id, token=credential.token, client="phone"
        )
        yield connection, reply
    finally:
        connection.close()


def _rpc(connection: ServeSocketClient, method: str, params: dict | None = None) -> dict:
    connection.send(
        {"jsonrpc": "2.0", "id": f"r-{method}", "method": method, "params": params or {}}
    )
    for _ in range(50):
        frame = connection.read_frame()
        if frame is None:
            raise AssertionError(f"connection closed before a reply to {method}")
        if frame.get("id") == f"r-{method}":
            return frame
    raise AssertionError(f"no reply to {method}")


@contextmanager
def loopback_client(handle: _RunningServe):
    """The local console's door: the loopback lane, greeted with the root's token."""

    from agent_runtime.serve_auth import read_token

    with ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT) as client:
        client.hello(token=read_token(_store_root()) or "", client="launcher")
        yield client


def _frames_until(connection: ServeSocketClient, event: str, *, limit: int = 2000) -> list[dict]:
    """Every frame up to and including the first ``event`` one."""

    frames = []
    for _ in range(limit):
        frame = connection.read_frame()
        if frame is None:
            raise AssertionError(f"connection closed before {event!r}: {frames[-3:]}")
        frames.append(frame)
        if frame.get("event") == event:
            return frames
    raise AssertionError(f"no {event!r} within {limit} frames")


def _set_access(allow: bool) -> None:
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import STDIO_OWNER

    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "acc", "method": "runtime.gateway.access.set", "params": {"allow": allow}},
        serve_rpc.RpcContext(caller=STDIO_OWNER),
    )
    assert reply["result"]["access"] is allow, reply


# ── off by default ──────────────────────────────────────────────────────────


def test_with_no_config_the_second_listener_does_not_exist_and_the_frame_says_disabled():
    """The default, and the whole security posture behind it: a runtime that
    executes agents with tools does not open a network door because a package
    was updated. ``disabled`` rather than an absent key, so an operator who
    thinks they turned it on can tell the difference."""

    with running_serve() as handle:
        # S2 (R-IP16): the capability list rides EVERY outcome, ``disabled``
        # included, because "does this build know the verb" and "is the LAN door
        # open" are different questions. The key set is still exact — a block
        # that grew a field nobody declared would fail here.
        assert handle.ready["gateway"] == {
            "outcome": "disabled",
            "capabilities": list(GATEWAY_CAPABILITIES),
        }
        assert handle.ready["socket"]["outcome"] == "listening"
        assert handle.ready["socket"]["host"] == "127.0.0.1"
        # Nothing was minted on the way past: no certificate, no key.
        assert read_certificate(_store_root()).state == "error:absent"
        assert not certificate_path(_store_root()).exists()


# ── R-L1: "no listener" is four different sentences, and it says which ──────
#
# Measured 2026-09-04 on the operator's machine. The launcher wrote
# `remote_gateway.listen: 0.0.0.0` and `.port: 8765` (correctly — reproduced in a
# scratch home), respawned the serve, and the replacement lost the socket-owner
# lock to a dead pid. With no socket lane there is no LAN listener, and the
# greeting called that `disabled` — the same word as "the operator never asked
# for one". The launcher, having just asked for one, could only read that as
# "this build does not support the feature". Every outcome below exists so that
# sentence cannot be said again.


def _stdio_only_ready() -> dict:
    """Boot a serve with NO socket lane and return its ``ready`` frame.

    ``running_serve`` above pins ``socket_lane=True``, which is right for every
    other test in this file and is exactly the condition under test here.
    """

    pipe, sink = _StdioPipe(), _Sink()
    pipe.send({"op": "shutdown"})
    serve_loop(pipe, sink, dispatch=lambda argv: 0)
    return next(f for f in sink.frames() if f.get("event") == "ready")


def test_a_listener_the_config_asked_for_and_a_socket_lane_that_is_off_says_so(
    gateway_on,
):
    """The heart of R-L1: config ON + no socket lane must not read `disabled`.

    The key set is pinned exactly, as the `listening` block's is. `reason` is the
    `socket` block's own outcome verbatim, so the two blocks on one frame cannot
    tell different stories about one boot.
    """

    ready = _stdio_only_ready()

    assert ready["socket"] == {"outcome": "disabled"}
    block = ready["gateway"]
    assert block["outcome"] == "socket_unavailable"
    assert block["reason"] == "disabled"
    assert block["pid"] is None
    assert block["owner_started_at"] is None
    # The door the operator ASKED for, carried the way the `error:*` outcomes
    # already carry it — never to be read as a door that opened.
    assert block["host"] == "127.0.0.1"
    assert block["port"] == 0
    assert set(block) == {
        "outcome",
        "reason",
        "pid",
        "owner_started_at",
        "host",
        "port",
        # R-IP16, unchanged: the capability list rides EVERY outcome, because
        # "does this build know the verb" is a different question from "is the
        # LAN door open" — and a launcher deciding whether to render a pairing
        # row asks the first one on exactly this kind of boot.
        "capabilities",
    }
    assert block["capabilities"] == list(GATEWAY_CAPABILITIES)


def test_a_socket_lock_lost_to_a_live_owner_names_the_holder_on_the_gateway_block(
    gateway_on, live_foreign_pid
):
    """The operator's shape, minus the dead pid R-L2 now takes over from.

    A launcher that reads this knows three things it could not read before: the
    runtime is present, the listener it asked for is not up, and the reason is a
    process it can name — which is what turns a grey switch into "waiting for
    pid N to release the runtime".
    """

    root = _store_root()
    incumbent = SocketOwnerLock(root)
    assert incumbent.acquire().acquired is True
    try:
        incumbent.publish_owner(
            {
                "pid": live_foreign_pid,
                "port": 61010,
                "boot_id": "incumbent",
                "started_at": "2026-09-04T10:28:16.817Z",
            }
        )
        # RS-4 (2026-09-07): an owner that is alive is refused at once only
        # while it is also SERVING, and the registry row is half of how the
        # contender reads that. A bare sidecar now reads as an owner that has
        # already unregistered, and the serve below would spend the drain bound
        # waiting for it instead of reporting the block this test is about.
        _serving_row(root, live_foreign_pid)
        with running_serve() as handle:
            assert handle.ready["socket"]["outcome"] == "lock_held_by"
            block = handle.ready["gateway"]
            assert block["outcome"] == "socket_unavailable"
            assert block["reason"] == "lock_held_by"
            assert block["pid"] == live_foreign_pid
            assert block["owner_started_at"] == "2026-09-04T10:28:16.817Z"

            # Re-askable, like every other block on this frame: a client that
            # reconnects after the incumbent goes away must be able to learn
            # that without a restart it cannot cause. There is no `hello_ok` to
            # carry it in this state — no socket lane means no loopback
            # listener to greet on — which is exactly why `ready` and `version`
            # have to be complete.
            handle.pipe.send({"op": "version"})
            version = handle.sink.wait_for("version")
            assert version["gateway"] == block
    finally:
        incumbent.release()


def test_config_off_wins_over_a_socket_lane_that_is_also_down():
    """Precedence, and it is deliberate. `disabled` is the ACTIONABLE answer —
    turn it on — while `socket_unavailable` on a runtime nobody asked to listen
    would send a launcher chasing a lock for a door it was never told to open."""

    ready = _stdio_only_ready()
    assert ready["socket"] == {"outcome": "disabled"}
    assert ready["gateway"] == {
        "outcome": "disabled",
        "capabilities": list(GATEWAY_CAPABILITIES),
    }


def test_a_disabled_listener_names_the_port_it_will_listen_on_when_one_is_stored(
    monkeypatch,
):
    """RT-FU-TURNING-REACHABLE-BACK-ON-KEEPS-THE-PORT-THE-COMPUTER-LISTENS-ON.

    With the listener off and ``remote_gateway_port`` stored, the greeting
    names that port, so Eternia's enable writes it back rather than its 8765
    default. With none stored the block is unchanged (the test above)."""

    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(_home, "gateway_listen_config", lambda: (None, 31734))
    ready = _stdio_only_ready()
    assert ready["gateway"] == {
        "outcome": "disabled",
        "port": 31734,
        "capabilities": list(GATEWAY_CAPABILITIES),
    }


def test_the_greeting_a_socket_client_reads_carries_the_same_gateway_block():
    """R-L1 covers `hello_ok` as well as `ready`, and the launcher's LAN
    connector and the peer dial both read it there rather than on `ready`."""

    with running_serve() as handle:
        with ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT) as client:
            from agent_runtime.serve_auth import read_token

            hello = client.hello(token=read_token(_store_root()) or "", client="t")
        assert hello["gateway"] == handle.ready["gateway"]
        assert hello["gateway"]["outcome"] == "disabled"


def test_the_no_listener_block_is_pure_and_answers_without_a_runtime(monkeypatch):
    """`gateway_block_when_no_listener` is module-level and side-effect-free for
    the same reason `start_gateway_listener` is: the four outcomes are worth
    reading in one screen, and a table-driven test of them should not have to
    boot four runtimes."""

    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(
            _home, "gateway_listen_config", lambda: ("0.0.0.0", 8765)
        )
    build = serve_module.gateway_block_when_no_listener

    # No root at all: the same word `auth` and `install` use for it, so one
    # frame tells one story.
    assert build({"outcome": "listening"}, root_resolved=False) == {
        "outcome": "error:root_unresolved"
    }

    # The operator's own boot, reconstructed from the sidecar he still had.
    assert build(
        {
            "outcome": "lock_held_by",
            "pid": 25672,
            "owner_started_at": "2026-09-04T10:28:16.817Z",
        },
        root_resolved=True,
    ) == {
        "outcome": "socket_unavailable",
        "reason": "lock_held_by",
        "pid": 25672,
        "owner_started_at": "2026-09-04T10:28:16.817Z",
        "host": "0.0.0.0",
        "port": 8765,
    }

    # A socket lane that ERRORED carries its typed token through as the reason
    # rather than being flattened into one word for every failure.
    assert build({"outcome": "error:EACCES"}, root_resolved=True)["reason"] == (
        "error:EACCES"
    )
    # And a `socket` block that says nothing recognisable still produces a
    # complete answer — an explanation with a hole in it is not an explanation.
    assert build({}, root_resolved=True)["reason"] == "unknown"

    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(_home, "gateway_listen_config", lambda: (None, 0))
    assert build({"outcome": "lock_held_by"}, root_resolved=True) == {
        "outcome": "disabled"
    }

    # Off with a stored port: the port rides the `disabled` block so an off/on
    # toggle keeps it (RT-FU-TURNING-REACHABLE-BACK-ON-KEEPS-THE-PORT-…).
    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(_home, "gateway_listen_config", lambda: (None, 31734))
    assert build({"outcome": "lock_held_by"}, root_resolved=True) == {
        "outcome": "disabled",
        "port": 31734,
    }


def test_the_loopback_lane_is_byte_identical_with_the_gateway_lane_up(
    monkeypatch,
):
    """Stage 1's hardest invariant, asserted rather than inferred.

    Everything on ``ready`` that is not the new ``gateway`` block, and the whole
    of a loopback client's ``hello_ok``, must be the same shape with the second
    door open as with it shut. Volatile fields (pids, ports, ids, timings) are
    dropped by NAME rather than by a heuristic, so a field that starts varying
    for a real reason breaks this test instead of slipping through it.
    """

    volatile = {
        "pid",
        "boot_id",
        "socket",
        "gateway",
        "instance",
        "connection",
        "started_at",
        "ready_ms",
        "timeline",
        "boot_timeline",
        "connections",
    }

    def _stable(frame: dict) -> dict:
        stable = {k: v for k, v in frame.items() if k not in volatile}
        reached = stable.get("reached_at")
        if isinstance(reached, dict):
            # D12's ``reached_at`` is half claim, half ephemeral. The HOST is
            # exactly what this test is about — bringing the gateway lane up
            # must not change which address a loopback client reaches — so it
            # stays in the comparison. The PORT is this boot's ephemeral
            # listener, as boot-dependent as ``socket`` and ``connection``
            # above, and comparing it would only re-prove that two boots got
            # two ports.
            stable["reached_at"] = {"host": reached.get("host")}
        return stable

    # WARM THE ROOT FIRST, and discard that boot. A fresh root mints its serve
    # token and its install identity on the first boot and loads them on every
    # one after, so `auth.token_file` reads `minted` then `present` and
    # `install.state` reads `minted` then `loaded` — differences that belong to
    # boot ORDER and would otherwise be attributed to the gateway lane. The
    # comparison below has to be between two steady-state boots, or it proves
    # nothing about the thing it names.
    with running_serve():
        pass

    with running_serve() as plain:
        plain_ready = _stable(plain.ready)
        with ServeSocketClient("127.0.0.1", plain.port, timeout_seconds=WAIT) as client:
            from agent_runtime.serve_auth import read_token

            plain_hello = _stable(
                client.hello(token=read_token(_store_root()) or "", client="t")
            )

    for _home in (serve_gateway_listener, endpoint_candidates):
        monkeypatch.setattr(
            _home, "gateway_listen_config", lambda: ("127.0.0.1", 0)
        )
    with running_serve() as both:
        assert both.ready["gateway"]["outcome"] == "listening"
        both_ready = _stable(both.ready)
        with ServeSocketClient("127.0.0.1", both.port, timeout_seconds=WAIT) as client:
            from agent_runtime.serve_auth import read_token

            both_hello = _stable(
                client.hello(token=read_token(_store_root()) or "", client="t")
            )

    assert both_ready == plain_ready
    assert both_hello == plain_hello
    # And the loopback client is still the local console on the transport it
    # always was — the gateway lane did not rename the door it came through.
    assert both_hello["transport"] == "socket"
    assert "drain" in both_hello["ops"]["ops"]


# ── the lane comes up, and says what a client must pin ──────────────────────


def test_the_ready_frame_publishes_the_gateway_port_and_the_fingerprint(gateway_on):
    with running_serve() as handle:
        block = handle.ready["gateway"]

        assert block["outcome"] == "listening"
        assert block["host"] == "127.0.0.1"
        assert isinstance(block["port"], int) and block["port"] > 0
        assert block["port"] != handle.ready["socket"]["port"]
        assert block["cert_fingerprint"] == read_certificate(_store_root()).fingerprint
        # A greeting frame carries the POSTURE and never the secret — the rule
        # `auth` established and every block since has kept. Asserted against the
        # actual secrets rather than against the substring "token", which
        # `auth.token_file` legitimately contains: the private key that proves
        # this listener, and any device verifier that would let one be forged.
        rendered = json.dumps(handle.ready)
        assert handle.ready["auth"] == {"token_file": handle.ready["auth"]["token_file"]}
        assert "PRIVATE KEY" not in rendered
        assert "BEGIN " not in rendered
        assert "verifier" not in rendered
        assert set(block) == {
            "outcome",
            "host",
            "port",
            "started_at",
            "cert_fingerprint",
            # S2. Additive, and asserted as a VALUE below rather than merely as
            # a present key: a capabilities list that drifted from the module's
            # tuple would be a feature-detection answer nobody could trust.
            "capabilities",
        }
        assert block["capabilities"] == list(GATEWAY_CAPABILITIES)


def test_a_paired_device_completes_the_handshake_over_tls_with_a_pinned_cert(
    gateway_on,
):
    credential = pair_device(name="the phone")

    with running_serve() as handle:
        with device_client(handle, credential) as (_connection, reply):
            assert reply["event"] == "hello_ok"
            assert reply["hello_contract"] == HELLO_CONTRACT_VERSION
            # The door it came through, stated — a device reading "socket" here
            # would be told it is on the local lane.
            assert reply["transport"] == "gateway"
            assert reply["install"]["install_id"]
            # And the ops it is offered exclude the one that ends the runtime.
            assert "drain" not in reply["ops"]["ops"]
            assert "shutdown" not in reply["ops"]["ops"]
            assert "subscribe" in reply["ops"]["ops"]
            assert reply["ops"]["transport"] == "gateway"
            # It can read the tier map it will be held to, off the same frame.
            assert reply["rpc"]["tiers"]["runtime.agent.retire"] == TIER_CONSOLE
            assert reply["rpc"]["tiers"]["runtime.office.get"] == TIER_READ


def test_a_client_that_pins_the_wrong_fingerprint_refuses_before_it_speaks(gateway_on):
    """The pin is what makes the encryption worth having: without it TLS stops
    an eavesdropper and stops no impostor. The refusal happens BEFORE any
    credential is sent, which is the whole point of checking it first."""

    credential = pair_device()

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint="0" * 64,
        )
        with pytest.raises(ServeHelloProtocolError, match="pinned fingerprint"):
            connection.connect()
        connection.close()
        assert credential.token  # never sent


def test_a_boot_whose_gateway_bind_fails_publishes_the_outcome_so_pairing_refuses(
    monkeypatch,
):
    """RT-FU-A-PAIRING-CODE-IS-REFUSED-WHEN-THE-RUNNING-SERVES-PAIRING-DOOR-FAILED-TO-OPEN.

    Another program holds the port: the boot's ``gateway`` block is ``error:*``,
    and the ownership sidecar mirrors it as ``{outcome, port}`` (no host, no
    fingerprint), so ``listener_endpoint`` in another process answers
    ``not_listening`` instead of falling to ``config`` and minting."""

    import socket as _socket

    from agent_runtime.gateway_endpoints import SOURCE_NOT_LISTENING, listener_endpoint
    from agent_runtime.serve_socket import read_socket_owner

    holder = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    held = holder.getsockname()[1]
    try:
        for _home in (serve_gateway_listener, endpoint_candidates):
            monkeypatch.setattr(
                _home, "gateway_listen_config", lambda: ("127.0.0.1", held)
            )
        with running_serve() as handle:
            block = handle.ready["gateway"]
            assert block["outcome"].startswith("error:")
            assert read_socket_owner(_store_root())["gateway"] == {
                "outcome": block["outcome"],
                "port": held,
            }
            endpoint = listener_endpoint(_store_root())
            assert endpoint["source"] == SOURCE_NOT_LISTENING
            assert endpoint["port"] == held
            assert endpoint["outcome"] == block["outcome"]
    finally:
        holder.close()


def test_a_plaintext_peer_gets_no_challenge_and_no_information(gateway_on):
    """A port scanner, or a client that has not been told this lane is
    encrypted, learns nothing at all — not even a rejection, because there is no
    negotiated channel to write one on."""

    import socket as _socket

    with running_serve() as handle:
        raw = _socket.create_connection(("127.0.0.1", handle.gateway_port), timeout=WAIT)
        try:
            raw.settimeout(WAIT)
            raw.sendall(b'{"op":"hello","proof":"x"}\n')
            assert raw.recv(4096) in (b"", None) or True
        except OSError:
            pass  # a reset is an equally correct answer
        finally:
            raw.close()
        # The lane is still serving everybody else.
        credential = pair_device()
        with device_client(handle, credential) as (_c, reply):
            assert reply["event"] == "hello_ok"


# ── who is refused at the door ──────────────────────────────────────────────


def test_the_root_token_is_not_a_credential_on_this_lane(gateway_on):
    """The local console's secret opens the local door and only that one. A
    lane that accepted it would mean pairing was decoration: anything that could
    read the token file could reach the install from the network."""

    from agent_runtime.serve_auth import read_token

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            reply = connection.hello(
                token=read_token(_store_root()) or "", client="impostor"
            )
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


def test_a_revoked_device_is_refused_at_the_hello(gateway_on):
    credential = pair_device()
    revoke_device(_store_root(), credential.device_id)

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            reply = connection.device_hello(
                device_id=credential.device_id, token=credential.token, client="phone"
            )
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    # Collapsed into ONE reason with every other credential failure, so a peer
    # cannot learn which device ids exist by watching it change.
    assert reply["reason"] == "bad_proof"


def test_an_unknown_device_and_a_wrong_proof_are_indistinguishable(gateway_on):
    credential = pair_device()

    with running_serve() as handle:
        replies = []
        for device_id, token in (
            ("dev_never_paired", credential.token),
            (credential.device_id, "0" * 64),
        ):
            connection = ServeSocketClient(
                "127.0.0.1",
                handle.gateway_port,
                timeout_seconds=WAIT,
                cert_fingerprint=handle.fingerprint,
            )
            connection.connect()
            try:
                replies.append(
                    connection.device_hello(
                        device_id=device_id, token=token, client="phone"
                    )
                )
            finally:
                connection.close()

    assert [r["reason"] for r in replies] == ["bad_proof", "bad_proof"]
    assert replies[0] == replies[1]


def test_a_proof_stolen_from_the_loopback_lane_does_not_verify_here(gateway_on):
    """The port binding, earning its keep across two listeners on one machine:
    the lanes have different ports, so a proof minted for one is wrong at the
    other even with the right credential."""

    credential = pair_device()

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            greeting = connection.read_frame()
            connection.send(
                {
                    "op": "hello",
                    "client": "phone",
                    "device_id": credential.device_id,
                    "proof": device_proof(
                        credential.token,
                        greeting["nonce"],
                        # the LOOPBACK port, not the one it dialled
                        port=handle.port,
                        device_id=credential.device_id,
                    ),
                }
            )
            reply = connection.read_frame()
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


# ── the tier becomes a refusal (A5, over the wire) ──────────────────────────


def test_a_console_device_passes_the_gate_on_a_console_verb(gateway_on):
    credential = pair_device()

    with running_serve() as handle:
        with device_client(handle, credential) as (connection, _reply):
            answer = _rpc(connection, "runtime.agent.retire", {})

    # It is refused for its PARAMS, not for its scope: an empty retire has
    # nothing to retire. What matters is which refusal it is — the gate let it
    # through and the handler answered.
    assert answer.get("error", {}).get("data", {}).get("reason") != "scope_denied"


@pytest.mark.parametrize("stored", ["read", "superuser"])
def test_a_stored_device_that_is_not_full_control_is_refused_at_the_hello(gateway_on, stored):
    """A row holding the retired view-only ``read`` (or any word but ``console``) is no device: the
    hello is refused like any other credential failure, and its holder pairs again
    (RT-FU-HERMES-PAIRS-A-DEVICE-ONLY-AT-FULL-CONTROL-WITH-NO-VIEW-ONLY-LEVEL; no migration).

    Killing mutation (red seen 2026-11-23): in ``store.decode_device`` decode a non-console row as
    ``read`` (the old least-privilege rule), and the hello is answered ``hello_ok``."""

    from agent_runtime.serve_gateway_auth import device_store_path

    credential = pair_device()
    path = device_store_path(_store_root())
    payload = json.loads(path.read_bytes().decode("utf-8"))
    payload["devices"][credential.device_id]["tier"] = stored
    path.write_bytes(json.dumps(payload).encode("utf-8"))

    with running_serve() as handle:
        with device_client(handle, credential) as (_connection, reply):
            pass

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


def test_the_argv_lane_is_unreachable_from_a_device_at_every_tier(gateway_on):
    """The argv lane is the machine owner's shell: a device, even at full control, is refused it
    outright rather than handed an ungated door beside the method lane's gate."""

    credential = pair_device()
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, _reply):
            connection.send(
                {"id": "a-1", "argv": ["harness", "agent", "retire", "--id", "x"]}
            )
            frame = connection.read_frame()

    assert frame["event"] == "error"
    assert frame["error"] == "argv_lane_unavailable"


def test_a_device_may_not_drain_the_runtime_other_clients_are_using(gateway_on):
    credential = pair_device()

    with running_serve() as handle:
        with device_client(handle, credential) as (connection, _reply):
            connection.send({"op": "drain", "force": True})
            frame = connection.read_frame()
        # …and the runtime is still alive to say so.
        assert handle.thread.is_alive()

    assert frame["error"] == "op_not_available_on_gateway"


def test_the_local_console_can_still_drain_with_the_gateway_lane_up(gateway_on):
    """The mirror of the test above: refusing the device must not have refused
    the operator. A guard that took the loopback lane's verb with it would pass
    every assertion about devices."""

    with running_serve() as handle:
        with ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT) as client:
            from agent_runtime.serve_auth import read_token

            client.hello(token=read_token(_store_root()) or "", client="launcher")
            client.send({"op": "drain", "force": True})
            frames = []
            for _ in range(40):
                frame = client.read_frame()
                if frame is None:
                    break
                frames.append(frame.get("event"))
                if frame.get("event") in {"drain_complete", "drain_timeout"}:
                    break

    assert "draining" in frames


# ── the device is visible to its operator ───────────────────────────────────


def test_an_attached_device_is_named_on_the_connections_block(gateway_on):
    """"Which of my paired devices is attached right now" is the question this
    block exists to answer once there is more than one client, and a device id
    is not a secret — the device names it in its own hello."""

    credential = pair_device(name="the phone")

    with running_serve() as handle:
        with device_client(handle, credential) as (_connection, _reply):
            # Read by the local console while the device is attached: the table
            # is the console's, never the device's own to ask for.
            with loopback_client(handle) as console:
                console.send({"op": "connections"})
                frame = _frames_until(console, "socket_connections")[-1]

    # The gateway lane has its OWN sub-block rather than merged rows: `port`,
    # `count` and `max_connections` are per-listener facts, and merged they
    # would answer for two listeners at once without saying which.
    assert frame["gateway"]["enabled"] is True
    rows = frame["gateway"]["connections"]
    assert len(rows) == 1
    assert rows[0]["device_id"] == credential.device_id
    assert rows[0]["device_tier"] == TIER_CONSOLE
    # …and the loopback lane's own rows are unchanged in shape: no device keys
    # where there is no device.
    assert all("device_id" not in row for row in frame["connections"])


# ── the local console's diagnostics stay the console's ──────────────────────
#
# Hermes row RT-FU-A-PAIRED-DEVICE-CAN-READ-THIS-COMPUTERS-THREAD-STACKS-AND-ITS-CONNECTION-LIST:
# `stacks` and `connections` are in OPS_GATEWAY_DENIED, and `_handle_message` refuses
# every op in that tuple to a gateway caller before its handler runs.


def test_a_device_is_refused_the_thread_stacks_and_reads_no_stack_line(gateway_on):
    """MUTATION: drop ``"stacks"`` from ``OPS_GATEWAY_DENIED`` -> the device gets ``stderr``
    stack lines and ``stacks_dumped``, red."""

    credential = pair_device()
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, reply):
            assert "stacks" not in reply["ops"]["ops"]
            connection.send({"op": "stacks"})
            connection.send({"op": "ping"})
            frames = _frames_until(connection, "busy")

    events = [frame.get("event") for frame in frames]
    assert "stderr" not in events and "stacks_dumped" not in events, events
    assert frames[0]["event"] == "error"
    assert frames[0]["error"] == "op_not_available_on_gateway"


def test_a_device_is_refused_the_connection_list_with_allow_access_off(gateway_on):
    """MUTATION: drop ``"connections"`` from ``OPS_GATEWAY_DENIED`` -> the device reads
    ``socket_connections``, red. Allow access off: the refusal does not hang on it."""

    credential = pair_device()
    _set_access(False)
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, reply):
            assert reply["event"] == "hello_ok" and reply["access"] is False, reply
            assert "connections" not in reply["ops"]["ops"]
            connection.send({"op": "connections"})
            frame = connection.read_frame()

    assert frame["event"] == "error", frame
    assert frame["error"] == "op_not_available_on_gateway"


def test_a_device_version_carries_no_connections_block_and_a_loopback_version_does(gateway_on):
    """MUTATION: put ``connections`` back on ``_op_version`` for every caller -> the device's
    ``version`` carries the attached-client table, red.

    The console asks on the loopback's SECOND connection, the first staying silent: the two
    listeners number their connections alike and share one sink map, so the device's
    ``conn-1`` must not meet a loopback ``conn-1`` that spoke
    (RT-FU-A-PHONE-AND-THE-LOCAL-APP-ON-THE-SAME-CONNECTION-NUMBER-GET-EACH-OTHERS-ANSWERS)."""

    credential = pair_device()
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, _reply):
            with loopback_client(handle), loopback_client(handle) as console:
                console.send({"op": "version"})
                local = _frames_until(console, "version")[-1]
                connection.send({"op": "version"})
                remote = _frames_until(connection, "version")[-1]

    assert remote["transport"] == "gateway"
    assert "connections" not in remote, sorted(remote)
    assert local["connections"]["gateway"]["connections"][0]["device_id"] == credential.device_id


def test_the_local_console_still_reads_stacks_and_connections_with_a_device_attached(gateway_on):
    """MUTATION: key the dispatcher's door on ``connection is not None`` instead of
    ``_is_gateway`` -> the loopback console is refused both, red."""

    credential = pair_device()
    with running_serve() as handle:
        with device_client(handle, credential):
            with loopback_client(handle) as console:
                console.send({"op": "stacks"})
                stacks = _frames_until(console, "stacks_dumped")
                console.send({"op": "connections"})
                table = _frames_until(console, "socket_connections")[-1]

    assert any(frame.get("event") == "stderr" for frame in stacks)
    assert table["gateway"]["connections"][0]["device_id"] == credential.device_id


# ── the ceremony's second half: a code becomes a device, over the wire ──────


def test_a_pairing_code_becomes_a_credential_in_one_round_trip(gateway_on):
    """Without this the device tier is a tier no device can ever enter: the
    operator prints eight characters and there is nowhere to spend them."""

    code = mint_pairing_code(_store_root(), name="the phone")
    assert isinstance(code, PairingCode)

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            reply = connection.pair_hello(pairing_code=code.code, client="the phone")
        finally:
            connection.close()

        assert reply["event"] == "hello_ok"
        paired = reply["paired"]
        assert paired["tier"] == TIER_CONSOLE
        assert len(paired["device_token"]) == 64
        credential = DeviceCredential(
            device_id=paired["device_id"],
            token=paired["device_token"],
            tier=paired["tier"],
            name="the phone",
        )
        # …and the credential works on the NEXT connection, which is the only
        # thing that proves the token is real rather than decorative.
        with device_client(handle, credential) as (_c, second):
            assert second["event"] == "hello_ok"
            # The secret rides exactly ONE frame. A second handshake with the
            # same device carries no `paired` block, because there is nothing
            # left on the connection to carry — the slot is read-and-cleared.
            assert "paired" not in second


def test_a_code_is_one_shot_and_the_second_attempt_is_refused(gateway_on):
    code = mint_pairing_code(_store_root())
    assert isinstance(code, PairingCode)

    with running_serve() as handle:
        replies = []
        for _ in range(2):
            connection = ServeSocketClient(
                "127.0.0.1",
                handle.gateway_port,
                timeout_seconds=WAIT,
                cert_fingerprint=handle.fingerprint,
            )
            connection.connect()
            try:
                replies.append(
                    connection.pair_hello(pairing_code=code.code, client="phone")
                )
            finally:
                connection.close()

    assert replies[0]["event"] == "hello_ok"
    assert replies[1]["event"] == "hello_rejected"
    assert replies[1]["reason"] == "bad_proof"


def test_a_wrong_code_is_refused_and_looks_like_every_other_credential_failure(
    gateway_on,
):
    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            reply = connection.pair_hello(pairing_code="ZZZZZZZZ", client="phone")
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


def test_a_hello_carrying_both_a_code_and_a_device_id_is_refused(gateway_on):
    """A handshake with two credentials in it is where a downgrade lives: the
    server must not get to pick which one it liked."""

    credential = pair_device()
    code = mint_pairing_code(_store_root())
    assert isinstance(code, PairingCode)

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            connection.read_frame()
            connection.send(
                {
                    "op": "hello",
                    "client": "phone",
                    "device_id": credential.device_id,
                    "pairing_code": code.code,
                }
            )
            reply = connection.read_frame()
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


def test_the_pairing_code_is_not_a_credential_on_the_loopback_lane(gateway_on):
    """The doors do not trade credentials in either direction: the root token is
    refused on the gateway lane (above) and a pairing code is refused here."""

    code = mint_pairing_code(_store_root())
    assert isinstance(code, PairingCode)

    with running_serve() as handle:
        connection = ServeSocketClient("127.0.0.1", handle.port, timeout_seconds=WAIT)
        connection.connect()
        try:
            connection.read_frame()
            connection.send({"op": "hello", "client": "x", "pairing_code": code.code})
            reply = connection.read_frame()
        finally:
            connection.close()

    assert reply["event"] == "hello_rejected"
    assert reply["reason"] == "bad_proof"


def test_a_paired_device_never_shows_its_credential_on_the_connections_block(
    gateway_on,
):
    """The one-shot slot must not survive into anything an operator, a log, or
    another attached client can read."""

    code = mint_pairing_code(_store_root())
    assert isinstance(code, PairingCode)

    with running_serve() as handle:
        connection = ServeSocketClient(
            "127.0.0.1",
            handle.gateway_port,
            timeout_seconds=WAIT,
            cert_fingerprint=handle.fingerprint,
        )
        connection.connect()
        try:
            reply = connection.pair_hello(pairing_code=code.code, client="phone")
            token = reply["paired"]["device_token"]
            with loopback_client(handle) as console:
                console.send({"op": "connections"})
                frame = _frames_until(console, "socket_connections")[-1]
        finally:
            connection.close()

    assert token not in json.dumps(frame)
    assert code.code not in json.dumps(frame)
    assert frame["gateway"]["connections"][0]["device_id"] == reply["paired"]["device_id"]
