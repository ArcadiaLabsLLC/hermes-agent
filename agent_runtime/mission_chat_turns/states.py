"""The turn-lifecycle vocabulary: the states, the buckets, the decision sets, the table.

VOCABULARY/TABLE module (floor-exempt — sheet ``mission_chat_turns.md`` §1). It
holds the turn states, the three lifecycle buckets, the three decision sets,
the journal transition table with the import-time guard that fails the import
when any of them rot, ``next_turn_state`` (the one transition authority) and the
two state readers. Imports nothing in its package.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from agent_runtime.serde import safe_assignment_token

__layer__ = "models"


# ═══ turn-lifecycle vocabulary — ONE table, and it decides everything ═══════
#
# This module OWNS the turn states. Every consumer — in this file, in the
# history projection, in the operator-conversation contract, in the CLI chat
# lane — asks this table instead of re-spelling a state literal.
#
# The rule exists because the same defect landed twice, ~700 lines apart. Both
# times a consumer wrote "which turn states are over" as its own string:
# ``state != "interrupted"`` in the marker synthesizer and again in the
# tool-call settler. When ``budget_exhausted`` was added (2026-07-26) neither
# spelling knew about it, so a turn that had been over for minutes still
# rendered a live spinner in the cockpit. Recurrence was the finding: the bug
# is not either literal, it is that a consumer was free to invent one. Adding
# a state must extend a TABLE here, never require finding every comparison.
#
# ── the states ──────────────────────────────────────────────────────────────
# Journal states — the exactly-once lane driven by
# ``transition_mission_chat_turn``.
TURN_STATE_PENDING = "pending"
TURN_STATE_EXECUTING = "executing"
TURN_STATE_OUTCOME_UNKNOWN = "outcome_unknown"
TURN_STATE_NATIVE_COMMITTED = "native_committed"
TURN_STATE_PROJECTED = "projected"
TURN_STATE_ABANDONED = "abandoned"
# Wall-budget terminal (2026-07-26). A turn that ran out of wall clock is NOT
# an ambiguous provider outcome — the harness knows exactly why it stopped — so
# it settles here instead of freezing at ``outcome_unknown`` and demanding an
# operator ``turn-resolve --action abandon``. Terminal, needs no resolution,
# and never blocks the next send.
TURN_STATE_BUDGET_EXHAUSTED = "budget_exhausted"
# Provider-refusal terminal (2026-09-11). The PROVIDER authored a definite "this
# request did not run" — a plan quota wall, a rejected credential, a model the
# account cannot reach. Like ``budget_exhausted``, and for the same reason, it
# is NOT an ambiguous provider outcome: there is no turn to prove either way, so
# it settles here instead of freezing at ``outcome_unknown`` and demanding an
# operator ``turn-resolve --action abandon`` for a request that never ran.
#
# A JOURNAL state rather than the legacy ``failed``: ``failed`` belongs to the
# pre-journal streaming vocabulary, ``next_turn_state`` refuses a journal ->
# legacy write by construction, and a legacy state carries none of the
# lifecycle-set membership this one needs.
TURN_STATE_PROVIDER_REFUSED = "provider_refused"
# Legacy streaming vocabulary. Written by the pre-journal persist lane and by
# the repair sweep; never produced by ``transition_mission_chat_turn``.
TURN_STATE_RUNNING = "running"
TURN_STATE_COMPLETED = "completed"
TURN_STATE_FAILED = "failed"
TURN_STATE_INTERRUPTED = "interrupted"

JOURNAL_TURN_STATES = frozenset(
    {
        TURN_STATE_PENDING,
        TURN_STATE_EXECUTING,
        TURN_STATE_OUTCOME_UNKNOWN,
        TURN_STATE_NATIVE_COMMITTED,
        TURN_STATE_PROJECTED,
        TURN_STATE_ABANDONED,
        TURN_STATE_BUDGET_EXHAUSTED,
        TURN_STATE_PROVIDER_REFUSED,
    }
)
LEGACY_TURN_STATES = frozenset(
    {
        TURN_STATE_RUNNING,
        TURN_STATE_COMPLETED,
        TURN_STATE_FAILED,
        TURN_STATE_INTERRUPTED,
    }
)
# The known universe. A state outside it is not a turn state and is rejected at
# the store boundary (``_safe_turn_state``).
ALL_TURN_STATES = JOURNAL_TURN_STATES | LEGACY_TURN_STATES

# ── lifecycle buckets: every known state belongs to EXACTLY one ─────────────
# A record here has an executor that has not settled it: the legacy streaming
# state plus every non-terminal journal state. Retention never evicts them, GC
# never archives their session file, and the stale-turn repairs (next-send +
# serve-boot orphan sweep) flip exactly this set. ``budget_exhausted`` is
# deliberately ABSENT: it is settled, so no repair may reopen it and no sweep
# may flip it to ``interrupted``.
INFLIGHT_TURN_STATES = frozenset(
    {
        TURN_STATE_RUNNING,
        TURN_STATE_PENDING,
        TURN_STATE_EXECUTING,
        TURN_STATE_OUTCOME_UNKNOWN,
    }
)
# The provider's reply is durable but the Mission Control projection has not
# committed yet. NEITHER in-flight (a repair flip here would destroy a recorded
# reply) NOR terminal (the projection walk still owes work). This bucket had no
# name before the consolidation — ``native_committed`` simply fell out of both
# sets, which is exactly the kind of silent gap the coverage guard below now
# makes impossible to reintroduce.
SETTLING_TURN_STATES = frozenset({TURN_STATE_NATIVE_COMMITTED})
# States that are settled and require NO operator resolution. ``turn-resolve``
# still accepts only ``outcome_unknown`` (the genuinely ambiguous case).
TERMINAL_TURN_STATES = frozenset(
    {
        TURN_STATE_PROJECTED,
        TURN_STATE_ABANDONED,
        TURN_STATE_BUDGET_EXHAUSTED,
        TURN_STATE_PROVIDER_REFUSED,
        TURN_STATE_COMPLETED,
        TURN_STATE_FAILED,
        TURN_STATE_INTERRUPTED,
    }
)

# ── decision sets: what a consumer actually asks ────────────────────────────
# A resend of the SAME client_message_id that finds a durable reply already in
# SessionDB promotes the record to ``native_committed`` from these states — the
# reply is proven, so it must be projected rather than lost. Read by the CLI
# chat lane; mirrors the ``native_committed`` column of ``_JOURNAL_TRANSITIONS``
# (guarded below).
REPLY_RECOVERABLE_TURN_STATES = frozenset(
    {
        TURN_STATE_EXECUTING,
        TURN_STATE_OUTCOME_UNKNOWN,
        TURN_STATE_BUDGET_EXHAUSTED,
        # A provider refusal means nothing ran, so there should be no reply to
        # recover. It is listed anyway, exactly as ``budget_exhausted`` is:
        # the house rule is that a reply PROVEN durable in SessionDB is never
        # lost to a state flip, and a rule with an exception is a rule someone
        # has to remember.
        TURN_STATE_PROVIDER_REFUSED,
    }
)
# ...and with no such proof, a resend from these states is REFUSED: the prior
# provider outcome cannot be proven, so the operator must resolve the turn
# first. ``budget_exhausted`` is deliberately absent — it is settled, gets its
# own honest refusal, and never routes anyone to ``turn-resolve``.
RESEND_BLOCKING_TURN_STATES = frozenset(
    {TURN_STATE_EXECUTING, TURN_STATE_OUTCOME_UNKNOWN}
)
# The only states ``turn-resolve --action abandon`` accepts: the genuinely
# ambiguous provider outcome, and nothing else.
OPERATOR_RESOLVABLE_TURN_STATES = frozenset({TURN_STATE_OUTCOME_UNKNOWN})

# A legacy record entering the journal lane is read as its journal equivalent.
_LEGACY_TO_JOURNAL_STATE = {
    TURN_STATE_RUNNING: TURN_STATE_PENDING,
    TURN_STATE_COMPLETED: TURN_STATE_PROJECTED,
}
_JOURNAL_TRANSITIONS = {
    None: {TURN_STATE_PENDING},
    TURN_STATE_PENDING: {
        TURN_STATE_PENDING,
        TURN_STATE_EXECUTING,
        TURN_STATE_ABANDONED,
        TURN_STATE_BUDGET_EXHAUSTED,
    },
    TURN_STATE_EXECUTING: {
        TURN_STATE_NATIVE_COMMITTED,
        TURN_STATE_OUTCOME_UNKNOWN,
        TURN_STATE_BUDGET_EXHAUSTED,
        TURN_STATE_PROVIDER_REFUSED,
    },
    TURN_STATE_OUTCOME_UNKNOWN: {
        TURN_STATE_ABANDONED,
        TURN_STATE_NATIVE_COMMITTED,
        TURN_STATE_BUDGET_EXHAUSTED,
    },
    # A durable reply proven AFTER the budget settled the turn still wins — the
    # same legacy-interrupted convention that lets ``outcome_unknown`` promote
    # to ``native_committed`` (a recorded reply must never be lost to a repair
    # flip). Nothing else may leave this state: it does not resurrect to
    # ``pending``, so a retry uses a NEW client_message_id like any other
    # settled turn.
    TURN_STATE_BUDGET_EXHAUSTED: {
        TURN_STATE_BUDGET_EXHAUSTED,
        TURN_STATE_NATIVE_COMMITTED,
    },
    # Same shape as the budget row above, and for the same two reasons: a
    # repeated settle after a crash must be safe, and a reply proven durable
    # still wins. Nothing else leaves it — a retry uses a NEW
    # client_message_id, like every other settled turn.
    TURN_STATE_PROVIDER_REFUSED: {
        TURN_STATE_PROVIDER_REFUSED,
        TURN_STATE_NATIVE_COMMITTED,
    },
    TURN_STATE_NATIVE_COMMITTED: {TURN_STATE_NATIVE_COMMITTED, TURN_STATE_PROJECTED},
    TURN_STATE_PROJECTED: {TURN_STATE_PROJECTED},
    TURN_STATE_ABANDONED: {TURN_STATE_ABANDONED},
}


# ── import-time contract guards ─────────────────────────────────────────────
#
# Raised, not asserted, so ``python -O`` cannot strip the contract (same
# convention as ``persona_chat_history.TERMINAL_TURN_MARKERS``). Each guard
# encodes a failure that has already cost real time: a state nobody classified
# (the wall-budget spinner), a decision set naming a state the store cannot
# hold (a typo that silently never matches), or a transition table drifting
# away from the decision set derived from it.
def _guard_turn_state_vocabulary() -> None:  # pragma: no cover - import contract
    buckets = {
        "INFLIGHT_TURN_STATES": INFLIGHT_TURN_STATES,
        "SETTLING_TURN_STATES": SETTLING_TURN_STATES,
        "TERMINAL_TURN_STATES": TERMINAL_TURN_STATES,
    }
    decisions = {
        "REPLY_RECOVERABLE_TURN_STATES": REPLY_RECOVERABLE_TURN_STATES,
        "RESEND_BLOCKING_TURN_STATES": RESEND_BLOCKING_TURN_STATES,
        "OPERATOR_RESOLVABLE_TURN_STATES": OPERATOR_RESOLVABLE_TURN_STATES,
    }
    for name, states in {**buckets, **decisions}.items():
        unknown = sorted(states - ALL_TURN_STATES)
        if unknown:
            raise RuntimeError(f"{name} names non-existent turn state(s): {unknown}")

    # Exactly one bucket per state: pairwise disjoint...
    names = sorted(buckets)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = sorted(buckets[left] & buckets[right])
            if overlap:
                raise RuntimeError(
                    f"turn state(s) in both {left} and {right}: {overlap}"
                )
    # ...and no state left behind. An unclassified state is the wall-budget
    # spinner waiting to happen again.
    unclassified = sorted(ALL_TURN_STATES - set().union(*buckets.values()))
    if unclassified:
        raise RuntimeError(
            "turn state(s) belong to no lifecycle bucket: " f"{unclassified}"
        )

    # The refusal ladder narrows: what an operator may resolve is a subset of
    # what blocks a resend, which is a subset of what a proven reply recovers.
    if not (
        OPERATOR_RESOLVABLE_TURN_STATES
        <= RESEND_BLOCKING_TURN_STATES
        <= REPLY_RECOVERABLE_TURN_STATES
    ):
        raise RuntimeError(
            "turn-state refusal ladder is not nested: "
            f"resolvable={sorted(OPERATOR_RESOLVABLE_TURN_STATES)} "
            f"blocking={sorted(RESEND_BLOCKING_TURN_STATES)} "
            f"recoverable={sorted(REPLY_RECOVERABLE_TURN_STATES)}"
        )
    # ``REPLY_RECOVERABLE`` is a VIEW of the transition table, not a second
    # opinion: it must be exactly the states from which the journal accepts a
    # promotion to ``native_committed``, minus that state itself (a record
    # already there has nothing to recover).
    derived = {
        state
        for state, allowed in _JOURNAL_TRANSITIONS.items()
        if state is not None
        and state != TURN_STATE_NATIVE_COMMITTED
        and TURN_STATE_NATIVE_COMMITTED in allowed
    }
    if derived != REPLY_RECOVERABLE_TURN_STATES:
        raise RuntimeError(
            "REPLY_RECOVERABLE_TURN_STATES disagrees with _JOURNAL_TRANSITIONS: "
            f"table={sorted(derived)} set={sorted(REPLY_RECOVERABLE_TURN_STATES)}"
        )

    # The transition table and the legacy alias map may only name real states.
    for state, allowed in _JOURNAL_TRANSITIONS.items():
        if state is not None and state not in JOURNAL_TURN_STATES:
            raise RuntimeError(f"_JOURNAL_TRANSITIONS keys a non-journal state: {state}")
        unknown = sorted(allowed - JOURNAL_TURN_STATES)
        if unknown:
            raise RuntimeError(
                f"_JOURNAL_TRANSITIONS[{state}] targets non-journal state(s): {unknown}"
            )
    for legacy, journal in _LEGACY_TO_JOURNAL_STATE.items():
        if legacy not in LEGACY_TURN_STATES or journal not in JOURNAL_TURN_STATES:
            raise RuntimeError(
                f"_LEGACY_TO_JOURNAL_STATE maps {legacy!r} -> {journal!r}, "
                "which is not legacy -> journal"
            )


_guard_turn_state_vocabulary()


class MissionChatTurnPersistOutcome(str, Enum):
    """Typed result of a turn-record persist. No write is ever lost silently:
    every skipped or rejected persist names its reason."""

    PERSISTED = "persisted"
    SKIPPED_NO_KEYS = "skipped_no_keys"
    SKIPPED_EMPTY_LEGACY = "skipped_empty_legacy"
    REJECTED_INVALID_STATE = "rejected_invalid_state"
    REJECTED_STALE_TRANSITION = "rejected_stale_transition"
    SKIPPED_LOCK_TIMEOUT = "skipped_lock_timeout"


def next_turn_state(
    current: str | None,
    requested: str | None,
    *,
    write_ahead: bool = False,
) -> str | None:
    """Single transition authority for turn-record states.

    Returns the state to store, or ``None`` when the write must be rejected.
    Rules:
    - ``requested=None`` (legacy elements-only call) preserves the current
      state; a brand-new record defaults to ``running``.
    - Explicit terminal states (``completed``/``failed``) and the repair state
      (``interrupted``) always win — a completed reply recorded after a
      repair flip must not be lost.
    - ``running`` with ``write_ahead=True`` is a fresh turn start (same-client
      retry after an interrupted/failed turn) and always wins.
    - ``running`` with ``write_ahead=False`` is an incremental on_update flush
      and must NOT resurrect a settled record: a late flush from a turn that
      another process already repaired to ``interrupted`` (or that completed)
      is stale and is rejected.
    """

    if current in JOURNAL_TURN_STATES and requested in LEGACY_TURN_STATES:
        return None
    if requested is None:
        return current or TURN_STATE_RUNNING
    if requested not in ALL_TURN_STATES:
        return None
    if requested != TURN_STATE_RUNNING:
        return requested
    if write_ahead or current is None or current == TURN_STATE_RUNNING:
        return TURN_STATE_RUNNING
    return None


def _safe_turn_state(value: Any) -> str | None:
    state = safe_assignment_token(value)
    return state if state in ALL_TURN_STATES else None


def _record_state(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    state = _safe_turn_state(record.get("state"))
    # A record whose state is missing/unrecognized predates the vocabulary (or
    # was written by something that is not this store). Read it as settled —
    # never as in-flight, which would hand it to the repair sweep.
    return state or TURN_STATE_COMPLETED
