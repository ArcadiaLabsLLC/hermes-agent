"""The supervisor pool and the local leg: stamp, run natively, wait, settle; and the status the tool returns.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from agent_runtime.dispatch_store.supervision import (
    _forget_supervised,
    _mark_supervised,
    supervised_dispatch_ids,
)
from agent_runtime.persona_chat_continuity.lease import chat_root_is_busy

from .cancel_watch import CANCEL_POLL_SECONDS, ensure_cancel_watch
from .native import TurnRun, run_turn
from .outcome import KILL_GRACE_SECONDS, payload_completion
from .remote import _run_remote_dispatch, request_remote_cancel

logger = logging.getLogger(__name__)

__layer__ = "lanes"


_executor = None
_executor_lock = threading.Lock()
_executor_max_workers = 0


def _get_executor(max_workers: int):
    """The shared dispatch executor, resized when the configured cap grows.

    Each worker supervises one native turn (``native.run_turn``, which runs the
    turn on a thread of its own), so the pool is a concurrency cap rather than a
    compute pool. It stays daemon-threaded: a supervisor waiting on a 30-minute
    turn must never hold interpreter exit open (stdlib pool workers are joined
    unconditionally by an atexit hook).

    Deliberately never SHRINKS a live pool: an in-flight dispatch holds a
    worker, and tearing the pool down under it to honour a smaller cap would
    abandon exactly the long work this lane exists to host. A lowered cap takes
    effect on the next process.
    """

    global _executor, _executor_max_workers
    from tools.daemon_pool import DaemonThreadPoolExecutor

    with _executor_lock:
        if _executor is None or max_workers > _executor_max_workers:
            if _executor is not None:
                _executor.shutdown(wait=False)
            _executor = DaemonThreadPoolExecutor(
                max_workers=max(1, int(max_workers)),
                thread_name_prefix="agent-chat-dispatch",
            )
            _executor_max_workers = max(1, int(max_workers))
        return _executor


#: Cancellations asked of dispatches THIS process supervises: dispatch id -> reason.
#: Written by :func:`request_cancel`, read by the supervisor before the turn starts and
#: at each of its polls while the turn runs (``native.run_turn``'s ``stop_requested``,
#: which carries it to the turn's interrupt seam), and consumed by the settle.
_CANCEL_REQUESTED: dict[str, str] = {}
_CANCEL_LOCK = threading.Lock()

CANCEL_STOPPING = "stopping"
CANCEL_CANCELLED = "cancelled"
CANCEL_ALREADY_FINISHED = "already_finished"
CANCEL_NOT_OWNED_HERE = "not_owned_here"
#: D1.07 (owner ruling a): another process supervises a running turn; the
#: durable mark is written and that process's cancel watch stops it.
CANCEL_REQUESTED = "cancel_requested"
#: A Stop on a row no process here supervises, whose process had already ended:
#: settled ``unknown`` at once, as the orphan sweep would a minute later.
CANCEL_SETTLED = "settled"


def _request_cancel_mark(dispatch_id: str, reason: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_REQUESTED[str(dispatch_id)] = str(reason or "operator_cancel")


def _take_cancel_mark(dispatch_id: str) -> str | None:
    with _CANCEL_LOCK:
        return _CANCEL_REQUESTED.pop(str(dispatch_id), None)


def _peek_cancel_mark(dispatch_id: str) -> str | None:
    with _CANCEL_LOCK:
        return _CANCEL_REQUESTED.get(str(dispatch_id))

def _durable_cancel_reason(dispatch_id: str) -> str:
    """The durable cancel another process left on the row (any state), or ""."""

    from agent_runtime import dispatch_store

    return str((dispatch_store.get_dispatch(dispatch_id) or {}).get("cancel_requested") or "")


def request_cancel(dispatch_id: str, *, reason: str = "operator_cancel") -> dict[str, Any]:
    """Cancel one dispatch this process supervises. Never a bare PID kill.

    Three honest answers, each a typed ``outcome``:

    * ``cancelled`` -- it had not started yet (queued behind the concurrency
      cap); the row is settled ``cancelled`` here and the worker that later
      picks it up sees the mark and runs nothing.
    * ``stopping`` -- its turn is running in this process; the supervisor carries
      the Stop to the turn's interrupt seam (``live_turns``, the conversation's own
      Stop) within a poll and settles the row when the turn has ended. "Stopping" is
      reported until that happens, never "stopped".
    * ``already_finished`` -- the row is terminal; its result is kept as is.

    A dispatch another process on this machine supervises is cancelled through
    the row (D1.07, owner ruling a): see :func:`_request_cancel_elsewhere`. A
    cross-install dispatch is asked of the install running its turn
    (:func:`~.remote.request_remote_cancel`), whoever supervises the row here. The
    mark is set BEFORE the row is re-read and the supervisor reads the mark before
    the turn starts and at every poll after, so a cancel racing the start is never
    dropped.
    """

    from agent_runtime import dispatch_store

    dispatch_id = str(dispatch_id or "")
    row = dispatch_store.get_dispatch(dispatch_id)
    if row is None:
        return {"dispatch_id": dispatch_id, "outcome": "not_found"}
    if row.get("state") != dispatch_store.STATE_RUNNING:
        return {
            "dispatch_id": dispatch_id,
            "outcome": CANCEL_ALREADY_FINISHED,
            "state": row.get("state"),
        }
    if row.get("remote_install_id"):
        # The turn runs on a paired install: ITS serve supervises the work, so
        # it is asked, from whichever process here holds the Stop (D1.07 S2).
        return request_remote_cancel(row, reason=reason)
    if dispatch_id not in supervised_dispatch_ids():
        return _request_cancel_elsewhere(dispatch_id, row, reason)
    _request_cancel_mark(dispatch_id, reason)
    row = dispatch_store.get_dispatch(dispatch_id) or row
    if row.get("started_at"):
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_STOPPING, "reason": reason}
    # Not started: settle it now. The worker consults the mark before the turn starts.
    dispatch_store.record_completion(
        dispatch_id,
        state=dispatch_store.STATE_CANCELLED,
        error=_cancelled_text(reason, started=False),
        only_if_running=True,
    )
    return {"dispatch_id": dispatch_id, "outcome": CANCEL_CANCELLED, "reason": reason}


def _request_cancel_elsewhere(dispatch_id: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    """Cancel a dispatch another process supervises: through the row, never a pid.

    The durable mark is written first; then a row that never started is settled
    ``cancelled`` here, exactly as its owner would (its worker reads the mark
    and runs nothing), and a running turn is left to its supervisor's cancel
    watch, which stops it within :data:`CANCEL_POLL_SECONDS` —
    ``cancel_requested`` says so rather than claiming a stop. A started row whose
    supervising process is PROVABLY gone (dead, or a recycled number) has nothing left to stop
    and nobody left to settle it but the orphan sweep, so it is settled here and
    now (``settled``, row ``MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT``):
    the operator's Stop on an ended entry clears it instead of waiting a sweep.
    """

    from agent_runtime import dispatch_store

    if not dispatch_store.request_dispatch_cancel(dispatch_id, reason):
        settled = dispatch_store.get_dispatch(dispatch_id) or row
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_ALREADY_FINISHED, "state": settled.get("state")}
    row = dispatch_store.get_dispatch(dispatch_id) or row
    if not row.get("started_at"):
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_CANCELLED,
            error=_cancelled_text(reason, started=False),
            only_if_running=True,
        )
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_CANCELLED, "reason": reason}
    if dispatch_store.settle_if_orphaned(row):
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_SETTLED, "reason": reason}
    return {
        "dispatch_id": dispatch_id,
        "outcome": CANCEL_REQUESTED,
        "reason": reason,
        "poll_seconds": CANCEL_POLL_SECONDS,
    }


def _cancelled_text(reason: str, *, started: bool) -> str:
    where = "before it replied" if started else "before it started"
    return f"the dispatch was cancelled {where} ({reason}); nothing was delivered"


def _run_dispatch(dispatch_id: str, spec: dict[str, Any]) -> None:
    """Run one dispatched turn natively, wait for it, and record its outcome.

    Never raises, and that is now STRUCTURAL rather than a claim this docstring
    makes about the code below it. The body used to run unguarded, so a raise
    before the turn — a malformed spec, a store that would not
    stamp — left the row ``running`` and owned by the
    sender's still-live serve PID, which the orphan sweep can therefore never
    settle: running forever, with nobody waiting on a Future to notice, because
    ``executor.submit`` discards it. The wrapper below turns every such raise
    into a recorded terminal state.
    """

    try:
        _run_dispatch_guarded(dispatch_id, spec)
    except BaseException as exc:  # a detached turn must never vanish
        logger.exception("detached dispatch %s failed unrecoverably", dispatch_id)
        try:
            from agent_runtime import dispatch_store

            dispatch_store.record_completion(
                dispatch_id,
                state=dispatch_store.STATE_ERROR,
                error=(
                    "the dispatch supervisor failed before it could record a result: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        except Exception:  # pragma: no cover - the store is the last resort
            logger.exception(
                "dispatch %s could not be settled after a supervisor failure", dispatch_id
            )
        return
    finally:
        # ONE release site. The inner handler used to release too, which was
        # harmless (the operation is idempotent) but read as though the outer
        # `finally` did not cover the early return — it does, and a second call
        # invites the next reader to assume one of them is load-bearing.
        _forget_supervised(dispatch_id)


def _run_dispatch_guarded(dispatch_id: str, spec: dict[str, Any]) -> None:
    """The supervisor body. See :func:`_run_dispatch` for the failure contract.

    **Gateway Stage 7's fork is the first line, and it is a fork rather than a
    branch inside the local run**: a cross-install dispatch runs its turn on the
    paired install, so everything below — the owner stamp, the native turn, its
    interrupt — describes work that is not happening on this machine. The two legs
    meet again at ``record_completion``, which is the only thing the rest of the
    lane reads.
    """

    if spec.get("remote_install_id"):
        _run_remote_dispatch(dispatch_id, spec)
        return

    from agent_runtime import dispatch_store

    if _take_cancel_mark(dispatch_id) is not None:
        # Cancelled while queued: ``request_cancel`` settled the row; running
        # the turn now would deliver an answer to a sender who stopped asking.
        return
    durable = _durable_cancel_reason(dispatch_id)
    if durable:
        # The same, asked from another process (D1.07). It settled the row
        # already unless it lost a race with this worker; the guard makes the
        # second write a no-op either way.
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_CANCELLED,
            error=_cancelled_text(durable, started=False),
            only_if_running=True,
        )
        return

    # ``spec["max_seconds"]`` everywhere: the tool always sets it, and reading
    # the same key two ways (subscript here, ``.get(...) or 1800`` there) is how
    # a spec-shape bug hides behind a default that looks deliberate.
    budget = float(spec["max_seconds"])
    # A target still in another turn refuses the turn ``chat_busy`` before anything
    # runs. That is a wait, never a result: the dispatch waits for the target's turn
    # to end and runs then, for at most its own budget of waiting
    # (RT-A-LEADS-STOP-TO-A-BUSY-HELPER-COMES-BACK-AS-WORK-FAILED: a lead's stop order
    # to a lane still on the lead's first task was delivered as "work failed").
    wait_until = time.time() + budget
    while True:
        run = _run_turn_once(dispatch_id, spec, budget)
        busy_root = None if (run.exit_reason or run.abandoned) else _busy_target_root(run.payload)
        if busy_root is None or not _wait_for_busy_target(dispatch_id, busy_root, wait_until):
            break
    cancel_reason = _peek_cancel_mark(dispatch_id)
    if busy_root is not None and cancel_reason is not None:
        # Cancelled while it waited: nothing ran, so the cancel is the outcome.
        run.payload = None
    try:
        _record_local_outcome(dispatch_id, budget, run, cancel_reason=cancel_reason)
    finally:
        # Taken only once the row is settled: a cancel watch pass between a take
        # and the settle would read "running, no mark here" and ask again.
        _take_cancel_mark(dispatch_id)


#: How often a dispatch waiting on a busy target looks at the target's chat root again.
#: Each look is a zero-wait lease probe; the turn is started again only once the root is free.
BUSY_TARGET_POLL_SECONDS = 2.0
#: The owner the busy check names while it probes the target's root.
BUSY_TARGET_PROBE_OWNER = "dispatch-busy-target-probe"


def _busy_target_root(payload: dict[str, Any] | None) -> str | None:
    """The chat root that refused this turn ``chat_busy`` (``""`` when unnamed); ``None`` for any other answer."""

    from agent_runtime.mission_chat_outcome import ChatErrorKind

    payload = payload or {}
    if payload.get("ok") or str(payload.get("error_kind") or "") != ChatErrorKind.CHAT_BUSY:
        return None
    return str(payload.get("root_chat_session_id") or payload.get("session_id") or "")


def _wait_for_busy_target(dispatch_id: str, root: str, wait_until: float) -> bool:
    """Wait until the busy target's root is free. False when cancelled or out of waiting time."""

    while time.time() < wait_until:
        time.sleep(BUSY_TARGET_POLL_SECONDS)
        if _peek_cancel_mark(dispatch_id) is not None:
            return False
        if not root or not chat_root_is_busy(root, probe_owner=BUSY_TARGET_PROBE_OWNER):
            return time.time() < wait_until
    return False


def _run_turn_once(dispatch_id: str, spec: dict[str, Any], budget: float) -> TurnRun:
    """Stamp the row, then run the target's turn natively in this process (``native.run_turn``).

    The row's owner is THIS process — the one running the turn — so the orphan sweep settles it
    when this serve is gone, which is exactly when the turn is gone; ``started_at`` is written by
    the same stamp, ending the queue wait.
    """

    from agent_runtime import dispatch_store
    from agent_runtime.dispatch_store.db import _owner_identity

    try:
        pid, started_at = _owner_identity()
        dispatch_store.set_dispatch_owner(dispatch_id, owner_pid=pid, owner_started_at=started_at)
    except Exception:  # pragma: no cover - bookkeeping must not abort the run
        logger.debug("dispatch %s owner stamp failed", dispatch_id, exc_info=True)
    if _peek_cancel_mark(dispatch_id) is None:
        durable = _durable_cancel_reason(dispatch_id)
        if durable:
            _request_cancel_mark(dispatch_id, durable)
    return run_turn(spec, budget=budget, stop_requested=lambda: _peek_cancel_mark(dispatch_id) is not None)


def _record_local_outcome(
    dispatch_id: str,
    budget: float | None,
    run: TurnRun,
    *,
    cancel_reason: str | None,
) -> None:
    """Record the native turn's outcome: stopped, over budget, failed, no payload, or its payload's verdict.

    ``cancel_reason`` is the mark a :func:`request_cancel` left. It decides the row when the turn
    produced no payload, came back ``stopped`` (the Stop reached it) or was left behind: a turn that
    had already replied when the Stop arrived keeps its reply, because the sender asked for that
    answer before anyone stopped asking.
    """

    from agent_runtime import dispatch_store

    payload = run.payload
    if cancel_reason is not None and (payload is None or payload.get("stopped") or run.abandoned):
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_CANCELLED,
            error=_cancelled_text(cancel_reason, started=True),
            target_session_id=str((payload or {}).get("session_id") or ""),
        )
        return
    if run.exit_reason == "budget_exceeded" or run.abandoned:
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_ERROR,
            error=(
                f"the dispatch exceeded its {budget or 0:.0f}s budget (plus a "
                f"{KILL_GRACE_SECONDS:.0f}s grace) and was stopped. Anything it wrote "
                "before that is in its own chat thread."
            ),
            target_session_id=str((payload or {}).get("session_id") or ""),
        )
        return
    if run.exit_reason:
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_ERROR,
            error=f"the dispatched turn failed before it replied: {run.error or run.exit_reason}"[:600],
        )
        return
    if payload is None:
        # No payload is a runtime failure, not a result — say so rather than
        # inventing an empty reply the sender would read as "nothing to report".
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_UNKNOWN,
            error=(
                f"the dispatched turn ended (exit code {run.exit_code}) without a reply payload; "
                "the outcome is unknown."
            ),
        )
        return
    # Whether that turn produced anything visible is recorded here, from its own
    # payload: a turn whose model returned no content comes back `ok` with an empty
    # reply, and the sender would then read the same blank as a reply that never
    # made it out.
    dispatch_store.record_completion(dispatch_id, **payload_completion(payload, run.exit_code))


def dispatch_detached_turn(
    *,
    dispatch_id: str,
    spec: dict[str, Any],
    max_concurrent: int,
) -> None:
    """Queue one detached target turn on the shared supervisor pool.

    Queued, not refused, when the cap is saturated: the caller has already been
    told ``dispatched: true`` and a durable row already exists, so dropping the
    work here would be a lie the sender could never detect. A queued dispatch no
    longer burns budget while it waits — the clock is minted when its turn starts.
    """

    executor = _get_executor(max_concurrent)
    # Marked BEFORE submit, not inside the worker: a dispatch queued behind the
    # concurrency cap has not started yet, but its row is already `running` and
    # the sweep must not answer for it either.
    _mark_supervised(dispatch_id)
    try:
        executor.submit(_run_dispatch, dispatch_id, spec)
    except Exception:
        _forget_supervised(dispatch_id)
        raise
    # AFTER the mark: the watch exits only when nothing is supervised (D1.07).
    ensure_cancel_watch()


def summarize_for_caller(row: dict[str, Any]) -> dict[str, Any]:
    """The bounded shape ``agent_chat_dispatches`` returns for one row.

    Read-only projection of a store row: enough for an agent to answer "did the
    thing I asked for come back yet?", never the whole reply (that arrives as
    its own delivered turn, and duplicating it here would double the context
    cost of every status check).

    ``delivery_error`` is here because ``delivery_state`` alone leaves the one
    party actually owed the answer — the agent that dispatched the work — able
    to see THAT delivery was abandoned but never why, at any point. Its whole
    recourse is to decide whether to re-dispatch, and "dropped" without a reason
    does not support that decision: a vanished chat root means re-sending is
    pointless, while an exhausted attempt cap means it is exactly right.
    """

    result = row.get("result") or {}
    reply = str(result.get("reply") or "")
    return {
        "dispatch_id": row.get("dispatch_id"),
        "target_persona": row.get("target_persona"),
        "target_instance_id": row.get("target_instance_id") or None,
        "title": row.get("title") or None,
        "ask_excerpt": str(row.get("ask") or "")[:200],
        "state": row.get("state"),
        "delivery_state": row.get("delivery_state"),
        # Bounded like every other field here; the reason is a short token
        # (`attempt_cap`, `no_sender_session`, …), never prose.
        "delivery_error": str(row.get("delivery_error") or "")[:200] or None,
        "notify_operator": bool(row.get("notify_operator")),
        "dispatched_at": row.get("dispatched_at"),
        "started_at": row.get("started_at"),
        # How long it sat behind the concurrency cap before its turn started;
        # None until it starts. Its budget never ran during this wait.
        "queued_seconds": (
            int(max(0.0, (row.get("started_at") or 0.0) - (row.get("dispatched_at") or 0.0)))
            if row.get("started_at")
            else None
        ),
        "parent_turn_id": row.get("parent_turn_id") or None,
        "completed_at": row.get("completed_at"),
        "elapsed_seconds": int(
            max(
                0.0,
                (row.get("completed_at") or time.time()) - (row.get("dispatched_at") or 0.0),
            )
        ),
        "session_id": row.get("target_session_id") or None,
        "reply_chars": len(reply),
        "reply_excerpt": reply[:400],
        "error": str(result.get("error") or "") or None,
        # Gateway Stage 7. Present only when the dispatch left this machine, so
        # a local status check reads exactly as it always has. The asking agent
        # needs it for the same decision ``delivery_error`` supports: "should I
        # re-send?" has a different answer when the other install was simply
        # not answering than when its agent refused.
        "remote_install_id": row.get("remote_install_id") or None,
        "remote": result.get("remote") or None,
    }
