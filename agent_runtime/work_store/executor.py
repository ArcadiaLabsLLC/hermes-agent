"""The EXECUTOR contract — who runs a claimed row (dispatcher plan §2.2; work plan §6.3, W3).

W3 created this file with one production implementation, ``persona_turn.PersonaTurnExecutor``;
the dispatcher's B3 extended it (``goal_mode=UNTIL_DONE`` runs, ``Brief.tests`` become goal gates)
and B5 adds ``BATCH_LANE``. Every method
returns a value or raises ``WorkRefused(reason)``; ``can_start`` answers the refusal instead of
raising, because it is the cheap probe the engine asks before it writes a run record.

A ``Run`` is identified by ``run_id``, which the executor derives from where the run lives so that
``status`` needs no memory of ``start`` (a serve that restarted still answers it). ``Run.assignment``
is ``None`` only for a run rebuilt from durable state after a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .grammar import RowRef
from .models import Brief, GateReceipt, Verdict
from .reasons import Reason

__layer__ = "lanes"
__all__ = [
    "REFUSALS",
    "Assignment",
    "Brief",
    "Executor",
    "ExecutorKind",
    "GoalMode",
    "Outcome",
    "RowEnding",
    "Run",
    "RunStatus",
    "StopReason",
    "Verdict",
]


#: Every refusal an EXECUTOR may answer or raise (plan §2.2; B1 named the set).
REFUSALS: frozenset[Reason] = frozenset({
    Reason.EXECUTOR_BUSY, Reason.PERSONA_UNAVAILABLE, Reason.CAP_REACHED, Reason.DRAIN_BEGUN,
    Reason.DOOR_UNBOUND, Reason.WORKTREE_FAILED,
})


class ExecutorKind(StrEnum):
    PERSONA_TURN = "persona_turn"
    BATCH_LANE = "batch_lane"


class GoalMode(StrEnum):
    NONE = "none"
    UNTIL_DONE = "until_done"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SETTLED = "settled"
    STOPPED = "stopped"


class StopReason(StrEnum):
    OPERATOR = "operator"
    DRAIN = "drain"
    CAP = "cap"


@dataclass(frozen=True)
class Assignment:
    rows: tuple[RowRef, ...]
    persona_instance_id: str
    brief: Brief
    request_id: str
    heavy: bool = False
    goal_mode: GoalMode = GoalMode.NONE
    #: Gates from ``brief.tests`` for an ``UNTIL_DONE`` goal — on by default (owner ruling 2026-10-18).
    goal_gates: bool = True
    #: Skills the row(s) lend the run (``skills:`` segment; a lane's union) — derived, never a second store.
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class RowEnding:
    verdict: Verdict
    result: str = ""
    question: str = ""
    recommend: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    per_row: Mapping[RowRef, RowEnding] = field(default_factory=dict)
    report: str = ""
    tool_calls: int | None = None
    commits: tuple[str, ...] = ()
    #: The landing lane's code-run gate, one receipt per slot (``batch.gate.GateRunner``); empty for a work lane.
    gates: tuple[GateReceipt, ...] = ()


@dataclass(frozen=True)
class Run:
    run_id: str
    request_id: str
    assignment: Assignment | None
    root_session_id: str
    client_message_id: str
    started_at: str
    status: RunStatus


class Executor(Protocol):
    kind: ExecutorKind

    def can_start(self, a: Assignment) -> Reason | None:
        """Cheap and side-effect free: the refusal ``start`` would meet, or None."""

    def start(self, a: Assignment) -> Run:
        """Exactly one Run per ``request_id``: a second call with the same id returns the same run."""

    def status(self, run_id: str) -> RunStatus:
        """Where the run is now, read from durable state."""

    def stop(self, run_id: str, reason: StopReason) -> dict[str, Any]:
        """Stop a run that has not begun; a running turn is waited on (``stopped: False``). The receipt."""

    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None:
        """Register the one callback a settled run is reported to."""
