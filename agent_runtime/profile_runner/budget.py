"""Run budgets: the wall-budget checkpoint, the tool-call guard, result-budget
enforcement and the budget-pressure warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Any, Callable

from agent_runtime import turn_budget
from agent_runtime.run_budget import (
    UNIT_CALLS,
    UNIT_TOKENS,
    RunBudgetEnforcement,
    RunBudgetKind,
    RunBudgetLedger,
    RunBudgetTripReason,
)
from agent_runtime.turn_budget import TurnWallBudget

from agent_runtime.profile_runner.errors import RunBudgetExceeded
from agent_runtime.profile_runner.models import (
    AgentRunRequest,
    AgentRunResult,
    _positive_int,
)

__layer__ = "policy"

__all__ = [
    "WallBudgetCheckpoint",
    "_ToolBudgetGuard",
    "_emit_budget_pressure_warning",
    "_enforce_result_budgets",
]


class WallBudgetCheckpoint:
    """Graceful end-of-turn checkpoint for a run's wall-clock budget.

    Retires the mid-API-call kill as the FIRST thing that happens when a turn
    runs out of wall clock (live incident 2026-07-26). When the reserved window
    opens — see ``turn_budget.checkpoint_reserve_seconds`` — this:

    1. steers a system-side nudge into the agent's next tool result, so the
       model is told, in-band, to produce its final checkpoint reply;
    2. drains the agent's iteration budget, so the tool-calling loop launches NO
       further tool executions and exits at its next iteration boundary. The
       upstream finalizer then takes exactly ONE toolless provider call — the
       final reply — using the mechanism it already has for iteration
       exhaustion. No upstream edit, no private attribute, no mid-flight abort
       of an already-running tool (aborting that is the very kill we replace).

    The old hard wall stays armed at the real deadline as the last resort: if
    even the final call cannot fit, the run still dies — but it dies with a
    typed ``wall_budget`` on the exception, so the turn settles as
    ``budget_exhausted`` instead of ``outcome_unknown``.

    Thread-safe and idempotent: the timer thread and the tool-start gate race
    freely; exactly one of them engages.
    """

    def __init__(
        self,
        budget: TurnWallBudget,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        clock: Callable[[], float] | None = None,
        ledger: RunBudgetLedger | None = None,
    ):
        self.budget = budget
        self._progress_callback = progress_callback
        self._clock = clock or time.time
        # The run's budget ledger, for accounting only — the checkpoint's own
        # decision path is untouched by it. Defaulted so a directly-constructed
        # checkpoint (tests, and any future caller) still records somewhere.
        self.ledger = ledger or RunBudgetLedger()
        self._lock = RLock()
        self._agent: Any | None = None
        self._engaged = False
        self._trigger: str | None = None
        self._remaining_at_engage: float | None = None
        self._iterations_drained = 0

    # -- wiring ---------------------------------------------------------
    def bind(self, agent: Any) -> None:
        """Bind the agent AFTER any resident-registry swap, so the nudge and the
        iteration drain land on the object that actually runs the turn."""
        with self._lock:
            self._agent = agent

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._engaged

    # -- decision -------------------------------------------------------
    def gate(self) -> bool:
        """Pre-work check: engage when the reserved window has opened.

        Called before each tool execution (via the tool-start progress seam) so
        the stop lands deterministically at a tool boundary rather than waiting
        on the timer thread. Returns True when new work may still start.
        """

        if self.engaged:
            return False
        if not self.budget.supports_checkpoint:
            return True
        if self.budget.may_start_new_work(now=self._clock()):
            return True
        self.engage(trigger=turn_budget.CHECKPOINT_TRIGGER_TOOL_GATE)
        return False

    def engage(self, *, trigger: str) -> bool:
        """Open the checkpoint exactly once. Returns True if this call did it."""

        with self._lock:
            if self._engaged or self._agent is None:
                return False
            self._engaged = True
            self._trigger = trigger
            self._remaining_at_engage = self.budget.remaining_seconds(now=self._clock())
            agent = self._agent
        nudge = turn_budget.checkpoint_nudge_text(self.budget, now=self._clock())
        steer = getattr(agent, "steer", None)
        if callable(steer):
            try:
                steer(nudge)
            except Exception:
                pass
        drained = turn_budget.drain_iteration_budget(agent)
        with self._lock:
            self._iterations_drained = drained
        # Accounting only — the wall bound LANDS the turn, and recording that
        # here is what makes "the reply you are reading is a checkpoint reply"
        # readable from the run record instead of only from the progress lane.
        self.ledger.trip(
            RunBudgetKind.WALL,
            RunBudgetTripReason.WALL_CHECKPOINT_ENGAGED,
            consumed=self.consumed_seconds(),
            detail=f"trigger={trigger}",
        )
        self._emit_progress()
        return True

    def consumed_seconds(self) -> float:
        """Wall spent so far, from the same budget the enforcement reads."""

        return max(0.0, self.budget.total_seconds - self.budget.remaining_seconds(now=self._clock()))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            block = self.budget.hud_block(now=self._clock())
            block.update(
                {
                    "engaged": self._engaged,
                    "trigger": self._trigger,
                    "iterations_reclaimed": self._iterations_drained,
                }
            )
            if self._remaining_at_engage is not None:
                block["remaining_at_checkpoint_seconds"] = round(
                    max(0.0, self._remaining_at_engage), 1
                )
            return block

    def _emit_progress(self) -> None:
        callback = self._progress_callback
        if callback is None:
            return
        try:
            callback(
                {
                    "type": "run.progress",
                    "phase": "wall_budget_checkpoint",
                    "severity": "warning",
                    "step": "wall_budget_checkpoint_opened",
                    "status": "warning",
                    "summary": (
                        "Wall budget nearly exhausted — no further tool calls will run; "
                        "asking the agent for a final checkpoint reply "
                        f"({self.budget.summary(now=self._clock())})."
                    ),
                    "wall_budget": self.summary(),
                }
            )
        except Exception:
            return


@dataclass(slots=True)
class _ToolBudgetGuard:
    repeated_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    warned: set[tuple[str, str]] = field(default_factory=set)
    # Wall-clock checkpoint consulted before each tool execution. Distinct from
    # the tool-count budgets above: those TRIP the run, this one lands it.
    wall_checkpoint: WallBudgetCheckpoint | None = None
    # The run's budget ledger. Accounting only: every enforcement decision below
    # is made exactly where it was before, then declared here.
    ledger: RunBudgetLedger = field(default_factory=RunBudgetLedger)

    @property
    def skill_warning_threshold(self) -> int:
        return 3


def _enforce_result_budgets(
    result: AgentRunResult,
    request: AgentRunRequest,
    *,
    ledger: RunBudgetLedger | None = None,
) -> None:
    """The two POST-run bounds. Same order, same messages, same exception.

    ``ledger`` is accounting only: each bound declares its limit and actual
    consumption whether or not it trips, so an operator can read the headroom of
    a turn that finished as easily as the bound of one that did not.
    """

    ledger = ledger if ledger is not None else RunBudgetLedger()
    max_api_calls = _positive_int(request.max_api_calls)
    if max_api_calls is not None:
        api_calls = _positive_int(result.api_calls)
        ledger.declare(
            RunBudgetKind.API_CALLS,
            enforcement=RunBudgetEnforcement.TRIPS_RUN,
            unit=UNIT_CALLS,
            limit=max_api_calls,
            consumed=api_calls,
        )
        if api_calls is not None and api_calls > max_api_calls:
            message = f"live run budget exceeded: api_calls={api_calls}/{max_api_calls}"
            ledger.trip(
                RunBudgetKind.API_CALLS,
                RunBudgetTripReason.API_CALLS_EXCEEDED,
                consumed=api_calls,
                detail=message,
            )
            raise RunBudgetExceeded(
                message, session_id=result.session_id, run_budget=ledger.accounting()
            )
    max_total_tokens = _positive_int(request.max_total_tokens)
    if max_total_tokens is not None:
        total_tokens = _positive_int(result.total_tokens)
        ledger.declare(
            RunBudgetKind.TOTAL_TOKENS,
            enforcement=RunBudgetEnforcement.TRIPS_RUN,
            unit=UNIT_TOKENS,
            limit=max_total_tokens,
            consumed=total_tokens,
        )
        if total_tokens is not None and total_tokens > max_total_tokens:
            message = f"live run budget exceeded: total_tokens={total_tokens}/{max_total_tokens}"
            ledger.trip(
                RunBudgetKind.TOTAL_TOKENS,
                RunBudgetTripReason.TOTAL_TOKENS_EXCEEDED,
                consumed=total_tokens,
                detail=message,
            )
            raise RunBudgetExceeded(
                message, session_id=result.session_id, run_budget=ledger.accounting()
            )


def _emit_budget_pressure_warning(result: AgentRunResult, request: AgentRunRequest) -> None:
    callback = request.progress_callback
    if callback is None:
        return
    max_total_tokens = _positive_int(request.max_total_tokens)
    total_tokens = _positive_int(result.total_tokens)
    if max_total_tokens is None or total_tokens is None:
        return
    if total_tokens > max_total_tokens:
        return
    threshold = int(max_total_tokens * 0.8)
    if total_tokens < threshold:
        return
    try:
        callback(
            {
                "type": "run.progress",
                "phase": "runaway_warning",
                "severity": "warning",
                "step": "budget_pressure",
                "status": "warning",
                "summary": "Run is approaching the live token budget; stop broad exploration and pivot to proof, a bounded handoff, or an exact blocker.",
                "budget_kind": "total_tokens",
                "budget_used": total_tokens,
                "budget_limit": max_total_tokens,
                "budget_ratio": round(total_tokens / max_total_tokens, 3),
                "next_expected": "proof_or_block_now",
            }
        )
    except Exception:
        return
