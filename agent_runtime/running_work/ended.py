"""Agent work that ended a moment ago: the retention window, the outcome words and the one
marker every agent lane applies to a row it keeps after the work settled.

RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE (review w1118a.58 D2): a chat turn, a
request (dispatch), a delegation or a background terminal that ended stays on the projection
for :data:`ENDED_RETENTION_SECONDS` — status ``completed`` (it finished) or ``error`` (it failed,
was stopped or was lost), its ``outcome`` and ``finished_at``, never a Stop — so Eternia's
Finished section reads one answer that survives an Eternia restart, the way an ended build
already does. The runtime is the one place that knows a row ended and how; a row that merely
vanishes cannot say stopped from done.

The outcome words are the build row's (``builds.vocabulary``): one vocabulary for "how did
this end" on the whole wire. Each lane reads its own store's words through one table here.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from ..builds.vocabulary import (
    FINISHED_RECORD_TTL_SECONDS,
    OUTCOME_FAILED,
    OUTCOME_LOST,
    OUTCOME_STOPPED,
    OUTCOME_SUCCEEDED,
)
from ..dispatch_store.models import STATE_CANCELLED, STATE_COMPLETED, STATE_ERROR, STATE_UNKNOWN
from ..mission_chat_turns.states import (
    SETTLING_TURN_STATES,
    TERMINAL_TURN_STATES,
    TURN_STATE_ABANDONED,
    TURN_STATE_BUDGET_EXHAUSTED,
    TURN_STATE_COMPLETED,
    TURN_STATE_FAILED,
    TURN_STATE_INTERRUPTED,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_PROJECTED,
    TURN_STATE_PROVIDER_REFUSED,
)
from .rows import _iso
from .vocabulary import KIND_CHAT_TURN, KIND_DELEGATION, KIND_DISPATCH, KIND_TERMINAL, STATUS_COMPLETED, STATUS_ERROR

__layer__ = "policy"


#: How long ended agent work stays listed: the same window a finished build record keeps
#: (``builds.vocabulary.FINISHED_RECORD_TTL_SECONDS``, 30 min) — one number for "recently ended".
ENDED_RETENTION_SECONDS = FINISHED_RECORD_TTL_SECONDS
#: Per-lane bound on ended rows, newest first, so ended work never crowds running work out of
#: the lane's own cap (``vocabulary._MAX_ROWS_PER_SOURCE``).
MAX_ENDED_ROWS_PER_LANE = 50

#: The kinds whose lanes keep ended rows (a build keeps its own, through its registry's expiry).
ENDED_KINDS = frozenset({KIND_CHAT_TURN, KIND_DISPATCH, KIND_DELEGATION, KIND_TERMINAL})

#: The turn journal's settled states → outcome. ``native_committed`` is a reply that is durable
#: and only awaits its projection: the work is done.
OUTCOME_BY_TURN_STATE: Mapping[str, str] = MappingProxyType({
    TURN_STATE_PROJECTED: OUTCOME_SUCCEEDED,
    TURN_STATE_COMPLETED: OUTCOME_SUCCEEDED,
    TURN_STATE_NATIVE_COMMITTED: OUTCOME_SUCCEEDED,
    TURN_STATE_INTERRUPTED: OUTCOME_STOPPED,
    TURN_STATE_ABANDONED: OUTCOME_STOPPED,
    TURN_STATE_FAILED: OUTCOME_FAILED,
    TURN_STATE_BUDGET_EXHAUSTED: OUTCOME_FAILED,
    TURN_STATE_PROVIDER_REFUSED: OUTCOME_FAILED,
})
#: The dispatch store's terminal states → outcome.
OUTCOME_BY_DISPATCH_STATE: Mapping[str, str] = MappingProxyType({
    STATE_COMPLETED: OUTCOME_SUCCEEDED,
    STATE_CANCELLED: OUTCOME_STOPPED,
    STATE_ERROR: OUTCOME_FAILED,
    STATE_UNKNOWN: OUTCOME_LOST,
})
#: The delegation store's settled record words (``tools.async_delegation``) → outcome.
OUTCOME_BY_DELEGATION_STATE: Mapping[str, str] = MappingProxyType({
    "completed": OUTCOME_SUCCEEDED,
    "ok": OUTCOME_SUCCEEDED,
    "success": OUTCOME_SUCCEEDED,
    "interrupted": OUTCOME_STOPPED,
    "cancelled": OUTCOME_STOPPED,
    "error": OUTCOME_FAILED,
    "failed": OUTCOME_FAILED,
    "unknown": OUTCOME_LOST,
})
#: A terminal receipt's ``completion_reason`` (``tools.process_registry.ProcessSession``) → outcome;
#: ``exited`` and ``already_exited`` are decided by the exit code (:func:`terminal_outcome`).
OUTCOME_BY_COMPLETION_REASON: Mapping[str, str] = MappingProxyType({
    "killed": OUTCOME_STOPPED,
    "lost": OUTCOME_LOST,
    "failed_start": OUTCOME_FAILED,
})

#: Every turn state a settled-turn read lists (``mission_chat_turns.reads.settled_turn_rows``).
ENDED_TURN_STATES = frozenset(TERMINAL_TURN_STATES | SETTLING_TURN_STATES)
if ENDED_TURN_STATES != frozenset(OUTCOME_BY_TURN_STATE):  # a new settled state must name its outcome
    raise RuntimeError("OUTCOME_BY_TURN_STATE does not cover the settled turn states")


def ended_since(now: float) -> float:
    """The epoch before which ended work has left the projection."""

    return now - ENDED_RETENTION_SECONDS


def terminal_outcome(completion_reason: Any, exit_code: Any) -> str:
    """A finished background process's outcome: how it ended, else its exit code."""

    named = OUTCOME_BY_COMPLETION_REASON.get(str(completion_reason or ""))
    if named is not None:
        return named
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return OUTCOME_SUCCEEDED if exit_code == 0 else OUTCOME_FAILED
    return OUTCOME_LOST


def mark_ended(
    row: dict[str, Any], *, outcome: str, finished: float | None, started: float | None = None
) -> dict[str, Any]:
    """Turn a lane's row into an ended one, in place: status, ``outcome``, ``finished_at``, no Stop.

    ``completed`` only for work that finished; anything else that ended is ``error`` with its
    outcome saying which (stopped, failed, lost). ``elapsed_seconds`` is the work's own span when
    both ends are known, never a clock still running.
    """

    row["status"] = STATUS_COMPLETED if outcome == OUTCOME_SUCCEEDED else STATUS_ERROR
    row["outcome"] = outcome
    row["finished_at"] = _iso(finished)
    row["cancellable"] = False
    if finished is not None and started is not None:
        row["elapsed_seconds"] = int(max(0.0, finished - started))
    return row


def is_ended(row: dict[str, Any]) -> bool:
    """Whether a row is ended agent work :func:`mark_ended` marked (the cancel door refuses it)."""

    return row.get("kind") in ENDED_KINDS and bool(row.get("finished_at")) and bool(row.get("outcome"))
