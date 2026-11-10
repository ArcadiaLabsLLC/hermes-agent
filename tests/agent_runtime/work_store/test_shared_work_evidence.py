"""Shared Work uses executor proof, never a RUNNING manifest or worktree."""
from dataclasses import replace

from agent_runtime.batch.machine import LaneState
from agent_runtime.work_store.executor import RunStatus
from batch_support import WS, FakeManifests, dispatcher, qrow
from contract_fakes import FakeExecutor, FakeSource


def test_running_manifest_is_queued_until_executor_runs():
    source, executor, manifests = FakeSource([qrow("RT-A")]), FakeExecutor(), FakeManifests()
    d = dispatcher(source, executor=executor, manifests=manifests)
    plan = d.plan(WS)
    batch = d.start(WS, plan.id, personas={lane: "inst-a" for lane in plan.asks})
    lane = batch.lanes[0]
    assert lane.state is LaneState.RUNNING
    assert d.status(WS)["batches"][0]["lanes"][0]["execution"] == "queued"
    executor.statuses[lane.run_id] = RunStatus.RUNNING
    assert d.status(WS)["batches"][0]["lanes"][0]["execution"] == "running"
    other = dispatcher(source, executor=executor, manifests=manifests, machine="another-machine")
    other_lane = other.status(WS)["batches"][0]["lanes"][0]
    assert other_lane["execution"] is None and other_lane["session_id"] is None


def test_exact_attempt_session_and_missing_executor(monkeypatch):
    source, executor, manifests = FakeSource([qrow("RT-A")]), FakeExecutor(), FakeManifests()
    start = executor.start
    def native_run(assignment):
        run = replace(start(assignment), run_id="exact-root/exact-message")
        executor.statuses[run.run_id] = RunStatus.RUNNING
        return run
    monkeypatch.setattr(executor, "start", native_run)
    d = dispatcher(source, executor=executor, manifests=manifests)
    plan = d.plan(WS)
    d.start(WS, plan.id, personas={lane: "inst-a" for lane in plan.asks})
    wire = d.status(WS)["batches"][0]["lanes"][0]
    assert wire["run_id"] == "exact-root/exact-message" and wire["session_id"] == "exact-root"
    def unavailable(_run_id):
        raise OSError("executor unavailable")
    monkeypatch.setattr(executor, "status", unavailable)
    wire = d.status(WS)["batches"][0]["lanes"][0]
    assert wire["execution"] is None and wire["session_id"] is None
