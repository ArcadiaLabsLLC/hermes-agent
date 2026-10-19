"""The batch → lane → landing state machine (dispatcher plan §3.2, §3.3, §3.5) through ``BatchDispatcher``
over the contract fakes.

Killing mutations (plan §6 B2), each red recorded in the B2 commit body:
* ``BATCH_MOVES`` gains ``(LANDING, APPROVE) → LANDED`` (LANDED without AWAITING_APPROVAL) →
  ``test_approve_is_the_only_door_to_main`` red;
* ``AUTOMATABLE[START]`` gains ``BatchAction.LAND`` → ``test_land_and_approve_are_never_automated`` red;
* ``_stop_lane`` releases a RUNNING lane at once instead of waiting → ``test_stop_waits_for_the_running_turn`` red.

RT-BATCH-GATE-RECEIPT (owner ruling 2026-10-18), red recorded in its commit body:
* ``BatchDispatcher.approve`` without ``require_green`` → ``test_approve_refuses_without_a_green_gate_receipt`` red.
"""

from __future__ import annotations

import pytest

from agent_runtime.batch.machine import (
    AUTOMATABLE, BATCH_MOVES, Automation, BatchAction, BatchEvent, BatchState, LaneState, automation_allows, move,
)
from agent_runtime.batch.planner import Budget, Member
from agent_runtime.work_store.executor import Outcome, RowEnding, RunStatus, Verdict
from agent_runtime.work_store.grammar import Status
from agent_runtime.work_store.reasons import Reason, WorkRefused

from batch_support import WS, FakeLander, FakeManifests, dispatcher, gate, qrow, settings
from contract_fakes import FakeExecutor, FakeSource

ROSTER = [Member("inst-a", "alice", "engineer"), Member("inst-b", "bob", "engineer")]


def rows(*headings: str, assignee: str = "inst-a", per: int = 1, extra: str = ""):
    return [qrow(f"RT-{h[:2].upper()}{i}", heading=h, assignee=assignee, extra=extra) for h in headings for i in range(per)]


def refused(call) -> Reason:
    with pytest.raises(WorkRefused) as caught:
        call()
    return caught.value.reason


def started(source: FakeSource, **kw):
    d = dispatcher(source, roster=ROSTER, **kw)
    batch = d.start(WS, d.plan(WS).id)
    return d, batch


def settle_all(d, batch, verdict=Verdict.DONE):
    for lane in d.load(WS, batch.id).lanes:
        if lane.state is LaneState.RUNNING:
            d.executor.settle(f"{batch.id}:{lane.id}", Outcome(verdict, report="ok"))


def test_approve_is_the_only_door_to_main():
    assert [key for key, to in BATCH_MOVES.items() if to is BatchState.LANDED] == [
        (BatchState.AWAITING_APPROVAL, BatchEvent.APPROVE)]
    for state in BatchState:
        if state is not BatchState.AWAITING_APPROVAL:
            assert refused(lambda: move(BATCH_MOVES, state, BatchEvent.APPROVE)) is Reason.STATE_TRANSITION_INVALID
    lander = FakeLander()
    d, batch = started(FakeSource(rows("Fork-owned")), lander=lander)
    assert refused(lambda: d.approve(WS, batch.id)) is Reason.STATE_TRANSITION_INVALID
    settle_all(d, batch)
    assert d.load(WS, batch.id).state is BatchState.READY_TO_LAND
    assert refused(lambda: d.approve(WS, batch.id)) is Reason.STATE_TRANSITION_INVALID
    landing = d.land(WS, batch.id)
    assert landing.state is BatchState.LANDING and landing.landing.state is LaneState.RUNNING
    assert refused(lambda: d.approve(WS, batch.id)) is Reason.STATE_TRANSITION_INVALID
    d.executor.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="green: 12 passed", gates=(gate(),)))
    waiting = d.load(WS, batch.id)
    assert waiting.state is BatchState.AWAITING_APPROVAL and waiting.gate_receipts == (gate(),)
    assert waiting.gate == "hermes: exit 0 — === Summary: 3 files, 12 tests passed, 0 failed ==="
    assert lander.pushed == []
    landed = d.approve(WS, batch.id)
    assert landed.state is BatchState.LANDED and landed.landing_sha == "f00dfeed" and lander.pushed == [batch.id]


def test_approve_without_a_bound_lander_refuses_not_built_and_keeps_waiting():
    d, batch = started(FakeSource(rows("Fork-owned")))
    settle_all(d, batch)
    d.land(WS, batch.id)
    d.executor.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, gates=(gate(),)))
    assert refused(lambda: d.approve(WS, batch.id)) is Reason.NOT_BUILT
    assert d.load(WS, batch.id).state is BatchState.AWAITING_APPROVAL


def test_a_red_landing_returns_to_ready_to_land_and_lands_again():
    d, batch = started(FakeSource(rows("Fork-owned")))
    settle_all(d, batch)
    d.land(WS, batch.id)
    d.executor.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="green", gates=(gate(1, "red: test_x"),)))
    again = d.load(WS, batch.id)
    assert again.state is BatchState.READY_TO_LAND and again.gate == "hermes: exit 1 — red: test_x"
    relanded = d.land(WS, batch.id)
    assert relanded.landing_attempt == 2 and relanded.gate_receipts == ()


def test_the_gate_decides_and_the_persona_verdict_is_advisory():
    d, batch = started(FakeSource(rows("Fork-owned")))
    settle_all(d, batch)
    d.land(WS, batch.id)
    d.executor.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="all green, trust me"))
    assert d.load(WS, batch.id).state is BatchState.READY_TO_LAND, "no code-run gate: never green"
    d.land(WS, batch.id)
    d.executor.settle(f"{batch.id}:LAND:2", Outcome(Verdict.BLOCKED, report="I think x is red", gates=(gate(),)))
    assert d.load(WS, batch.id).state is BatchState.AWAITING_APPROVAL


def test_approve_refuses_without_a_green_gate_receipt():
    """A batch awaiting approval with no green receipt (a pre-ruling manifest) never reaches the lander."""

    lander, manifests = FakeLander(), FakeManifests()
    d, batch = started(FakeSource(rows("Fork-owned")), lander=lander, manifests=manifests)
    settle_all(d, batch)
    d.land(WS, batch.id)
    d.executor.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="green: 12 passed"))
    manifests.append(WS, batch.id, [d._batch_line(BatchState.AWAITING_APPROVAL, {"gate": "the persona said green"})],
                     "pre-ruling")
    assert d.load(WS, batch.id).state is BatchState.AWAITING_APPROVAL
    assert refused(lambda: d.approve(WS, batch.id)) is Reason.GATE_NOT_GREEN
    assert lander.pushed == [] and d.load(WS, batch.id).state is BatchState.AWAITING_APPROVAL


def test_land_and_approve_are_never_automated():
    assert all(BatchAction.LAND not in allowed and BatchAction.APPROVE not in allowed
               for allowed in AUTOMATABLE.values())
    assert refused(lambda: automation_allows(Automation.OFF, BatchAction.START)) is Reason.AUTOMATION_OFF
    assert refused(lambda: automation_allows(Automation.PLAN, BatchAction.START)) is Reason.AUTOMATION_OFF
    automation_allows(Automation.START, BatchAction.START)
    off = dispatcher(FakeSource(rows("Fork-owned")), roster=ROSTER)
    assert off.automation(WS) is Automation.OFF
    assert refused(lambda: off.plan(WS, scheduled=True)) is Reason.AUTOMATION_OFF
    plan_id = off.plan(WS).id
    assert refused(lambda: off.start(WS, plan_id, scheduled=True)) is Reason.AUTOMATION_OFF
    on = dispatcher(FakeSource(rows("Fork-owned")), roster=ROSTER, manifests=FakeManifests(settings("start")))
    assert on.start(WS, plan_id, scheduled=True).state is BatchState.STARTED


def test_rows_are_claimed_and_a_lane_settles_its_rows_by_ending():
    source = FakeSource(rows("Fork-owned", "Seams", per=2))
    d, batch = started(source)
    assert all(r.taken is not None and r.taken.who == "persona:inst-a" for r in source.by_ref.values())
    assert [lane.state for lane in batch.lanes] == [LaneState.RUNNING, LaneState.RUNNING]
    first, second = batch.lanes
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE, {first.rows[0]: RowEnding(Verdict.DONE, result="did it"),
                                                              first.rows[1]: RowEnding(Verdict.BLOCKED, question="Q?")}))
    assert first.rows[0] not in source.by_ref
    blocked = source.by_ref[first.rows[1]]
    assert blocked.status is Status.BLOCKED and blocked.taken is None and "Q?" in blocked.status_body
    d.executor.settle(f"{batch.id}:L2", Outcome(Verdict.FAILED))
    assert all(source.by_ref[r].status is Status.NEEDS_PLAN and source.by_ref[r].taken is None for r in second.rows)
    after = d.load(WS, batch.id)
    assert [(lane.state, lane.done_rows) for lane in after.lanes] == [(LaneState.REPORTED, 1), (LaneState.STOPPED, 0)]
    assert after.state is BatchState.READY_TO_LAND


def test_no_work_no_landing():
    d, batch = started(FakeSource(rows("Fork-owned")))
    settle_all(d, batch, Verdict.FAILED)
    assert d.load(WS, batch.id).state is BatchState.STARTED


def test_lanes_start_under_the_budget():
    source = FakeSource(rows("A-one", "B-two", "C-three"))
    d, batch = started(source, budget=Budget(max_lanes=2))
    assert [lane.state for lane in batch.lanes] == [LaneState.RUNNING, LaneState.RUNNING, LaneState.CLAIMED]
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE))
    assert d.load(WS, batch.id).lanes[2].state is LaneState.RUNNING
    heavy = FakeSource(rows("A-one", "B-two", extra=" on the daily branch"))
    _d2, batch2 = started(heavy)
    assert [lane.state for lane in batch2.lanes] == [LaneState.RUNNING, LaneState.CLAIMED]
    quiet = FakeSource(rows("A-one", extra=" a flaky test"))
    _d3, batch3 = started(quiet, box_idle=False)
    assert batch3.lanes[0].state is LaneState.CLAIMED


def test_a_sequenced_lane_waits_for_the_lane_it_follows():
    shared = [qrow("RT-A", heading="A", files=["agent_runtime/x.py"], assignee="inst-a"),
              qrow("RT-B", heading="B", files=["agent_runtime/x.py"], assignee="inst-a")]
    d, batch = started(FakeSource(shared))
    assert [(lane.state, lane.lane.after) for lane in batch.lanes] == [(LaneState.RUNNING, ()), (LaneState.CLAIMED, ("L1",))]
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE))
    assert d.load(WS, batch.id).lanes[1].state is LaneState.RUNNING


def test_stop_waits_for_the_running_turn():
    source = FakeSource(rows("Fork-owned"))
    d, batch = started(source)
    lane = batch.lanes[0]
    d.executor.statuses[lane.run_id] = RunStatus.RUNNING
    stopping = d.stop(WS, batch.id, "L1")
    assert stopping.lanes[0].state is LaneState.RUNNING and stopping.lanes[0].stop_requested
    assert source.by_ref[lane.rows[0]].taken is not None, "a running turn keeps its claim until it ends"
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.BLOCKED, {lane.rows[0]: RowEnding(Verdict.BLOCKED, question="?")}))
    row = source.by_ref[lane.rows[0]]
    assert row.status is Status.DEFERRED and row.taken is None and row.status_body.startswith("stopped")
    assert d.load(WS, batch.id).lanes[0].state is LaneState.STOPPED


def test_stop_releases_a_lane_that_has_not_begun_and_abort_releases_every_claim():
    source = FakeSource(rows("A-one", "B-two", "C-three"))
    d, batch = started(source, budget=Budget(max_lanes=1))
    claimed = batch.lanes[1]
    assert d.stop(WS, batch.id, "L2").lanes[1].state is LaneState.STOPPED
    assert source.by_ref[claimed.rows[0]].status is Status.DEFERRED and source.by_ref[claimed.rows[0]].taken is None
    aborted = d.stop(WS, batch.id)
    assert aborted.state is BatchState.ABORTED
    assert all(r.taken is None for r in source.by_ref.values())
    assert refused(lambda: d.stop(WS, batch.id)) is Reason.STATE_TRANSITION_INVALID


def test_start_refuses_a_moved_board_and_an_unasked_persona_and_replays():
    source = FakeSource(rows("Fork-owned"))
    d = dispatcher(source, roster=ROSTER)
    stale = d.plan(WS).id
    source.by_ref[qrow("RT-NEW").ref] = qrow("RT-NEW", assignee="inst-a")
    assert refused(lambda: d.start(WS, stale)) is Reason.CONFLICT
    lonely = dispatcher(FakeSource([qrow("RT-A")]), roster=ROSTER)
    plan = lonely.plan(WS)
    assert plan.asks and refused(lambda: lonely.start(WS, plan.id)) is Reason.PERSONA_UNRESOLVED
    assert lonely.start(WS, plan.id, personas={"L1": "inst-b"}).lanes[0].persona == "inst-b"
    fresh = dispatcher(FakeSource(rows("Fork-owned")), roster=ROSTER)
    once = fresh.start(WS, fresh.plan(WS).id)
    assert fresh.start(WS, once.id) == once, "a second start is a replay"


def test_only_the_owner_machine_runs_lands_and_approves():
    source, manifests = FakeSource(rows("Fork-owned")), FakeManifests()
    owner, batch = started(source, manifests=manifests)
    settle_all(owner, batch)
    other = dispatcher(source, manifests=manifests, machine="m-2", roster=ROSTER)
    assert refused(lambda: other.land(WS, batch.id)) is Reason.NOT_OWNER_MACHINE
    assert refused(lambda: other.approve(WS, batch.id)) is Reason.NOT_OWNER_MACHINE
    assert other.status(WS)["batches"][0]["owner_machine"] == "m-1"


def test_one_landing_at_a_time_on_a_machine():
    source, manifests = FakeSource(rows("Fork-owned")), FakeManifests()
    d, first = started(source, manifests=manifests)
    settle_all(d, first)
    d.land(WS, first.id)
    source.by_ref.update({r.ref: r for r in rows("Seams")})
    second = d.start(WS, d.plan(WS).id)
    settle_all(d, second)
    assert refused(lambda: d.land(WS, second.id)) is Reason.LANDING_IN_PROGRESS


def test_status_reads_marks_from_the_rows():
    source = FakeSource(rows("Fork-owned", per=2))
    d, batch = started(source)
    ref, other = batch.lanes[0].rows
    assert d.status(WS, batch.id)["batches"][0]["marks"] == {f"hermes/{ref.id}": "persona:inst-a",
                                                             f"hermes/{other.id}": "persona:inst-a"}
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE, {ref: RowEnding(Verdict.DONE),
                                                              other: RowEnding(Verdict.BLOCKED, question="?")}))
    marks = d.status(WS, batch.id)["batches"][0]["marks"]
    assert marks == {f"hermes/{ref.id}": "gone", f"hermes/{other.id}": "BLOCKED"}
    assert refused(lambda: d.status(WS, "BATCH-NOPE00")) is Reason.BATCH_MISSING


def test_a_settle_of_another_run_is_ignored():
    d, batch = started(FakeSource(rows("Fork-owned")))
    executor: FakeExecutor = d.executor
    executor.runs["other:req"] = executor.runs[f"{batch.id}:L1"].__class__(
        "run-x", "other:req", None, "root", "cmid", "now", RunStatus.QUEUED)
    executor.settle("other:req", Outcome(Verdict.DONE))
    assert d.load(WS, batch.id).lanes[0].state is LaneState.RUNNING
