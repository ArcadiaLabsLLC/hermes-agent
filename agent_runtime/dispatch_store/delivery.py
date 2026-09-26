"""The delivery-state machine — claim / release / mark_delivered / drop / rearm /
set_dispatch_owner — and the boot sweep that re-classifies orphaned ``running``
rows (settling them through ``writes.record_completion``).
"""

from __future__ import annotations

import time
from typing import Any

from ..serde import bounded_text
from .db import _DB_LOCK, _emit, _query, _supervised_here, _transaction, get_dispatch
from .models import (
    _TABLE,
    CLAIM_EXPIRY_SECONDS,
    DELIVERY_DELIVERED,
    DELIVERY_DROPPED,
    DELIVERY_PENDING,
    DROP_REASON_ATTEMPT_CAP,
    MAX_DELIVERY_ATTEMPTS,
    REARM_NOT_DROPPED,
    REARM_NOT_FOUND,
    REARM_OUTCOME_BY_STATE,
    REARM_REARMED,
    STATE_RUNNING,
    STATE_UNKNOWN,
)
from .writes import record_completion

__layer__ = "lanes"


def claim_delivery(dispatch_id: str, claim_id: str) -> bool:
    """Take exclusive, EXPIRING ownership of one pending delivery.

    Returns ``True`` only for the consumer that won the claim. A claim older
    than :data:`CLAIM_EXPIRY_SECONDS` is takeable — that is what stops a
    claimant killed mid-forge from stranding the completion forever.

    The attempt counter increments HERE, on the claim, not on success: a
    consumer that crashes between claiming and delivering must still burn an
    attempt, or an input that reliably kills the drain would be retried
    infinitely and never converge to ``dropped``.
    """

    now_epoch = time.time()
    claimed = False
    dropped = False
    attempts = 0
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            f"SELECT delivery_state, delivery_attempts FROM {_TABLE} WHERE dispatch_id=?",
            (str(dispatch_id),),
        ).fetchone()
        if row is None:
            return False
        state, attempts = row
        if state != DELIVERY_PENDING:
            return False
        if int(attempts or 0) >= MAX_DELIVERY_ATTEMPTS:
            conn.execute(
                f"""UPDATE {_TABLE} SET delivery_state=?, updated_at=?, delivery_claim=NULL,
                       delivery_claimed_at=NULL, delivery_error=?
                    WHERE dispatch_id=?""",
                (DELIVERY_DROPPED, now_epoch, DROP_REASON_ATTEMPT_CAP, str(dispatch_id)),
            )
            dropped = True
        else:
            cur = conn.execute(
                f"""UPDATE {_TABLE} SET delivery_claim=?, delivery_claimed_at=?,
                       delivery_attempts=delivery_attempts+1, updated_at=?
                    WHERE dispatch_id=? AND delivery_state=?
                      AND (delivery_claim IS NULL OR delivery_claimed_at < ?)""",
                (
                    str(claim_id),
                    now_epoch,
                    now_epoch,
                    str(dispatch_id),
                    DELIVERY_PENDING,
                    now_epoch - CLAIM_EXPIRY_SECONDS,
                ),
            )
            claimed = cur.rowcount == 1
    if dropped:
        _emit(
            "dispatch.dropped",
            dispatch_id=str(dispatch_id),
            reason=DROP_REASON_ATTEMPT_CAP,
            attempts=int(attempts or 0),
        )
        return False
    return claimed


def release_delivery_claim(dispatch_id: str, *, refund_attempt: bool = False) -> None:
    """Hand a claimed-but-undelivered row back for a later attempt.

    Used when the sender is BUSY: the completion is fine, the moment is wrong,
    and holding the claim would block the next drain pass for the whole expiry
    window.

    ``refund_attempt`` un-counts the attempt the claim burned, and exists for one
    specific and entirely real class: the sender took its chat-root lease between
    the drain's idle probe and the forge, so the handler answered ``chat_busy``.
    NOTHING failed there — racing a live operator is the system working — but the
    attempt counter cannot tell, and eight unlucky races would have marched a
    perfectly deliverable completion to a terminal ``dropped`` with no failure
    anywhere in its history. Attempts count real failures only; the cap exists to
    converge genuinely undeliverable rows, not to time out busy ones.
    """

    with _DB_LOCK, _transaction() as conn:
        if refund_attempt:
            conn.execute(
                f"""UPDATE {_TABLE}
                    SET delivery_claim=NULL, delivery_claimed_at=NULL, updated_at=?,
                        delivery_attempts=MAX(delivery_attempts-1, 0)
                    WHERE dispatch_id=? AND delivery_state=?""",
                (time.time(), str(dispatch_id), DELIVERY_PENDING),
            )
        else:
            conn.execute(
                f"""UPDATE {_TABLE} SET delivery_claim=NULL, delivery_claimed_at=NULL, updated_at=?
                    WHERE dispatch_id=? AND delivery_state=?""",
                (time.time(), str(dispatch_id), DELIVERY_PENDING),
            )


def set_dispatch_owner(
    dispatch_id: str, *, owner_pid: int | None, owner_started_at: int | None
) -> bool:
    """Re-point a running row's owner identity at the process actually doing the work.

    A dispatch is RECORDED by the tool (in the sender's process) and then
    EXECUTED by a child process. The row's owner has to become the child, because
    "is this dispatch still running?" is a question about the process running the
    turn — not about the supervisor thread waiting on it, and not about the
    sender that asked. Stamping the child here is what keeps the orphan sweep
    coherent when the supervisor itself dies: the row settles when the CHILD is
    gone, which is exactly when the work is gone.

    Only ``running`` rows move. A completion that arrived first wins — this is
    bookkeeping, and it must never resurrect a settled row.
    """

    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET owner_pid=?, owner_started_at=?, updated_at=?
                WHERE dispatch_id=? AND state=?""",
            (
                int(owner_pid) if owner_pid else None,
                int(owner_started_at) if owner_started_at else None,
                time.time(),
                str(dispatch_id),
                STATE_RUNNING,
            ),
        )
        return cur.rowcount == 1


def mark_delivered(dispatch_id: str) -> bool:
    """Atomically acknowledge that the sender was actually told."""

    now_epoch = time.time()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET delivery_state=?, delivered_at=?, updated_at=?,
                   delivery_claim=NULL, delivery_claimed_at=NULL
                WHERE dispatch_id=? AND delivery_state!=?""",
            (
                DELIVERY_DELIVERED,
                now_epoch,
                now_epoch,
                str(dispatch_id),
                DELIVERY_DELIVERED,
            ),
        )
        delivered = cur.rowcount == 1
    if delivered:
        _emit("dispatch.delivered", dispatch_id=str(dispatch_id))
    return delivered


def drop_delivery(dispatch_id: str, *, reason: str) -> bool:
    """Terminally give up on delivering a row, with the reason recorded."""

    now_epoch = time.time()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET delivery_state=?, updated_at=?, delivery_claim=NULL,
                   delivery_claimed_at=NULL, delivery_error=?
                WHERE dispatch_id=? AND delivery_state=?""",
            (
                DELIVERY_DROPPED,
                now_epoch,
                bounded_text(reason, 200),
                str(dispatch_id),
                DELIVERY_PENDING,
            ),
        )
        dropped = cur.rowcount == 1
    if dropped:
        _emit("dispatch.dropped", dispatch_id=str(dispatch_id), reason=str(reason)[:120])
    return dropped


def rearm_delivery(dispatch_id: str) -> tuple[str, dict[str, Any] | None]:
    """Put a DROPPED delivery back in the queue. Returns ``(outcome, row)``.

    The operator's way back from a terminal give-up. A dropped row is not a lost
    answer — the reply is still durable on the row and the sender still has not
    been told — so once the reason it was refused is FIXED (a deployed guard fix,
    a re-opened chat root), the delivery deserves another pass rather than a
    hand-written re-send.

    The re-arm is byte-for-byte the one ``record_completion`` already performs
    when a second outcome lands on a dropped row (see the ``delivery_attempts`` /
    ``delivery_error`` CASE arms there): back to ``pending``, counter to zero,
    previous give-up cleared, claim released. Both spellings must stay identical
    — a re-arm that kept the exhausted counter is re-dropped by the very next
    claim, and the operator then reads a stale reason against a delivery that
    never got an attempt.

    Refuses by NAME rather than silently: ``not_found``, ``already_delivered``
    (the sender was told; re-arming would deliver a second copy) and
    ``not_dropped`` (a pending row is already queued and needs nothing).

    Deliberately emits no EventLog row. ``dispatch.delivery_rearmed`` would be a
    new registered contract, and the registry's hash is stamped on every live
    persona instance — a migration this repair verb has no business forcing. The
    mutation is not silent regardless: the operator ran the verb and reads its
    envelope, and the next drain pass emits the real ``dispatch.delivered`` or
    ``dispatch.dropped`` for the same row.
    """

    now_epoch = time.time()
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            f"SELECT delivery_state FROM {_TABLE} WHERE dispatch_id=?",
            (str(dispatch_id),),
        ).fetchone()
        if row is None:
            return REARM_NOT_FOUND, None
        state = str(row[0] or DELIVERY_PENDING)
        outcome = REARM_OUTCOME_BY_STATE.get(state, REARM_NOT_DROPPED)
        if outcome == REARM_REARMED:
            conn.execute(
                f"""UPDATE {_TABLE} SET delivery_state=?, delivery_attempts=0,
                       delivery_error=NULL, delivery_claim=NULL,
                       delivery_claimed_at=NULL, updated_at=?
                    WHERE dispatch_id=? AND delivery_state=?""",
                (DELIVERY_PENDING, now_epoch, str(dispatch_id), DELIVERY_DROPPED),
            )
    return outcome, get_dispatch(dispatch_id)


def restore_undelivered_dispatches() -> dict[str, int]:
    """Reclassify dispatches orphaned by a dead process, at boot.

    A row still marked ``running`` whose owner process is provably gone can
    never complete: nothing is left to run its turn or write its result. It is
    reclassified ``unknown`` — an outcome the sender is still owed, phrased
    honestly — and armed for delivery.

    Identity, not liveness: a PID that exists but whose start time differs from
    the recorded baseline is a DIFFERENT process wearing a recycled number, and
    counts as gone. A start time that cannot be READ is neither proof nor
    disproof, so the row is left alone rather than being resurrected or buried
    on a psutil hiccup.

    Restored rows carry ``restored: True`` on the completion they produce (in
    memory only — the flag is a property of THIS boot, not of the record), and
    the drain must positively prove it owns the target chat root before
    delivering one (#64484).
    """

    try:
        from gateway.status import get_process_start_time

        from .._upstream_doors import pid_exists as _pid_exists
    except Exception:  # pragma: no cover - defensive
        return {"restored": 0, "checked": 0}

    supervised = _supervised_here()
    rows = _query("WHERE state=?", (STATE_RUNNING,))
    restored = 0
    for row in rows:
        # NEVER answer for a dispatch this process is still supervising. Since
        # the sweep became periodic it runs beside live supervisors, and there
        # is a real window — from the child exiting to the supervisor's
        # `record_completion`, across `proc.wait()` and two pump joins — where a
        # dead PID on a running row means "about to be recorded", not "orphan".
        # Guessing there delivers "the outcome is unknown" for a dispatch that
        # COMPLETED, and the real answer landing moments later is then swallowed
        # by the delivery-turn replay dedup.
        if row.get("dispatch_id") in supervised:
            continue
        pid = row.get("owner_pid")
        if not pid:
            continue
        try:
            alive = bool(_pid_exists(int(pid)))
        except Exception:
            continue
        if alive:
            baseline = row.get("owner_started_at")
            if baseline is None:
                # No identity baseline recorded: cannot disprove ownership.
                continue
            try:
                observed = get_process_start_time(int(pid))
            except Exception:
                continue
            if observed is None or int(observed) == int(baseline):
                # Unreadable probe, or a genuine match — either way not disproof.
                continue
        # The dominant case after the subprocess move is a serve recycled while
        # a HEALTHY child ran to completion: the reply exists, it is in the
        # target's own thread, and only this bookkeeping row was orphaned. So
        # the copy points at that thread rather than inviting the sender to
        # duplicate work that has very likely already been done.
        thread = row.get("target_session_id") or ""
        where = (
            f" Their reply, if they finished, is in thread {thread} "
            "(agent_chat_open with that session_id)."
            if thread
            else (
                " Check your thread with them (agent_chat_open / agent_chat_log_path)"
                " before re-sending — they may well have finished."
            )
        )
        if record_completion(
            row["dispatch_id"],
            state=STATE_UNKNOWN,
            error=(
                "The process running this dispatch exited before recording a result, so "
                "the outcome is unknown." + where
            ),
            target_session_id=thread,
            # The sweep INFERS; it must never overwrite an outcome a supervisor
            # actually observed and recorded between the read above and here.
            only_if_running=True,
        ):
            restored += 1
    return {"restored": restored, "checked": len(rows)}
