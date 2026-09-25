"""The two writes that CREATE and SETTLE a dispatch row — ``record_dispatch``
and ``record_completion`` — and the housekeeping a settle triggers (``_prune``,
the throttled backlog report). Both writes hold ``_DB_LOCK`` + ``_transaction``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .db import _DB_LOCK, _emit, _owner_identity, _transaction
from .models import (
    _MAX_RETAINED_TERMINAL,
    _RETENTION_SECONDS,
    _TABLE,
    ASK_LIMIT,
    DELIVERY_DELIVERED,
    DELIVERY_PENDING,
    REPLY_LIMIT,
    STATE_RUNNING,
    STATE_UNKNOWN,
    TERMINAL_STATES,
    _media_rows,
    _text,
)

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def record_dispatch(
    *,
    dispatch_id: str,
    sender_session_id: str,
    sender_persona_id: str = "",
    target_persona: str,
    target_instance_id: str = "",
    title: str = "",
    ask: str = "",
    notify_operator: bool = False,
    relay_chain: Any = None,
    dispatched_at: float | None = None,
    remote_install_id: str = "",
) -> dict[str, Any]:
    """Persist a dispatch BEFORE its target turn starts.

    Order matters and is not negotiable: the row exists first, so a process that
    dies one instruction into the target's turn leaves a record the boot sweep
    can classify as ``unknown`` and still tell the sender about. A row written
    after the fact would lose exactly the dispatches most worth reporting.
    """

    now_epoch = float(dispatched_at if dispatched_at is not None else time.time())
    pid, started = _owner_identity()
    row = {
        "dispatch_id": str(dispatch_id),
        "sender_session_id": _text(sender_session_id, 240),
        "sender_persona_id": _text(sender_persona_id, 160),
        "target_persona": _text(target_persona, 160),
        "target_instance_id": _text(target_instance_id, 200),
        "title": _text(title, 200),
        "ask": _text(ask, ASK_LIMIT),
        "notify_operator": bool(notify_operator),
        "dispatched_at": now_epoch,
        "remote_install_id": _text(remote_install_id, 128),
    }
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            f"""INSERT OR REPLACE INTO {_TABLE}
                (dispatch_id, sender_session_id, sender_persona_id, target_persona,
                 target_instance_id, target_session_id, title, ask, state,
                 notify_operator, dispatched_at, updated_at, delivery_state,
                 delivery_attempts, owner_pid, owner_started_at, relay_chain_json,
                 remote_install_id)
                VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                row["dispatch_id"],
                row["sender_session_id"],
                row["sender_persona_id"],
                row["target_persona"],
                row["target_instance_id"],
                row["title"],
                row["ask"],
                STATE_RUNNING,
                1 if row["notify_operator"] else 0,
                now_epoch,
                now_epoch,
                DELIVERY_PENDING,
                pid,
                started,
                json.dumps(list(relay_chain or [])),
                row["remote_install_id"],
            ),
        )
    _emit(
        "dispatch.recorded",
        dispatch_id=row["dispatch_id"],
        target_persona=row["target_persona"],
        sender_session_id=row["sender_session_id"],
        notify_operator=row["notify_operator"],
        title=row["title"][:120] or None,
        # Optional on the contract and present only when true, so a local
        # dispatch's event stays byte-identical to what it has always been.
        remote_install_id=row["remote_install_id"] or None,
    )
    return row


def record_completion(
    dispatch_id: str,
    *,
    state: str,
    reply: str = "",
    error: str = "",
    target_session_id: str = "",
    total_tokens: Any = None,
    visibility: dict[str, Any] | None = None,
    remote: dict[str, Any] | None = None,
    media: list[dict[str, Any]] | None = None,
    only_if_running: bool = False,
) -> bool:
    """Record the target turn's outcome and arm the row for delivery.

    ``delivery_state`` is (re)set to ``pending`` here rather than at dispatch
    time so a row only becomes deliverable once there is something to deliver —
    EXCEPT on a row already marked ``delivered``, which is never re-armed. The
    sender has been told; re-arming would queue a second delivery of the same
    dispatch, and the only thing standing between that and a duplicate message
    is a replay cache that can rotate or be compressed away.

    ``only_if_running`` scopes the write to a row still in flight. The GUESSING
    writer — the orphan sweep, which infers ``unknown`` from a dead PID — passes
    it; the supervisor that actually watched the turn does not. That ordering is
    the point: the supervisor's observed outcome must always beat the sweep's
    inference, never the other way round.

    ``visibility`` is the target turn's typed ``TurnVisibility`` block
    (``agent_runtime.turn_visibility``), passed only by the writer that HELD the
    child's payload — nobody else can know it. It rides the result blob, so
    absent stays absent and there is no schema to migrate: a row written by an
    older process simply carries no block, and the delivery formatter falls back
    to the generic wording. Without it, "they answered with nothing" and "their
    answer never reached us" are the same empty string to the sender.

    ``remote`` (Stage 7) rides the same blob for the same reason, and carries
    ``{install_id, attempts, reason?}`` — how many dial attempts the
    cross-install leg spent and, when it gave up,
    :data:`REMOTE_UNREACHABLE_REASON`. It is on the RESULT rather than in a
    column because it is only knowable once the leg is finished, which is the
    line ``visibility`` already drew: the column beside it
    (``remote_install_id``) carries the half that is true at dispatch time.

    ``media`` (Stage P4, ruling R-P3) is the ``reference → handle`` map the
    TARGET install minted for its reply's ``MEDIA:`` lines. It rides the same
    blob for the third time and for the same reason, plus one this field owns:
    **the map must outlive the process that carried it.** The forged reply stays
    in the sender's transcript after a restart, so the pictures it names have to
    stay fetchable after a restart, and a map held only in the supervisor's
    memory would make "can I open this image" depend on whether the serve has
    been bounced since the dispatch landed.

    It stays on the ROW and the ``dispatch.completed`` event carries only a
    COUNT. That is the 4096-byte event payload cap respected by construction
    rather than by hoping a map is small: sixteen entries of absolute Windows
    paths plus 71-character handles is several kilobytes, and a store write
    whose event was refused for size is a write no consumer would ever see.
    """

    settled = str(state or STATE_UNKNOWN)
    if settled not in TERMINAL_STATES:
        settled = STATE_UNKNOWN
    now_epoch = time.time()
    result = {
        "status": settled,
        "reply": _text(reply, REPLY_LIMIT),
        "error": _text(error, 600),
        "target_session_id": _text(target_session_id, 240),
        "total_tokens": total_tokens,
    }
    if isinstance(visibility, dict) and visibility:
        result["visibility"] = dict(visibility)
    if isinstance(remote, dict) and remote:
        result["remote"] = dict(remote)
    media_rows = _media_rows(media)
    if media_rows:
        result["media"] = media_rows
    guard = " AND state=?" if only_if_running else ""
    params: list[Any] = [
        settled,
        now_epoch,
        now_epoch,
        json.dumps(result),
        result["target_session_id"],
        # CASE WHEN delivery_state=<delivered> THEN <delivered> ELSE <pending>
        DELIVERY_DELIVERED,
        DELIVERY_DELIVERED,
        DELIVERY_PENDING,
        # …and the two CASE guards that leave a delivered row's bookkeeping
        # untouched while resetting a re-armed one's.
        DELIVERY_DELIVERED,
        DELIVERY_DELIVERED,
        str(dispatch_id),
    ]
    if only_if_running:
        params.append(STATE_RUNNING)
    with _DB_LOCK, _transaction() as conn:
        # Read the row's PRIOR verdict inside the same transaction, purely to
        # notice a specific silence: a second writer landing a DIFFERENT outcome
        # on a row the sender was already told about. The re-arm guard makes
        # that harmless to the sender (no second delivery), which is exactly why
        # it would otherwise leave no trace at all — and it is the observable
        # symptom of the supervised-id registry being process-local, so it wants
        # a name rather than to be silently absorbed.
        prior = conn.execute(
            f"SELECT state, delivery_state FROM {_TABLE} WHERE dispatch_id=?",
            (str(dispatch_id),),
        ).fetchone()
        cur = conn.execute(
            f"""UPDATE {_TABLE} SET state=?, completed_at=?, updated_at=?, result_json=?,
                   target_session_id=?,
                   delivery_state=CASE WHEN delivery_state=? THEN ? ELSE ? END,
                   delivery_claim=NULL, delivery_claimed_at=NULL,
                   -- Re-arming clears the PREVIOUS give-up. A row dropped by the
                   -- attempt cap keeps its exhausted counter and its drop reason
                   -- otherwise, so the very next claim re-drops it instantly —
                   -- and the operator reads a stale "attempt_cap" against a
                   -- delivery that never got an attempt. Scoped to rows actually
                   -- being re-armed: a delivered row is left exactly as it is.
                   delivery_attempts=CASE WHEN delivery_state=? THEN delivery_attempts ELSE 0 END,
                   delivery_error=CASE WHEN delivery_state=? THEN delivery_error ELSE NULL END
                WHERE dispatch_id=?{guard}""",
            tuple(params),
        )
        updated = cur.rowcount == 1
    if updated and prior is not None:
        prior_state, prior_delivery = prior
        if prior_delivery == DELIVERY_DELIVERED and str(prior_state or "") != settled:
            _emit(
                "dispatch.outcome_superseded",
                dispatch_id=str(dispatch_id),
                previous=str(prior_state or ""),
                settled=settled,
            )
    if updated:
        _emit(
            "dispatch.completed",
            dispatch_id=str(dispatch_id),
            status=settled,
            reply_chars=len(result["reply"]),
            error=result["error"][:200] or None,
            target_session_id=result["target_session_id"] or None,
            # Both optional and both absent on a local dispatch, so its event
            # stays exactly the bytes it has always been.
            remote_install_id=(remote or {}).get("install_id") or None,
            remote_reason=(remote or {}).get("reason") or None,
            # COUNT, never the map. See the ``media`` paragraph above: the
            # payload cap is 4096 bytes and one map can exceed it, so what the
            # event says is that pictures arrived and how many, and the row
            # says which.
            media_count=len(media_rows) or None,
        )
    _prune()
    return updated


#: How often the backlog report may repeat while the condition persists.
_BACKLOG_REPORT_INTERVAL_SECONDS = 300.0

_backlog_report_state: dict[str, float | int] = {"at": 0.0, "high": 0}


def _backlog_report_due(pending: int, *, now: float | None = None) -> bool:
    """True when the backlog is worth reporting AGAIN.

    ``_prune`` runs on every ``record_completion``, so an unthrottled report
    would emit an EventLog row and a warning per completion for as long as the
    backlog lasts — a storm produced by the very alarm meant to describe a quiet
    failure, in exactly the pathological state where the log is most needed for
    something else.

    Reported when the backlog reaches a NEW HIGH (that is new information) or
    when the interval has elapsed (so a stuck backlog never goes permanently
    silent) — and never merely because another completion happened to run the
    collector.

    A high-water mark rather than "the number changed": the two lanes interleave,
    so the pending count oscillates as rows drain and new completions land.
    Reporting on any change turns 3 -> 4 -> 3 -> 4 back into the storm this
    exists to prevent, which is exactly what the first version of this guard did
    and what its test caught.
    """

    moment = time.time() if now is None else now
    elapsed = moment - float(_backlog_report_state["at"])
    if (
        pending <= int(_backlog_report_state["high"])
        and elapsed < _BACKLOG_REPORT_INTERVAL_SECONDS
    ):
        return False
    _backlog_report_state["high"] = max(pending, int(_backlog_report_state["high"]))
    _backlog_report_state["at"] = moment
    return True


def _prune() -> None:
    """Bound terminal history — but NEVER at the cost of an undelivered answer.

    Housekeeping deletes only rows whose DELIVERY has settled (``delivered`` or
    ``dropped``). A ``pending`` row is an answer the sender has not been told
    about, and the previous ordering-only preference ("delivered first, then
    whatever is oldest") fell straight through to those rows once the terminal
    count passed the cap: a permanently-busy sender never drains — the idle
    probe requeues without burning an attempt, so the row never converges to
    ``dropped`` either — and the reply it was holding got deleted with no event,
    no log line, and nothing left to notice it by. That is precisely the silence
    this lane exists to retire, manufactured by the lane's own collector.

    An undeliverable row is not thereby immortal: the attempt cap converges it
    to ``dropped``, which is deletable and evented. Pruning is simply not the
    mechanism that decides an answer was worthless.
    """

    cutoff = time.time() - _RETENTION_SECONDS
    try:
        with _DB_LOCK, _transaction() as conn:
            conn.execute(
                f"DELETE FROM {_TABLE} WHERE delivery_state=? AND updated_at < ?",
                (DELIVERY_DELIVERED, cutoff),
            )
            settled = conn.execute(
                f"""SELECT COUNT(*) FROM {_TABLE}
                    WHERE state != ? AND delivery_state != ?""",
                (STATE_RUNNING, DELIVERY_PENDING),
            ).fetchone()[0]
            excess = max(0, int(settled) - _MAX_RETAINED_TERMINAL)
            if excess:
                conn.execute(
                    f"""DELETE FROM {_TABLE} WHERE dispatch_id IN (
                          SELECT dispatch_id FROM {_TABLE}
                          WHERE state != ? AND delivery_state != ?
                          ORDER BY CASE delivery_state WHEN ? THEN 0 ELSE 1 END,
                                   updated_at ASC LIMIT ?
                        )""",
                    (STATE_RUNNING, DELIVERY_PENDING, DELIVERY_DELIVERED, excess),
                )
            # Exempting pending rows above would trade one silent failure for
            # another if nobody ever looked: a store growing without bound while
            # senders quietly fail to drain. So count them and SAY SO — loudly,
            # and in the event log — but never delete.
            stranded = conn.execute(
                f"""SELECT COUNT(*) FROM {_TABLE}
                    WHERE state != ? AND delivery_state = ?""",
                (STATE_RUNNING, DELIVERY_PENDING),
            ).fetchone()[0]
        if int(stranded) > _MAX_RETAINED_TERMINAL and _backlog_report_due(int(stranded)):
            logger.warning(
                "dispatch store holds %s undelivered completions (cap %s) — "
                "senders are not draining; nothing was deleted",
                stranded,
                _MAX_RETAINED_TERMINAL,
            )
            _emit(
                "dispatch.delivery_backlog",
                pending=int(stranded),
                cap=_MAX_RETAINED_TERMINAL,
            )
    except Exception:  # pragma: no cover - housekeeping must never fail a write
        logger.debug("dispatch store prune failed", exc_info=True)
