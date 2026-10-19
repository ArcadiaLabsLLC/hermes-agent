"""The batch → lane → landing state machine (dispatcher plan §3.2, §3.3), as tables. Pure.

``BATCH_MOVES`` and ``LANE_MOVES`` are the only transitions; any other is ``state_transition_invalid``.
``LANDED`` is reachable from ``AWAITING_APPROVAL`` alone, by ``APPROVE`` — the owner's push to ``main`` —
and nothing automates ``LAND`` or ``APPROVE`` (``AUTOMATABLE``; owner ruling 2026-10-18).

The tree, where it differs from the plan's table: a lane is ``PLANNED`` between the manifest's
``STARTED`` line and its rows' claims (a start that crashed half way resumes there); a landing lane
that does not report green moves the batch back to ``READY_TO_LAND`` (``LANDING_RED``), so the
operator can land again — the plan's table names no red edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, TypeVar

from ..work_store.grammar import RowRef
from ..work_store.models import GateReceipt, Verdict
from ..work_store.reasons import Reason, WorkRefused
from .planner import Budget, Lane, LaneKind

__layer__ = "policy"
__all__ = [
    "AUTOMATABLE",
    "BATCH_MOVES",
    "LANE_MOVES",
    "LIVE",
    "Automation",
    "Batch",
    "BatchAction",
    "BatchEvent",
    "BatchState",
    "LaneEvent",
    "LaneRecord",
    "LaneState",
    "automation_allows",
    "move",
    "ready_to_land",
    "startable",
]


class BatchState(StrEnum):
    PLANNED = "PLANNED"
    STARTED = "STARTED"
    READY_TO_LAND = "READY_TO_LAND"
    LANDING = "LANDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    LANDED = "LANDED"
    ABORTED = "ABORTED"


class BatchEvent(StrEnum):
    START = "start"
    LANES_SETTLED = "lanes_settled"
    LAND = "land"
    LANDING_GREEN = "landing_green"
    LANDING_RED = "landing_red"
    APPROVE = "approve"
    ABORT = "abort"


class LaneState(StrEnum):
    PLANNED = "PLANNED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    REPORTED = "REPORTED"
    STOPPED = "STOPPED"


class LaneEvent(StrEnum):
    CLAIM = "claim"
    RUN = "run"
    REPORT = "report"
    STOP = "stop"


_ABORTABLE = (BatchState.STARTED, BatchState.READY_TO_LAND, BatchState.LANDING, BatchState.AWAITING_APPROVAL)

BATCH_MOVES: dict[tuple[BatchState, BatchEvent], BatchState] = {
    (BatchState.PLANNED, BatchEvent.START): BatchState.STARTED,
    (BatchState.STARTED, BatchEvent.LANES_SETTLED): BatchState.READY_TO_LAND,
    (BatchState.READY_TO_LAND, BatchEvent.LAND): BatchState.LANDING,
    (BatchState.LANDING, BatchEvent.LANDING_GREEN): BatchState.AWAITING_APPROVAL,
    (BatchState.LANDING, BatchEvent.LANDING_RED): BatchState.READY_TO_LAND,
    (BatchState.AWAITING_APPROVAL, BatchEvent.APPROVE): BatchState.LANDED,
    **{(state, BatchEvent.ABORT): BatchState.ABORTED for state in _ABORTABLE},
}

LANE_MOVES: dict[tuple[LaneState, LaneEvent], LaneState] = {
    (LaneState.PLANNED, LaneEvent.CLAIM): LaneState.CLAIMED,
    (LaneState.PLANNED, LaneEvent.STOP): LaneState.STOPPED,
    (LaneState.CLAIMED, LaneEvent.RUN): LaneState.RUNNING,
    (LaneState.CLAIMED, LaneEvent.STOP): LaneState.STOPPED,
    (LaneState.RUNNING, LaneEvent.REPORT): LaneState.REPORTED,
    (LaneState.RUNNING, LaneEvent.STOP): LaneState.STOPPED,
}

#: A batch in one of these still holds (or may hold) claims and runs lanes.
LIVE = frozenset({BatchState.STARTED, BatchState.READY_TO_LAND, BatchState.LANDING, BatchState.AWAITING_APPROVAL})
_SETTLED = frozenset({LaneState.REPORTED, LaneState.STOPPED})

S = TypeVar("S", BatchState, LaneState)


def move(table: Mapping[tuple[S, Any], S], state: S, event: StrEnum) -> S:
    """The state ``event`` moves ``state`` to, or ``state_transition_invalid``."""

    nxt = table.get((state, event))
    if nxt is None:
        raise WorkRefused(Reason.STATE_TRANSITION_INVALID, f"{state.value} --{event.value}-->")
    return nxt


# ── automation (plan §3.3) ─────────────────────────────────────────────────


class Automation(StrEnum):
    OFF = "off"
    PLAN = "plan"
    START = "start"


class BatchAction(StrEnum):
    """The operator's manual points (plan §3.3); ``LAND`` and ``APPROVE`` are never automated."""

    PLAN = "plan"
    START = "start"
    STOP = "stop"
    LAND = "land"
    APPROVE = "approve"


#: What a scheduler fire may do at each ``batch_automation`` level; land and approve appear at none.
AUTOMATABLE: dict[Automation, frozenset[BatchAction]] = {
    Automation.OFF: frozenset(),
    Automation.PLAN: frozenset({BatchAction.PLAN}),
    Automation.START: frozenset({BatchAction.PLAN, BatchAction.START}),
}


def automation_allows(level: Automation, action: BatchAction) -> None:
    """Refuse ``automation_off`` unless the workspace's level lets a scheduler fire do ``action``."""

    if action not in AUTOMATABLE[level]:
        raise WorkRefused(Reason.AUTOMATION_OFF, f"batch_automation={level.value} does not automate {action.value}")


# ── the folded batch ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class LaneRecord:
    """A lane as its manifest lines fold: the planned lane plus where it is now."""

    lane: Lane
    state: LaneState = LaneState.PLANNED
    persona: str | None = None
    rows: tuple[RowRef, ...] = ()
    run_id: str = ""
    stop_requested: bool = False
    verdict: Verdict | None = None
    tool_calls: int | None = None
    commits: tuple[str, ...] = ()
    done_rows: int = 0

    @property
    def id(self) -> str:
        return self.lane.id

    def wire(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.lane.kind.value, "state": self.state.value, "persona": self.persona,
                "rows": [[r.slot, r.note, r.id] for r in self.rows], "run_id": self.run_id or None,
                "stop_requested": self.stop_requested, "verdict": self.verdict.value if self.verdict else None,
                "tool_calls": self.tool_calls, "commits": list(self.commits), "done_rows": self.done_rows,
                "heavy": self.lane.heavy, "quiet_box": self.lane.quiet_box, "after": list(self.lane.after),
                "effort": self.lane.effort,
                "domain": None if self.lane.domain is None else [
                    self.lane.domain.slot, self.lane.domain.note, self.lane.domain.heading]}


@dataclass(frozen=True)
class Batch:
    id: str
    workspace_id: str
    owner_machine: str
    state: BatchState
    lanes: tuple[LaneRecord, ...]
    landing: LaneRecord
    budget: Budget
    landing_attempt: int = 0
    gate: str = ""
    landing_sha: str = ""
    #: The current landing attempt's code-run gate, one receipt per slot (``gate.GateRunner``).
    gate_receipts: tuple[GateReceipt, ...] = ()

    def lane(self, lane_id: str) -> LaneRecord:
        found = next((lane for lane in (*self.lanes, self.landing) if lane.id == lane_id), None)
        if found is None:
            raise WorkRefused(Reason.BATCH_MISSING, f"{self.id} has no lane {lane_id}")
        return found

    def with_lane(self, record: LaneRecord) -> Batch:
        if record.lane.kind is LaneKind.LANDING:
            return replace(self, landing=record)
        return replace(self, lanes=tuple(record if lane.id == record.id else lane for lane in self.lanes))

    def wire(self) -> dict[str, Any]:
        return {"id": self.id, "workspace_id": self.workspace_id, "owner_machine": self.owner_machine,
                "state": self.state.value, "lanes": [lane.wire() for lane in self.lanes],
                "landing": self.landing.wire(), "budget": self.budget.wire(),
                "landing_attempt": self.landing_attempt, "gate": self.gate, "landing_sha": self.landing_sha or None,
                "gate_receipts": [g.wire() for g in self.gate_receipts]}


# ── the rules ──────────────────────────────────────────────────────────────


def startable(batch: Batch, budget: Budget, *, box_idle: bool) -> tuple[list[LaneRecord], list[LaneRecord]]:
    """(lanes to start now, quiet-box lanes waiting for an idle box) under the budget (plan §3.3).

    A lane starts when it is ``CLAIMED``, every lane it is ``after`` has settled, a slot is free
    (``max_lanes``), and its weight allows: a heavy lane only when no heavy lane and no landing runs,
    a light lane only under ``light_at_once``.
    """

    running = [lane for lane in batch.lanes if lane.state is LaneState.RUNNING]
    landing_runs = batch.landing.state is LaneState.RUNNING
    settled = {lane.id for lane in batch.lanes if lane.state in _SETTLED}
    start: list[LaneRecord] = []
    waiting: list[LaneRecord] = []
    for lane in batch.lanes:
        if lane.state is not LaneState.CLAIMED or not set(lane.lane.after) <= settled:
            continue
        live = running + start
        if len(live) >= budget.max_lanes:
            break
        heavy_now = sum(1 for other in live if other.lane.heavy)
        if lane.lane.heavy and (heavy_now >= budget.heavy_at_once or landing_runs):
            continue
        if not lane.lane.heavy and len(live) - heavy_now >= budget.light_at_once:
            continue
        if lane.lane.quiet_box and not box_idle:
            waiting.append(lane)
            continue
        start.append(lane)
    return start, waiting


def _has_work(lane: LaneRecord) -> bool:
    return bool(lane.commits) or lane.done_rows > 0


def ready_to_land(lanes: Sequence[LaneRecord]) -> bool:
    """Every lane settled and at least one carries work (plan §3.2 ``READY_TO_LAND``)."""

    return bool(lanes) and all(lane.state in _SETTLED for lane in lanes) and any(map(_has_work, lanes))
