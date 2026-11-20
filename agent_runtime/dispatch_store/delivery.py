"""The delivery-state machine — claim / release / mark_delivered / drop / rearm /
set_dispatch_owner — and the boot sweep that re-classifies orphaned ``running``
rows (settling them through ``writes.record_completion``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..serde import bounded_text
from .db import _DB_LOCK, _emit, _owner_identity, _query, _supervised_here, _transaction, get_dispatch
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

logger = logging.getLogger(__name__)

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
    dispatch_id: str, *, owner_pid: int | None, owner_started_at: int | None,
    owner_group: int | None = None,
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

    ``owner_group`` is the process group the child leads (review w1118a.55 D10), or
    None: what :func:`settle_if_orphaned` may end once the child is provably gone.
    """

    # The owner stamp IS the moment the child exists, so it is also where the
    # queue wait ends: ``started_at`` is written here and nowhere else.
    now = time.time()
    # The stamping process is the child's supervisor (D12, review w1118a.56).
    supervisor_pid, supervisor_started = _owner_identity()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET owner_pid=?, owner_started_at=?, owner_group=?, updated_at=?,
                started_at=COALESCE(started_at, ?), supervisor_pid=?, supervisor_started_at=?
                WHERE dispatch_id=? AND state=?""",
            (
                int(owner_pid) if owner_pid else None,
                int(owner_started_at) if owner_started_at else None,
                int(owner_group) if owner_group else None,
                now,
                now,
                supervisor_pid,
                supervisor_started,
                str(dispatch_id),
                STATE_RUNNING,
            ),
        )
        return cur.rowcount == 1


def claim_dispatch_supervision(dispatch_id: str, row: dict[str, Any]) -> bool:
    """Make THIS process the supervisor of a running row it re-adopts; True when it won (D12).

    Compare-and-set on the supervisor the caller read: two serves of one home booting together
    re-adopt a request once, never twice.
    """

    pid, started = _owner_identity()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET supervisor_pid=?, supervisor_started_at=?, updated_at=?
                WHERE dispatch_id=? AND state=?
                  AND supervisor_pid IS ? AND supervisor_started_at IS ?""",
            (
                pid,
                started,
                time.time(),
                str(dispatch_id),
                STATE_RUNNING,
                row.get("supervisor_pid"),
                row.get("supervisor_started_at"),
            ),
        )
        return cur.rowcount == 1


def request_dispatch_cancel(dispatch_id: str, reason: str) -> bool:
    """Leave a durable cancel on a ``running`` row for the process supervising it.

    D1.07 (owner ruling a). The canceller holds no handle and never kills by pid;
    the supervisor's cancel watch reads the mark and stops its own child. True
    when the row is running and now carries a mark (a first reason is kept: a
    second request does not rewrite why the first one was made).
    """

    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            f"""UPDATE {_TABLE} SET cancel_requested=?, cancel_requested_at=?, updated_at=?
                WHERE dispatch_id=? AND state=? AND cancel_requested=''""",
            (str(reason or "operator_cancel")[:80], now, now, str(dispatch_id), STATE_RUNNING),
        )
        row = conn.execute(
            f"SELECT cancel_requested FROM {_TABLE} WHERE dispatch_id=? AND state=?",
            (str(dispatch_id), STATE_RUNNING),
        ).fetchone()
    return bool(row and row[0])


def ack_dispatch_cancel(dispatch_id: str) -> bool:
    """The supervising process took a durable cancel (its cancel watch); True when recorded.

    What tells a cancel a live supervisor is acting on from one nobody is left to
    honour (:func:`settle_if_cancel_unanswered`, review w1118a.55 D11).
    """

    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET cancel_seen_at=?
                WHERE dispatch_id=? AND state=? AND cancel_requested != '' AND cancel_seen_at IS NULL""",
            (time.time(), str(dispatch_id), STATE_RUNNING),
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
        if settle_if_orphaned(row) or settle_if_cancel_unanswered(row):
            restored += 1
    return {"restored": restored, "checked": len(rows)}


def _identity_state(pid: Any, baseline: Any) -> str:
    """``"alive"`` (the pid runs under its recorded start time), ``"gone"`` (dead, or a recycled
    number), or ``"unproven"`` (no pid, no baseline, or an unreadable probe)."""

    try:
        from gateway.status import get_process_start_time

        from .._upstream_doors import pid_exists as _pid_exists
    except Exception:  # pragma: no cover - defensive
        return "unproven"
    if not pid:
        return "unproven"
    try:
        alive = bool(_pid_exists(int(pid)))
    except Exception:
        return "unproven"
    if not alive:
        return "gone"
    if baseline is None:
        return "unproven"
    try:
        observed = get_process_start_time(int(pid))
    except Exception:
        return "unproven"
    if observed is None:
        return "unproven"
    return "alive" if int(observed) == int(baseline) else "gone"


def owner_provably_alive(row: dict[str, Any]) -> bool:
    """Whether a row's child is PROVABLY the recorded process, still running: pid plus start time (D12)."""

    return _identity_state(row.get("owner_pid"), row.get("owner_started_at")) == "alive"


def supervisor_provably_gone(row: dict[str, Any]) -> bool:
    """Whether the serve that supervised a row's child is PROVABLY gone (D12).

    A row with no supervisor stamp (written before the column) is not proof: it is never re-adopted.
    """

    return _identity_state(row.get("supervisor_pid"), row.get("supervisor_started_at")) == "gone"


def owner_provably_gone(row: dict[str, Any]) -> bool:
    """Whether a ``running`` row's recorded owner process is PROVABLY gone.

    Dead, or alive under a start time that differs from the recorded baseline
    (a recycled number). An unreadable probe, a missing pid or a missing
    baseline is not proof, so it answers False.
    """

    return _identity_state(row.get("owner_pid"), row.get("owner_started_at")) == "gone"


def settle_if_orphaned(row: dict[str, Any]) -> bool:
    """Settle ONE ``running`` row ``unknown`` when its owner is provably gone; True when it did.

    The sweep's per-row step, also taken at once by a Stop on a row no process
    here supervises (``tools/agent_chat_dispatch/local.py``): its process has
    already ended, so the Stop is answered by settling what the sweep would
    settle a minute later. The CALLER owns the supervised-here guard.
    """

    if not owner_provably_gone(row):
        return False
    _end_left_group(row)
    # The child may have answered after its serve was gone: its result file holds the
    # answer the closed pipe lost (review w1118a.56 D12), read through the one mapping.
    from .result_file import discard_dispatch_result, read_dispatch_result

    payload = read_dispatch_result(row["dispatch_id"])
    if payload is not None:
        from tools.agent_chat_dispatch.child import payload_completion

        settled = bool(record_completion(
            row["dispatch_id"], **payload_completion(payload, None), only_if_running=True
        ))
        discard_dispatch_result(row["dispatch_id"])
        return settled
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
    discard_dispatch_result(row["dispatch_id"])
    return bool(
        record_completion(
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
        )
    )


#: How long a durable cancel waits for a supervisor's cancel watch to take it before the
#: row is settled ``unknown`` (review w1118a.55 D11). Several of the watch's 2 s polls
#: (``tools/agent_chat_dispatch/cancel_watch.py::CANCEL_POLL_SECONDS``; a test pins the
#: margin), so a live supervisor is never out-waited.
CANCEL_ANSWER_WINDOW_SECONDS = 10.0


def settle_if_cancel_unanswered(row: dict[str, Any], *, now: float | None = None) -> bool:
    """Settle ONE ``running`` row ``unknown`` when its Stop went unanswered; True when it did.

    The row whose pid is alive again but unprovable (a recycled number, another
    session's process) stays listed by design — burying it on a probe hiccup would
    bury a live build. A Stop on it writes a durable cancel; a live supervisor takes
    that within a poll (``ack_dispatch_cancel``). One untaken after
    :data:`CANCEL_ANSWER_WINDOW_SECONDS` has no process left to answer it: the operator
    asked and nothing answered, so the row settles ``unknown`` and nothing is signalled.
    A cross-install row is answered by the far install, never here. The CALLER owns
    the supervised-here guard.
    """

    if (
        row.get("state") != STATE_RUNNING
        or row.get("remote_install_id")
        or not row.get("cancel_requested")
        or row.get("cancel_seen_at")
    ):
        return False
    asked = row.get("cancel_requested_at")
    if not asked or (time.time() if now is None else now) - float(asked) < CANCEL_ANSWER_WINDOW_SECONDS:
        return False
    return bool(
        record_completion(
            row["dispatch_id"],
            state=STATE_UNKNOWN,
            error=(
                "Stop was asked and no process answered it, so the dispatch was cleared and "
                "its outcome is unknown. Check your thread with them before re-sending."
            ),
            target_session_id=row.get("target_session_id") or "",
            only_if_running=True,
        )
    )


def settle_unanswered_cancels(*, now: float | None = None) -> int:
    """Settle every running row whose Stop no supervisor took within its window; the count.

    One indexed read of the rows carrying a cancel (``cancel_requested_dispatches``), so it
    runs on the delivery drain's own short cadence: a Stop nobody answers clears its row
    seconds after the window, not a sweep later. Rows a supervisor in THIS process holds
    are skipped — its cancel watch answers them.
    """

    from .db import cancel_requested_dispatches

    supervised = _supervised_here()
    settled = 0
    for row in cancel_requested_dispatches():
        if row.get("dispatch_id") not in supervised and settle_if_cancel_unanswered(row, now=now):
            settled += 1
    return settled


def _end_left_group(row: dict[str, Any]) -> None:
    """End what a provably-gone child left in its process group (review w1118a.55 D10).

    Only a row that names a group (a child spawned leading one) and only through the
    child's own identity-guarded group end. Best effort: a settle never fails on it.
    """

    group = row.get("owner_group")
    if not group:
        return
    try:
        from tools.agent_chat_dispatch.child import end_child_group

        end_child_group(int(group), row.get("owner_started_at"))
    except Exception:  # pragma: no cover - best effort
        logger.debug("dispatch %s group end failed", row.get("dispatch_id"), exc_info=True)
