"""h-pool-starve: a chat turn never queues behind requests parked on a snapshot build,
a re-sent turn runs one handler, and a cold snapshot worker answers or is given up
in seconds.

Live case (2026-10-06 12:04, base agent.log): the boot build's worker (generation 1)
never answered and was given up at the 120 s timeout; four ``harness stream``
hydrates parked on that build held the four pool workers, Neko turn ``b00deebf``
queued 24 s (``queue_ms=24111``), the launcher re-sent it, and the original then ran
a second handler (anchored 12:04:47.297 beside the re-send's 12:04:45.700).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import turn_activity
from agent_runtime.snapshot_worker import child as child_mod
from agent_runtime.snapshot_worker import executor as executor_mod
from agent_runtime.snapshot_worker import peer as peer_mod
from agent_runtime.snapshot_worker.peer import SnapshotPeer
from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
from hermes_cli.harness_parts.serve.lanes import ArgvLanes, submit_accepted
from hermes_cli.harness_parts.serve.request_pool import RequestPool, TurnClaims

_REPO = Path(__file__).resolve().parents[2]


def _messages(caplog, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def _fields(message: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in message.split() if "=" in token)


# ── the cold worker: a grandchild never inherits the request pipe ─────────────

_GRANDCHILD_PROBE = r"""
import subprocess, sys
from agent_runtime.snapshot_worker.entry import own_protocol_pipes
requests, replies = own_protocol_pipes()
try:
    out = subprocess.run([sys.executable, "-c", "import sys; sys.stdout.write(repr(sys.stdin.read()))"],
                         capture_output=True, text=True, timeout=4).stdout
except subprocess.TimeoutExpired:
    out = "timeout"
replies.write((out + "\n").encode())
replies.flush()
"""


@pytest.mark.timeout(60)
def test_a_build_subprocess_never_inherits_the_workers_request_pipe():
    """A grandchild reads the null device, not the open request pipe (which never
    ends while the serve lives): its stdin read returns at once."""

    process = subprocess.Popen(
        [sys.executable, "-c", _GRANDCHILD_PROBE], cwd=str(_REPO),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        started = time.monotonic()
        line = process.stdout.readline().decode().strip()
        elapsed = time.monotonic() - started
    finally:
        process.stdin.close()
        process.wait(timeout=20)
    assert line == "''", f"the grandchild read {line!r} from its stdin"
    assert elapsed < 30


# ── the cold worker: silent or idle is given up in seconds ────────────────────

_SILENT_CHILD = "import time; time.sleep(60)"

_IDLE_CHILD = r"""
import json, sys, time
out = sys.stdout.buffer
out.write(json.dumps({"jsonrpc": "2.0", "method": "snapshot.ready", "params": {}}).encode() + b"\n"); out.flush()
frame = json.loads(sys.stdin.buffer.readline())
while True:
    beat = {"jsonrpc": "2.0", "method": "snapshot.beat", "params": {"idle_s": {frame["id"]: 99.0}}}
    out.write(json.dumps(beat).encode() + b"\n"); out.flush()
    time.sleep(0.1)
"""


def _peer_of(script: str) -> SnapshotPeer:
    process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return SnapshotPeer(process)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("script, reason", [(_SILENT_CHILD, "silent"), (_IDLE_CHILD, "idle")],
                         ids=["no_handshake", "idle_request"])
def test_a_silent_cold_worker_falls_back_within_the_new_bound(monkeypatch, caplog, tmp_path, script, reason):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(peer_mod, "HANDSHAKE_SECONDS", 1.0)
    monkeypatch.setattr(peer_mod, "IDLE_SECONDS", 1.0)
    peers: list[SnapshotPeer] = []
    binding = executor_mod.WorkerBinding(tmp_path, start=lambda home: peers.append(_peer_of(script)) or peers[-1],
                                          timeout=20.0)
    started = time.monotonic()
    try:
        assert binding.build() is None
        elapsed = time.monotonic() - started
    finally:
        binding.close()
        for peer in peers:
            peer.process.kill()
    assert elapsed < 10, f"gave up after {elapsed:.1f} s; the outer bound is {binding.timeout:.0f} s"
    lost = _messages(caplog, "snapshot_worker op=lost ")
    assert lost and _fields(lost[0])["reason"] == reason, lost
    assert _fields(lost[0])["fallback"] == "in_process"


def test_the_worker_beats_a_parked_request_as_idle_and_a_working_one_as_not(monkeypatch):
    """The child's progress signal: a request thread that burns no CPU is idle."""

    monkeypatch.setattr(child_mod, "BEAT_SECONDS", 0.1)
    release = threading.Event()

    def parked(_params):
        release.wait(10)
        return {"core": {}, "receipts": []}

    def working(_params):
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and not release.is_set():
            sum(range(2000))
        return {"core": {}, "receipts": []}

    monkeypatch.setitem(child_mod._HANDLERS, "parked", parked)
    monkeypatch.setitem(child_mod._HANDLERS, "working", working)
    request_r, request_w = os.pipe()
    reply_r, reply_w = os.pipe()
    requests, replies = os.fdopen(request_r, "rb"), os.fdopen(reply_w, "wb", buffering=0)
    server = threading.Thread(target=child_mod.serve, args=(requests, replies), daemon=True)
    server.start()
    feed = os.fdopen(request_w, "wb", buffering=0)
    for rid in ("parked", "working"):
        feed.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": rid, "params": {}}).encode() + b"\n")
    frames = os.fdopen(reply_r, "rb")
    seen: dict[str, float] = {"parked": 0.0, "working": 0.0}
    ready = False
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = json.loads(frames.readline())
            ready = ready or frame.get("method") == "snapshot.ready"
            idle = (frame.get("params") or {}).get("idle_s") or {}
            for rid in seen:
                seen[rid] = max(seen[rid], float(idle.get(rid, 0.0)))
            if seen["parked"] >= 1.0:
                break
    finally:
        release.set()
        feed.close()
        frames.close()
    assert ready, "no snapshot.ready before the beats"
    assert seen["parked"] >= 1.0, seen
    assert seen["working"] < 1.0, seen


# ── the pool: a chat turn has a lane the parked riders cannot take ────────────


def _session(dispatch, pool):
    frames: list = []
    session = SimpleNamespace(
        inflight_lock=threading.RLock(), inflight={}, inflight_futures={}, drain_state=None,
        pool=pool, turn_claims=TurnClaims(),
        frames=SimpleNamespace(emit=frames.append), dispatch=dispatch,
        serve_request_home=None, read_cache=None,
        stdout_proxy=SimpleNamespace(flush_request=lambda rid: None),
        stderr_proxy=SimpleNamespace(flush_request=lambda rid: None),
        _owner_of=lambda connection: "stdio",
        _bind_launcher_link=lambda request, sink: None,
    )
    for name in ("_run", "_execute_request", "_dispatch_guarded", "_reply_exit", "_refuse_duplicate_turn"):
        setattr(session, name, getattr(ArgvLanes, name).__get__(session))
    return session, frames


@pytest.mark.timeout(60)
def test_four_parked_riders_do_not_delay_a_chat_turns_anchor(caplog):
    caplog.set_level(logging.INFO, logger=turn_activity.__name__)
    build_done = threading.Event()
    anchored = threading.Event()
    parked = threading.Semaphore(0)

    def dispatch(argv):
        if argv[1] == "stream":  # a hydrate rider, parked on a snapshot build
            parked.release()
            build_done.wait(30)
            return 0
        with turn_activity.admitted_turn():
            anchored.set()
        return 0

    pool = RequestPool(4)
    session, _frames = _session(dispatch, pool)
    try:
        for index in range(4):
            submit_accepted(pool, session._run, _ArgvRequest(f"ride-{index}", ["harness", "stream"]))
        for _ in range(4):
            assert parked.acquire(timeout=10), "a rider never reached a worker"
        ArgvLanes._spawn_chat_turn(
            session, SimpleNamespace(emit=_frames.append), None, "chat-turn-1",
            ["harness", "mission-chat", "message", "--client-message-id", "m-1"], "",
        )
        assert anchored.wait(5), "the chat turn queued behind the parked riders"
    finally:
        build_done.set()
        pool.shutdown(wait=True)
    receipt = _messages(caplog, "chat_turn_accept_to_anchor request=chat-turn-1 ")
    assert receipt and int(_fields(receipt[0])["queue_ms"]) < 1000, receipt


# ── one turn, one handler ─────────────────────────────────────────────────────


@pytest.mark.timeout(60)
def test_a_re_sent_turn_runs_one_handler(caplog):
    caplog.set_level(logging.INFO)
    first_running = threading.Event()
    finish = threading.Event()
    handlers: list[str] = []

    def dispatch(argv):
        handlers.append(argv[-1])
        first_running.set()
        finish.wait(10)
        return 0

    pool = RequestPool(4)
    session, frames = _session(dispatch, pool)
    argv = ["harness", "mission-chat", "message", "--message", "hi", "--client-message-id", "send-b00d"]
    try:
        # The launcher's re-send (argv lane) reaches a worker first ...
        resend = _ArgvRequest("req-9", argv + ["resend"])
        submit_accepted(pool, session._run, resend)
        assert first_running.wait(5)
        # ... and the original method-lane presentation reaches one while it runs.
        original = _ArgvRequest("chat-8920", argv + ["original"])
        session._run(original)
    finally:
        finish.set()
        pool.shutdown(wait=True)
    assert handlers == ["resend"], handlers
    refused = [f for f in frames if f.get("id") == "chat-8920" and f.get("event") == "error"]
    assert refused and refused[0]["error"] == "chat_turn_duplicate_in_flight"
    exits = [f for f in frames if f.get("id") == "chat-8920" and f.get("event") == "exit"]
    assert exits and exits[0]["code"] == 2
    receipt = _messages(caplog, "chat_turn_duplicate_refused ")
    assert receipt and _fields(receipt[0])["twin"] == "req-9"
    # The claim ends with its turn: a later presentation is the journal's to answer.
    finish.set()
    later_pool = RequestPool(1)
    session.pool = later_pool
    try:
        session._run(_ArgvRequest("req-10", argv + ["later"]))
    finally:
        later_pool.shutdown(wait=True)
    assert handlers == ["resend", "later"]
