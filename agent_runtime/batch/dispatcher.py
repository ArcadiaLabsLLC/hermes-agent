"""``BatchDispatcher`` — plan, start, run, stop, land and approve a batch (dispatcher plan §3.1–§3.5).

It holds no state: every call folds the batch from its manifest (``manifest.fold``) and the rows'
claim marks, moves it by the tables in ``machine.py``, and appends ONE manifest line per lane per state
through the W2 writer before or after the side effect it records:

* ``plan`` reads ``WorkSource.ready`` and writes nothing (``batch.planned``);
* ``start`` (manual; a scheduler fire only at ``batch_automation: start``) re-plans, refuses
  ``idempotency_conflict`` when the board moved since the plan, writes the manifest (``STARTED`` + the
  plan + each lane's brief) FIRST — so the W3 engine's ``held`` hook already skips the rows — then claims
  each lane's rows ``persona:<instance_id>`` and starts what the budget allows. A second ``start`` of a
  batch whose manifest exists is a replay that finishes any claim a crash left;
* a lane runs as ONE ``Executor`` assignment of all its rows; its settle writes every row's ending
  (``ROW_ENDINGS``) and the lane line, then advances the batch (``READY_TO_LAND`` when every lane settled
  with work);
* ``stop`` releases a lane that has not begun and WAITS for a running turn (owner ruling 2026-10-18):
  the lane line records ``STOP_REQUESTED`` and the settle ends the lane ``STOPPED``; ``stop`` with no lane
  aborts the batch (every claim released ``DEFERRED``);
* ``land`` (manual only) runs the landing lane; ``approve`` (manual only) is the ONLY door to
  ``LANDED`` — the push is the ``Lander``'s, which B5 (``RT-DISPATCH-B5-LANE-EXECUTOR``) builds; until
  then it refuses ``not_built``.

Multi-device (§3.5): the machine that started a batch owns it (``owner_machine``); only it runs lanes,
lands or approves (``not_owner_machine``); any machine may read it and ``stop`` (a release is a row op
any writer replays). Receipts: ``batch.planned | started | lane_refused | waiting_box | lane_settled |
stop_requested | ready_to_land | landing | awaiting_approval | landing_red | landed | aborted``, beside
the writer's ``work.row_*`` and the executor's ``work.exec_*``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from ..work_store import receipts
from ..work_store.executor import Assignment, Executor, Outcome, RowEnding, Run, StopReason, Verdict
from ..work_store.grammar import RowRef, Status
from ..work_store.reasons import Reason, WorkRefused
from ..work_store.source import Claimant, WorkSource
from .machine import (
    BATCH_MOVES, LANE_MOVES, Automation, Batch, BatchAction, BatchEvent, BatchState, LaneEvent, LaneRecord,
    LaneState, automation_allows, move, ready_to_land, startable,
)
from .manifest import (
    BATCH_SUBJECT, LANE_PREFIX, STOP_REQUESTED, ManifestStore, automation_of, brief_path, entry_line, fold, head,
    manifest_path,
)
from .planner import LANDING_ID, Budget, LaneKind, Member, Plan, plan as make_plan

__layer__ = "lanes"
__all__ = ["ROW_ENDINGS", "BatchDispatcher", "Lander", "UnbuiltLander", "default_dispatcher", "idle_box"]

logger = logging.getLogger(__name__)

_REPORTED = frozenset({Verdict.DONE, Verdict.BLOCKED})
_SETTLED = frozenset({LaneState.REPORTED, LaneState.STOPPED})
_HOLDING_LANDING = frozenset({BatchState.LANDING, BatchState.AWAITING_APPROVAL})
_GATE_TAIL = 1000

#: A row's ending → the one SOURCE write it is (the W3 engine's ``WRITE_BACKS``, over the contract).
ROW_ENDINGS: dict[Verdict, Callable[[WorkSource, RowRef, Claimant, RowEnding], Any]] = {
    Verdict.DONE: lambda src, ref, who, e: src.done(ref, who, e.result or "done"),
    Verdict.BLOCKED: lambda src, ref, who, e: src.block(ref, who, e.question or "the lane asked no question",
                                                        e.recommend),
    Verdict.STOPPED: lambda src, ref, who, e: src.release(ref, who, Status.DEFERRED,
                                                          f"stopped — {e.reason or 'no reason given'}"),
    Verdict.FAILED: lambda src, ref, who, e: src.release(
        ref, who, Status.NEEDS_PLAN, f"batch lane ended without a readable work_report ({e.reason or 'no detail'})"),
}


class Lander(Protocol):
    def push(self, batch: Batch) -> str:
        """Push the landing lane's branch to ``main`` fast-forward; the landing SHA."""


class UnbuiltLander:
    """B2 has no landing worktree; ``RT-DISPATCH-B5-LANE-EXECUTOR`` builds the push behind ``approve``."""

    def push(self, batch: Batch) -> str:
        raise WorkRefused(Reason.NOT_BUILT, "RT-DISPATCH-B5-LANE-EXECUTOR builds the landing push")


def idle_box(*, cpu_max: float = 50.0, python_max: int = 20) -> bool:
    """``Dispatching a lane.md`` § 2's two numbers: CPU under 50 % and fewer than 20 python processes."""

    try:
        import psutil
    except ImportError:
        return False
    pythons = sum(1 for p in psutil.process_iter(["name"]) if "python" in str(p.info.get("name") or "").lower())
    return psutil.cpu_percent(interval=0.5) < cpu_max and pythons < python_max


def _stamp(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


class BatchDispatcher:
    """The operations over one machine's view of every workspace's batches."""

    def __init__(
        self,
        *,
        source_for: Callable[[str], WorkSource],
        manifests: ManifestStore,
        executor: Executor,
        machine: Callable[[], str],
        roster: Callable[[str], list[Member]] = lambda _ws: [],
        slot_roles: Callable[[str], dict[str, str]] = lambda _ws: {},
        budget_for: Callable[[str], Budget] = lambda _ws: Budget(),
        box_idle: Callable[[], bool] = idle_box,
        lander: Lander | None = None,
        workspaces: Callable[[], list[str]] = list,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._source_for = source_for
        self.manifests = manifests
        self.executor = executor
        self._machine = machine
        self._roster = roster
        self._slot_roles = slot_roles
        self._budget_for = budget_for
        self._box_idle = box_idle
        self._lander = lander or UnbuiltLander()
        self._workspaces = workspaces
        self._now = now or (lambda: datetime.now(UTC))

    # ── reads ────────────────────────────────────────────────────────────

    def plan(self, workspace_id: str, *, scheduled: bool = False) -> Plan:
        if scheduled:
            automation_allows(self.automation(workspace_id), BatchAction.PLAN)
        rows = self._source_for(workspace_id).ready(workspace_id)
        planned = make_plan(rows, workspace_id=workspace_id, roster=self._roster(workspace_id),
                            slot_roles=self._slot_roles(workspace_id), budget=self._budget_for(workspace_id))
        receipts.emit("batch.planned", workspace_id=workspace_id, batch_id=planned.id,
                      lanes=[lane.id for lane in planned.lanes], asks=list(planned.asks))
        return planned

    def automation(self, workspace_id: str) -> Automation:
        return automation_of(self.manifests.settings(workspace_id))

    def load(self, workspace_id: str, batch_id: str, *, fresh: bool = True) -> Batch:
        text = self.manifests.texts(workspace_id, fresh=fresh).get(batch_id)
        batch = fold(text) if text is not None else None
        if batch is None:
            raise WorkRefused(Reason.BATCH_MISSING, batch_id)
        return batch

    def status(self, workspace_id: str, batch_id: str | None = None) -> dict[str, Any]:
        """Every batch of the workspace (or one), each lane's rows with their marks at the tip."""

        texts = self.manifests.texts(workspace_id)
        if batch_id is not None and batch_id not in texts:
            raise WorkRefused(Reason.BATCH_MISSING, batch_id)
        batches = [b for key, text in sorted(texts.items()) if batch_id in (None, key) and (b := fold(text))]
        rows = {row.ref: row for row in self._source_for(workspace_id).rows(workspace_id)}
        marks = lambda ref: ("gone" if ref not in rows else
                             rows[ref].taken.who if rows[ref].taken else (rows[ref].status or Status.READY).value)
        return {"automation": self.automation(workspace_id).value, "machine": self._machine(),
                "batches": [{**b.wire(), "marks": {f"{r.slot}/{r.id}": marks(r) for lane in b.lanes
                                                   for r in (lane.rows or lane.lane.rows)}} for b in batches]}

    # ── start ────────────────────────────────────────────────────────────

    def start(self, workspace_id: str, plan_id: str, *, personas: Mapping[str, str] | None = None,
              scheduled: bool = False) -> Batch:
        if scheduled:
            automation_allows(self.automation(workspace_id), BatchAction.START)
        if plan_id not in self.manifests.texts(workspace_id):
            self._open(workspace_id, plan_id, personas or {})
        batch = self.load(workspace_id, plan_id)
        self._own(batch)
        for record in batch.lanes:
            if record.state is LaneState.PLANNED:
                self._claim(workspace_id, batch, record)
        receipts.emit("batch.started", workspace_id=workspace_id, batch_id=plan_id, scheduled=scheduled)
        return self.advance(workspace_id, plan_id)

    def _open(self, workspace_id: str, plan_id: str, personas: Mapping[str, str]) -> None:
        planned = self.plan(workspace_id)
        if planned.id != plan_id:
            raise WorkRefused(Reason.CONFLICT, f"the board moved since {plan_id} was planned (now {planned.id})")
        planned = planned.with_personas(personas)
        if planned.asks:
            raise WorkRefused(Reason.PERSONA_UNRESOLVED, "name a persona instance for " + ", ".join(planned.asks))
        move(BATCH_MOVES, BatchState.PLANNED, BatchEvent.START)
        from ..work_store.persona_turn import render_brief

        files = {manifest_path(plan_id): head(planned, owner_machine=self._machine(), created_at=self._at())}
        for lane in (*planned.lanes, planned.landing):
            files[brief_path(plan_id, lane.id)] = render_brief(self._assignment(plan_id, lane.rows, lane.persona or "",
                                                                                lane, lane.id)) + "\n"
        line = entry_line(self._at(), BATCH_SUBJECT, BatchState.STARTED.value, {"plan": planned.wire()})
        self.manifests.append(workspace_id, plan_id, [line], f"{plan_id}:started", files=files)

    def _claim(self, workspace_id: str, batch: Batch, record: LaneRecord) -> None:
        source = self._source_for(workspace_id)
        who = Claimant.persona(record.persona or "")
        claimed: list[RowRef] = []
        lost: list[list[str]] = []
        for ref in record.lane.rows:
            try:
                source.claim(ref, who, f"{batch.id}:{record.id}:claim:{ref.id}")
                claimed.append(ref)
            except WorkRefused as refused:
                lost.append([ref.slot, ref.note, ref.id, refused.reason.value])
        lines = [self._lane_line(record.id, move(LANE_MOVES, record.state, LaneEvent.CLAIM), {
            "rows": [[r.slot, r.note, r.id] for r in claimed], "persona": record.persona, "lost": lost})]
        if not claimed:
            lines.append(self._lane_line(record.id, LaneState.STOPPED, {"reason": "no row could be claimed"}))
        self.manifests.append(workspace_id, batch.id, lines, f"{batch.id}:{record.id}:claimed")

    # ── running lanes ────────────────────────────────────────────────────

    def advance(self, workspace_id: str, batch_id: str) -> Batch:
        """Start what the budget allows; mark ``READY_TO_LAND`` once every lane settled with work."""

        batch = self.load(workspace_id, batch_id)
        if batch.owner_machine != self._machine():
            return batch
        if batch.state is BatchState.LANDING and batch.landing.state is LaneState.CLAIMED:
            self._run(workspace_id, batch, batch.landing)
            return self.load(workspace_id, batch_id)
        if batch.state is not BatchState.STARTED:
            return batch
        quiet = any(r.lane.quiet_box and r.state is LaneState.CLAIMED for r in batch.lanes)
        start, waiting = startable(batch, batch.budget, box_idle=self._box_idle() if quiet else True)
        for record in waiting:
            receipts.emit("batch.waiting_box", workspace_id=workspace_id, batch_id=batch_id, lane=record.id)
        for record in start:
            self._run(workspace_id, batch, record)
        batch = self.load(workspace_id, batch_id) if start else batch
        if ready_to_land(batch.lanes):
            state = move(BATCH_MOVES, batch.state, BatchEvent.LANES_SETTLED)
            self.manifests.append(workspace_id, batch_id, [self._batch_line(state, {})], f"{batch_id}:ready_to_land")
            receipts.emit("batch.ready_to_land", workspace_id=workspace_id, batch_id=batch_id)
            batch = self.load(workspace_id, batch_id)
        return batch

    def _assignment(self, batch_id: str, rows: tuple[RowRef, ...], persona: str, lane: Any, request: str) -> Assignment:
        return Assignment(rows, persona, lane.brief, f"{batch_id}:{request}", heavy=lane.heavy)

    def _request(self, batch: Batch, record: LaneRecord) -> str:
        return f"{LANDING_ID}:{batch.landing_attempt}" if record.lane.kind is LaneKind.LANDING else record.id

    def _run(self, workspace_id: str, batch: Batch, record: LaneRecord) -> None:
        a = self._assignment(batch.id, record.rows, record.persona or "", record.lane, self._request(batch, record))
        refusal = self.executor.can_start(a)
        try:
            if refusal is not None:
                raise WorkRefused(refusal, a.persona_instance_id)
            run = self.executor.start(a)
        except WorkRefused as refused:
            receipts.emit("batch.lane_refused", workspace_id=workspace_id, batch_id=batch.id, lane=record.id,
                          reason=refused.reason.value, detail=refused.detail)
            return
        line = self._lane_line(record.id, move(LANE_MOVES, record.state, LaneEvent.RUN), {"run_id": run.run_id})
        self.manifests.append(workspace_id, batch.id, [line], f"{a.request_id}:running")

    def settled(self, run: Run, outcome: Outcome) -> None:
        """The executor's settle callback: a batch lane's turn ended (any other run is not ours)."""

        batch_id, _sep, request = run.request_id.partition(":")
        if not batch_id.startswith("BATCH-") or not request:
            return
        found = self._find(batch_id)
        if found is None:
            logger.warning("batch %s settled a run but no manifest names it", batch_id)
            return
        workspace_id, batch = found
        record = batch.lane(request.split(":")[0])
        if record.state is not LaneState.RUNNING or record.run_id not in ("", run.run_id):
            return  # a repeat settle, or a run this lane no longer waits on
        settle = self._landing_settled if record.lane.kind is LaneKind.LANDING else self._lane_settled
        settle(workspace_id, batch, record, outcome)
        self.advance(workspace_id, batch_id)

    def _lane_settled(self, workspace_id: str, batch: Batch, record: LaneRecord, outcome: Outcome) -> None:
        source = self._source_for(workspace_id)
        who = Claimant.persona(record.persona or "")
        stopping = record.stop_requested or batch.state is BatchState.ABORTED
        done, errors = 0, []
        for ref in record.rows:
            ending = outcome.per_row.get(ref) or RowEnding(outcome.verdict, reason="the lane named no ending")
            if stopping and ending.verdict is not Verdict.DONE:
                ending = RowEnding(Verdict.STOPPED, reason="operator stop")
            try:
                ROW_ENDINGS[ending.verdict](source, ref, who, ending)
                done += ending.verdict is Verdict.DONE
            except WorkRefused as refused:
                errors.append([ref.id, refused.reason.value])
        event = LaneEvent.REPORT if outcome.verdict in _REPORTED and not stopping else LaneEvent.STOP
        state = move(LANE_MOVES, record.state, event)
        line = self._lane_line(record.id, state, {"verdict": outcome.verdict.value, "tool_calls": outcome.tool_calls,
                                                  "commits": list(outcome.commits), "done_rows": done,
                                                  "errors": errors})
        self.manifests.append(workspace_id, batch.id, [line], f"{batch.id}:{record.id}:settled")
        receipts.emit("batch.lane_settled", workspace_id=workspace_id, batch_id=batch.id, lane=record.id,
                      state=state.value, verdict=outcome.verdict.value, done_rows=done, errors=errors)

    def _landing_settled(self, workspace_id: str, batch: Batch, record: LaneRecord, outcome: Outcome) -> None:
        green = outcome.verdict is Verdict.DONE and batch.state is BatchState.LANDING
        lane_state = move(LANE_MOVES, record.state, LaneEvent.REPORT if green else LaneEvent.STOP)
        lines = [self._lane_line(record.id, lane_state, {"verdict": outcome.verdict.value,
                                                         "tool_calls": outcome.tool_calls,
                                                         "commits": list(outcome.commits)})]
        if batch.state is BatchState.LANDING:
            state = move(BATCH_MOVES, batch.state, BatchEvent.LANDING_GREEN if green else BatchEvent.LANDING_RED)
            lines.append(self._batch_line(state, {"gate": outcome.report[-_GATE_TAIL:]}))
            receipts.emit("batch.awaiting_approval" if green else "batch.landing_red", workspace_id=workspace_id,
                          batch_id=batch.id, attempt=batch.landing_attempt)
        self.manifests.append(workspace_id, batch.id, lines, f"{batch.id}:{self._request(batch, record)}:settled")

    # ── stop ─────────────────────────────────────────────────────────────

    def stop(self, workspace_id: str, batch_id: str, lane_id: str | None = None) -> Batch:
        """Stop one lane, or (no lane) abort the batch: every claim released, running turns waited on."""

        batch = self.load(workspace_id, batch_id)
        if lane_id is not None:
            self._stop_lane(workspace_id, batch, batch.lane(lane_id))
            return self.load(workspace_id, batch_id)
        state = move(BATCH_MOVES, batch.state, BatchEvent.ABORT)
        for record in (*batch.lanes, batch.landing):
            if record.state not in _SETTLED and not (record.lane.kind is LaneKind.LANDING
                                                     and record.state is LaneState.PLANNED):
                self._stop_lane(workspace_id, batch, record)
        self.manifests.append(workspace_id, batch_id, [self._batch_line(state, {"reason": "operator stop"})],
                              f"{batch_id}:aborted")
        receipts.emit("batch.aborted", workspace_id=workspace_id, batch_id=batch_id)
        return self.load(workspace_id, batch_id)

    def _stop_lane(self, workspace_id: str, batch: Batch, record: LaneRecord) -> None:
        if record.state is LaneState.RUNNING:
            mine = batch.owner_machine == self._machine()
            stopped = mine and bool(self.executor.stop(record.run_id, StopReason.OPERATOR).get("stopped"))
            if not stopped:
                if not record.stop_requested:
                    line = self._lane_line(record.id, STOP_REQUESTED, {})
                    self.manifests.append(workspace_id, batch.id, [line], f"{batch.id}:{record.id}:stop_requested")
                receipts.emit("batch.stop_requested", workspace_id=workspace_id, batch_id=batch.id, lane=record.id)
                return
        state = move(LANE_MOVES, record.state, LaneEvent.STOP)
        source = self._source_for(workspace_id)
        who = Claimant.persona(record.persona or "")
        ending = RowEnding(Verdict.STOPPED, reason="operator stop")
        for ref in record.rows:
            try:
                ROW_ENDINGS[Verdict.STOPPED](source, ref, who, ending)
            except WorkRefused as refused:
                logger.warning("batch %s lane %s: release of %s refused %s", batch.id, record.id, ref.id,
                               refused.reason.value)
        line = self._lane_line(record.id, state, {"verdict": Verdict.STOPPED.value})
        self.manifests.append(workspace_id, batch.id, [line], f"{batch.id}:{self._request(batch, record)}:stopped")

    # ── land and approve: the operator's alone ───────────────────────────

    def land(self, workspace_id: str, batch_id: str, *, persona: str | None = None) -> Batch:
        batch = self.load(workspace_id, batch_id)
        self._own(batch)
        busy = self._landing_elsewhere(batch_id)
        if busy is not None:
            raise WorkRefused(Reason.LANDING_IN_PROGRESS, busy)
        state = move(BATCH_MOVES, batch.state, BatchEvent.LAND)
        who = persona or batch.landing.persona
        if not who:
            raise WorkRefused(Reason.PERSONA_UNRESOLVED, f"name a persona instance for {LANDING_ID}")
        attempt = batch.landing_attempt + 1
        lines = [self._batch_line(state, {"persona": who, "attempt": attempt}),
                 self._lane_line(LANDING_ID, LaneState.CLAIMED, {"rows": [], "persona": who})]
        self.manifests.append(workspace_id, batch_id, lines, f"{batch_id}:land:{attempt}")
        receipts.emit("batch.landing", workspace_id=workspace_id, batch_id=batch_id, attempt=attempt)
        return self.advance(workspace_id, batch_id)

    def approve(self, workspace_id: str, batch_id: str) -> Batch:
        batch = self.load(workspace_id, batch_id)
        self._own(batch)
        state = move(BATCH_MOVES, batch.state, BatchEvent.APPROVE)
        sha = self._lander.push(batch)
        self.manifests.append(workspace_id, batch_id, [self._batch_line(state, {"landing_sha": sha})],
                              f"{batch_id}:landed")
        receipts.emit("batch.landed", workspace_id=workspace_id, batch_id=batch_id, landing_sha=sha)
        return self.load(workspace_id, batch_id)

    # ── the tick and the lookups ─────────────────────────────────────────

    def tick(self) -> None:
        """Advance every batch this machine owns (lanes waiting on the budget, the box or a refusal)."""

        for workspace_id in self._workspaces():
            try:
                for batch_id, text in self.manifests.texts(workspace_id, fresh=False).items():
                    batch = fold(text)
                    if batch is not None and batch.owner_machine == self._machine() and batch.state in (
                            BatchState.STARTED, BatchState.LANDING):
                        self.advance(workspace_id, batch_id)
            except Exception:
                logger.warning("batch tick could not advance workspace %s", workspace_id, exc_info=True)

    def _find(self, batch_id: str) -> tuple[str, Batch] | None:
        for workspace_id in self._workspaces():
            if batch_id in self.manifests.texts(workspace_id, fresh=False):
                return workspace_id, self.load(workspace_id, batch_id)
        return None

    def _landing_elsewhere(self, batch_id: str) -> str | None:
        """Another batch this machine is landing, in any workspace (one landing at a time, plan §3.3)."""

        for workspace_id in self._workspaces():
            for key, text in self.manifests.texts(workspace_id, fresh=False).items():
                other = fold(text) if key != batch_id else None
                if other is not None and other.owner_machine == self._machine() and other.state in _HOLDING_LANDING:
                    return key
        return None

    def _own(self, batch: Batch) -> None:
        if batch.owner_machine != self._machine():
            raise WorkRefused(Reason.NOT_OWNER_MACHINE, f"{batch.id} is owned by {batch.owner_machine}")

    def _at(self) -> str:
        return _stamp(self._now())

    def _lane_line(self, lane_id: str, state: LaneState | str, data: Mapping[str, Any]) -> str:
        return entry_line(self._at(), LANE_PREFIX + lane_id, getattr(state, "value", state), data)

    def _batch_line(self, state: BatchState, data: Mapping[str, Any]) -> str:
        return entry_line(self._at(), BATCH_SUBJECT, state.value, data)


# ── the serve's defaults ───────────────────────────────────────────────────


def _roster(workspace_id: str) -> list[Member]:
    from ..persona_assignments.store import PersonaInstanceStore

    # The workspace's own instances first, then the runtime-global ones (workspace_id None) the
    # operator's free-floating chats run on; an instance of another workspace is never borrowed.
    found = [i for i in PersonaInstanceStore().list_all() if i.workspace_id in (workspace_id, None)]
    found.sort(key=lambda i: (i.workspace_id is None, i.id))
    return [Member(i.id, i.persona_id, i.role) for i in found]


def _slot_roles(workspace_id: str) -> dict[str, str]:
    from ..workspace_slots import live_slots, load_document

    return {name: str((slot.get("context") or {}).get("role") or "")
            for name, slot in live_slots(load_document(workspace_id)).items()}


def _budget(workspace_id: str) -> Budget:
    from ..work_store.engine import default_cap

    return Budget(max_lanes=default_cap(workspace_id))


def _this_machine() -> str:
    from ..workspace_slots import SlotRefused, machine_id

    try:
        return machine_id()
    except SlotRefused as exc:
        raise WorkRefused(Reason.MACHINE_UNIDENTIFIED, exc.detail) from exc


def _workspace_ids() -> list[str]:
    from ..work.service import workspace_ids

    return workspace_ids()


def default_dispatcher(*, executor: Executor | None = None, lander: Lander | None = None) -> BatchDispatcher:
    """The serve's dispatcher: the boards, the default brain's manifests, the persona-turn executor."""

    from ..work_store.persona_turn import PersonaTurnExecutor
    from .board_source import BoardSource
    from .manifest import BrainManifestStore

    return BatchDispatcher(source_for=BoardSource, manifests=BrainManifestStore(),
                           executor=executor or PersonaTurnExecutor(), machine=_this_machine, roster=_roster,
                           slot_roles=_slot_roles, budget_for=_budget, lander=lander, workspaces=_workspace_ids)
