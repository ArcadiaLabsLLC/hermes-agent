"""The resident snapshot worker (plan snapshot-offproc S2) and the build accounting.

* a real worker's core equals the in-process core, and it projects the SERVE's
  runtime resolution, not its own environment's;
* a worker that dies mid-request, hangs, or keeps dying never loses a build: the
  request is built in process, every rider is released once, a receipt says so;
* every build receipt carries ``reason``, ``executor``, ``turns`` and
  ``worker_pid`` before ``pid``; the shadow build has its own receipt;
* ``observe snapshot-builds`` derives its numbers from those receipts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

from agent_runtime import snapshot as snapshot_mod
from agent_runtime import turn_activity
from agent_runtime.core_cache.shadow import compare_cores
from agent_runtime.resolution import resolve_runtime, runtime_resolution_scope
from agent_runtime.serde import to_jsonable
from agent_runtime.snapshot_build_census import census_builds, parse_duration
from agent_runtime.snapshot_worker import executor as executor_mod
from agent_runtime.snapshot_worker.peer import WorkerLoss, WorkerLost
from agent_runtime.store import WorkspaceStore
from tests._downstream import _seams

_PAIR_KEYS = ("reason", "executor", "turns", "worker_pid", "pid")


@pytest.fixture(autouse=True)
def _fresh_process_state():
    _seams.reset_core_cache_process_state()
    with snapshot_mod._BUILD_COALESCE:
        snapshot_mod._build_coalesce_state.update(running=False, result=None, waiters=0, started=0, done=0)
    executor_mod.unbind()
    yield
    executor_mod.unbind()
    _seams.reset_core_cache_process_state()


def _home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def _messages(caplog, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def _fields(message: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in message.split() if "=" in token)


def _canonical(core: dict) -> str:
    """The core minus the clock fields of the build itself (plan S2 control i): when it
    was generated, what it cost, and when its watermark and freshness were read."""

    data = json.loads(json.dumps(to_jsonable(core)))
    data.pop("generated_at", None)
    parity = data.get("parity") or {}
    for key in ("build_ms", "sections_ms", "generated_at", "projection_age_ms"):
        parity.pop(key, None)
    (parity.get("watermark") or {}).pop("captured_at", None)
    (parity.get("freshness") or {}).pop("generated_at", None)
    return json.dumps(data, sort_keys=True)


def _differing(left, right, path="") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        return [p for key in sorted(set(left) | set(right))
                for p in _differing(left.get(key), right.get(key), f"{path}.{key}")]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [p for i, (a, b) in enumerate(zip(left, right)) for p in _differing(a, b, f"{path}[{i}]")]
    return [] if left == right else [f"{path}: {str(left)[:80]} != {str(right)[:80]}"]


# ── the real worker ───────────────────────────────────────────────────────────


@pytest.mark.timeout(240)
def test_worker_core_equals_in_process_core_under_the_serves_resolution(tmp_path, monkeypatch):
    for index in range(3):
        WorkspaceStore().create(name=f"golden {index}", workspace_id=f"ws_golden_{index}")
    served = resolve_runtime()
    # The worker's own environment now names an EMPTY store: only the resolution
    # the serve sends with the request can make it project the seeded one.
    elsewhere = tmp_path / "agent-runtime-probe-elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(elsewhere))
    binding = executor_mod.WorkerBinding(_home())
    try:
        with runtime_resolution_scope(served):
            in_process = snapshot_mod.build._build_snapshot_uncoalesced()
            execution = binding.build()
    finally:
        binding.close()
    assert execution is not None and execution.executor == "worker"
    assert execution.worker_pid and execution.worker_pid != os.getpid()
    ids = {row.get("id") for row in execution.core.get("workspaces") or []}
    assert {"ws_golden_0", "ws_golden_1", "ws_golden_2"} <= ids
    assert compare_cores(in_process, execution.core) is None
    assert execution.core["runtime_paths_diagnostic"] == to_jsonable(in_process)["runtime_paths_diagnostic"]
    assert _canonical(execution.core) == _canonical(in_process), _differing(
        json.loads(_canonical(execution.core)), json.loads(_canonical(in_process)))


@pytest.mark.timeout(240)
def test_running_work_is_the_serves_not_the_workers(monkeypatch):
    """Its live lanes read the in-memory registries of the process that owns the
    work; the worker owns none, so the section must be the serve's."""

    from agent_runtime.snapshot import sections

    def serve_side(accountant):
        accountant.consider(2)
        accountant.include(1)
        return {"marker": f"serve-{os.getpid()}", "rows": [], "sources": {}}

    monkeypatch.setattr(sections, "build_running_work", serve_side)
    binding = executor_mod.WorkerBinding(_home())
    try:
        execution = binding.build()
    finally:
        binding.close()
    assert execution.core["running_work"]["marker"] == f"serve-{os.getpid()}"
    in_process = snapshot_mod.build._build_snapshot_uncoalesced()
    assert (execution.core["parity"]["completeness"]["running_work"]
            == to_jsonable(in_process)["parity"]["completeness"]["running_work"])


@pytest.mark.timeout(240)
def test_a_worker_killed_mid_request_falls_back_in_process(caplog):
    caplog.set_level(logging.INFO)
    binding = executor_mod.WorkerBinding(_home())
    peer = binding._live_peer()
    killer = threading.Timer(0.5, peer.process.kill)
    killer.start()
    try:
        assert binding.build() is None  # the cold build cannot answer in 0.5 s
    finally:
        killer.cancel()
        binding.close()
    lost = _messages(caplog, "snapshot_worker op=lost ")
    assert lost and _fields(lost[0])["reason"] == "exited", lost
    assert _fields(lost[0])["fallback"] == "in_process"


# ── fallback through the coalescer (fake peers) ──────────────────────────────


class _FakePeer:
    def __init__(self, *, loss: WorkerLoss | None = None, delay: float = 0.0, pid: int = 4242):
        self.loss, self.delay, self.pid = loss, delay, pid
        self.alive = True
        self.calls = 0
        self.process = self

    def kill(self):
        self.alive = False

    def close(self):
        self.alive = False

    def build(self, params, *, timeout):
        self.calls += 1
        assert params["serve_pid"] == os.getpid()
        assert params["resolution"]["store_root"]
        time.sleep(self.delay)
        if self.loss is not None:
            raise WorkerLost(self.loss)
        return {"core": {"parity": {"build_ms": 7, "watermark": {"event_offset": 3}}, "from": "worker"},
                "receipts": [{"logger": "agent_runtime.snapshot.context", "level": logging.INFO,
                              "message": f"snapshot_agents_readiness walk_ms=1 tool_visibility_ms=2 pid={os.getpid()}"}],
                "worker_pid": self.pid}


def _bind_fake(monkeypatch, peer_factory):
    monkeypatch.setattr("agent_runtime.snapshot_worker.worker.subprocess_worker_enabled", lambda: True)
    assert executor_mod.bind(_home(), start=lambda home: peer_factory())


def _in_process_core():
    return {"parity": {"build_ms": 5, "watermark": {"event_offset": 9}}, "from": "in_process"}


def test_lost_worker_builds_in_process_and_releases_every_rider_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced",
                        lambda: calls.append(1) or _in_process_core())
    _bind_fake(monkeypatch, lambda: _FakePeer(loss=WorkerLoss.EXITED, delay=0.4))
    results: dict[str, tuple] = {}

    def run(name, **kwargs):
        info = {"caller": name, "reason": "demote"}
        results[name] = (snapshot_mod.build_snapshot(build_info=info, **kwargs), info)

    lead = threading.Thread(target=run, args=("hub",))
    lead.start()
    time.sleep(0.1)
    rider = threading.Thread(target=run, args=("cli",), kwargs={"accept_inflight": True})
    rider.start()
    lead.join(10)
    rider.join(10)
    assert not lead.is_alive() and not rider.is_alive()
    assert results["hub"][0]["from"] == "in_process" and results["cli"][0]["from"] == "in_process"
    assert results["hub"][1]["role"] == "led" and results["cli"][1]["role"] == "rode"
    assert calls == [1]
    core = _messages(caplog, "snapshot_build_core ")
    assert len(core) == 1 and _fields(core[0])["executor"] == "in_process"
    assert _fields(_messages(caplog, "snapshot_worker op=lost ")[0])["reason"] == "exited"


def test_a_worker_build_is_logged_as_worker_with_its_receipts_forwarded(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    from agent_runtime import snapshot_build_ledger

    _bind_fake(monkeypatch, lambda: _FakePeer(delay=0.05))
    info = {"caller": "hub", "reason": "demote"}
    started = time.monotonic()
    core = snapshot_mod.build_snapshot(build_info=info)
    assert core["from"] == "worker" and info["role"] == "led"
    # ruling R6: the ledger span is the serve's wait, so a turn overlapping a
    # worker build still counts it in ``builds_overlapped``.
    assert snapshot_build_ledger.overlapping_builds(start=started + 0.01, end=started + 0.02) >= 1
    messages = [r.getMessage() for r in caplog.records]
    readiness = [i for i, m in enumerate(messages) if m.startswith("snapshot_agents_readiness ")]
    receipt = [i for i, m in enumerate(messages) if m.startswith("snapshot_build_core ")]
    assert readiness and receipt and readiness[0] < receipt[0]  # the build's receipts precede its line
    fields = _fields(messages[receipt[0]])
    assert fields["executor"] == "worker" and fields["worker_pid"] == "4242"
    assert fields["pid"] == str(os.getpid())


def test_a_hung_worker_is_discarded_and_respawned_then_retired(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced", _in_process_core)
    spawned = []

    def factory():
        spawned.append(_FakePeer(loss=WorkerLoss.TIMEOUT, pid=100 + len(spawned)))
        return spawned[-1]

    _bind_fake(monkeypatch, factory)
    for _ in range(executor_mod.RESPAWN_LIMIT + 3):
        assert executor_mod.execute_build().executor == "in_process"
    assert len(spawned) == executor_mod.RESPAWN_LIMIT + 1
    assert executor_mod.bound_binding().retired
    assert len(_messages(caplog, "snapshot_worker op=retired ")) == 1


def test_a_build_error_keeps_the_worker(monkeypatch):
    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced", _in_process_core)
    spawned = []
    _bind_fake(monkeypatch, lambda: spawned.append(_FakePeer(loss=WorkerLoss.BUILD_ERROR)) or spawned[-1])
    executor_mod.execute_build()
    executor_mod.execute_build()
    assert len(spawned) == 1 and spawned[0].calls == 2


def test_switch_off_starts_no_worker(monkeypatch):
    monkeypatch.setattr("agent_runtime.snapshot_worker.worker.subprocess_worker_enabled", lambda: False)
    started = []
    assert executor_mod.bind(_home(), start=started.append) is False
    assert executor_mod.bound_binding() is None and not started
    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced", _in_process_core)
    assert executor_mod.execute_build().executor == "in_process"


def test_the_switch_follows_conversations_by_default(monkeypatch):
    from agent_runtime.snapshot_worker import worker

    seen = {}

    def switch(*keys, default=True):
        seen[keys] = default
        return default

    monkeypatch.setattr("hermes_cli.config.config_switch", switch)
    monkeypatch.setattr("agent_runtime.conversations.worker.subprocess_worker_enabled", lambda: False)
    assert worker.subprocess_worker_enabled() is False
    assert seen[("snapshot", "subprocess_worker")] is False


# ── the receipts ──────────────────────────────────────────────────────────────


def test_build_receipt_names_trigger_executor_and_overlapped_turns(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def build_during_a_second_turn():
        with turn_activity.admitted_turn(turn_id="turn-mid"):
            pass
        return _in_process_core()

    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced", build_during_a_second_turn)
    args = Namespace(client_message_id=None)
    with turn_activity.admitted_turn(turn_id=lambda: args.client_message_id):
        args.client_message_id = "turn-early"  # minted after admission, read at receipt time
        snapshot_mod.build_snapshot(build_info={"caller": "hub", "reason": "demote"})
    message = _messages(caplog, "snapshot_build_core ")[0]
    assert message.endswith(f"reason=demote executor=in_process turns=turn-early,turn-mid "
                            f"worker_pid=- pid={os.getpid()}"), message
    assert [key for key in _fields(message) if key in _PAIR_KEYS] == list(_PAIR_KEYS)


def test_shadow_build_has_its_own_receipt(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(snapshot_mod.build, "_build_snapshot_uncoalesced", _in_process_core)
    assert snapshot_mod.build._shadow_build("prewarm")["from"] == "in_process"
    (line,) = _messages(caplog, "snapshot_build_shadow ")
    fields = _fields(line)
    assert (fields["caller"], fields["reason"], fields["executor"], fields["build_ms"]) == (
        "prewarm", "shadow", "in_process", "5")
    assert not _messages(caplog, "snapshot_build_core ")


def test_turn_watch_caps_ids_and_counts_the_rest():
    entries = [turn_activity.admitted_turn(turn_id=f"t{i}") for i in range(turn_activity.TURN_IDS_SHOWN + 2)]
    for entry in entries:
        entry.__enter__()
    try:
        with turn_activity.turn_overlap_watch() as watch:
            pass
    finally:
        for entry in reversed(entries):
            entry.__exit__(None, None, None)
    assert watch.receipt_value().endswith(",+2")
    with turn_activity.turn_overlap_watch() as quiet:
        pass
    assert quiet.receipt_value() == "-"


# ── the summary verb ──────────────────────────────────────────────────────────

_FIXTURE_LOG = """\
2026-10-06 09:00:00,001 INFO agent_runtime.snapshot.context: snapshot_build_core role=led caller=prewarm generation=1 build_ms=15000 offset=10 sections_top=a:1 pid=7
2026-10-06 10:00:00,001 INFO agent_runtime.snapshot.context: snapshot_build_core role=led caller=prewarm generation=1 build_ms=16000 offset=10 sections_top=a:1 reason=boot executor=worker turns=- worker_pid=9 pid=7
2026-10-06 10:00:05,001 INFO agent_runtime.snapshot.context: snapshot_build_shadow caller=hub reason=shadow build_ms=6000 offset=11 sections_top=a:1 executor=worker turns=- worker_pid=9 pid=7
2026-10-06 10:01:00,001 INFO agent_runtime.snapshot.context: snapshot_build_core role=led caller=hub generation=2 build_ms=3000 offset=12 sections_top=a:1 reason=demote executor=worker turns=t1,t2 worker_pid=9 pid=7
2026-10-06 10:01:01,001 INFO agent_runtime.stream: snapshot_build reason=demote waited_ms=3000 role=shared_next caller=cli pid=7
2026-10-06 10:02:00,001 WARNING agent_runtime.snapshot_worker.executor: snapshot_worker op=lost reason=timeout fallback=in_process worker_pid=9 respawns=0 pid=7
2026-10-06 10:02:00,002 INFO agent_runtime.snapshot.context: snapshot_build_core role=led caller=cli generation=3 build_ms=4000 offset=13 sections_top=a:1 reason=demote executor=in_process turns=t2,? worker_pid=- pid=7
"""


def test_census_numbers_from_a_fixture_log():
    from datetime import datetime

    report = census_builds(_FIXTURE_LOG.splitlines(), since=datetime(2026, 10, 6, 9, 30))
    assert (report["builds"], report["led"], report["shadow"]) == (4, 3, 1)
    assert (report["total_build_ms"], report["max_build_ms"]) == (29000, 16000)
    assert report["by_executor"] == {"in_process": 1, "worker": 3}
    assert report["by_trigger"]["hub/demote"] == {"builds": 1, "total_ms": 3000, "max_ms": 3000}
    assert report["by_trigger"]["prewarm/boot"]["builds"] == 1
    assert report["worker_fallbacks"] == 1
    assert report["turns_affected"] == {"builds_with_turns": 2, "builds_turns_unknown": 0,
                                        "distinct_turns": 2, "turn_ids": ["t1", "t2"]}
    older = census_builds(_FIXTURE_LOG.splitlines())
    assert older["by_executor"]["unknown"] == 1 and older["turns_affected"]["builds_turns_unknown"] == 1


def test_observe_snapshot_builds_verb_reads_the_log_and_its_rotations(tmp_path, capsys):
    from hermes_cli.harness_parts.observe_commands import _cmd_observe_snapshot_builds

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    log = tmp_path / "agent.log"
    rotated = tmp_path / "agent.log.1"
    line = (f"{now},000 INFO x: snapshot_build_core role=led caller=hub generation=1 build_ms=%d offset=1 "
            "sections_top=a:1 reason=demote executor=worker turns=t9 worker_pid=3 pid=2\n")
    rotated.write_text(line % 100, encoding="utf-8")
    log.write_text(line % 200, encoding="utf-8")
    assert _cmd_observe_snapshot_builds(Namespace(since="1h", log=str(log), json=True)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["builds"] == 2 and report["total_build_ms"] == 300
    assert report["window"]["files"] == [str(rotated), str(log)]
    assert _cmd_observe_snapshot_builds(Namespace(since="soon", log=str(log), json=True)) == 2


def test_parse_duration():
    assert parse_duration("90s").total_seconds() == 90
    assert parse_duration("2h").total_seconds() == 7200
    with pytest.raises(ValueError):
        parse_duration("2 hours")


def test_worker_ready_identity_names_interpreter_not_windows_stub():
    from agent_runtime.snapshot_worker.peer import SnapshotPeer, READY_METHOD
    from types import SimpleNamespace
    # Invoke the receipt owner with a minimal peer: process.pid is the Windows
    # venv launcher, while the child itself reports the running interpreter.
    peer = SimpleNamespace(ready_at=None, _clock=lambda: 1.0, worker_pid=None,
                           process=SimpleNamespace(pid=100))
    SnapshotPeer._notice(peer, {"method": READY_METHOD, "params": {"worker_pid": 200}})
    assert SnapshotPeer.pid.fget(peer) == 200
    assert peer.ready_at == 1.0
