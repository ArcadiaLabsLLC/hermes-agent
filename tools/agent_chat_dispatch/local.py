"""The supervisor pool and the local leg: spawn, stamp, wait, settle; and the status the tool returns.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Any

from agent_runtime.dispatch_store.supervision import (
    _forget_supervised,
    _mark_supervised,
    supervised_dispatch_ids,
)
from agent_runtime.subprocess_pumps import drain, release_pumps

from .child import (
    _MAX_STREAM_CHARS,
    _STDERR_EXCERPT,
    KILL_GRACE_SECONDS,
    _BoundedTail,
    _child_identity,
    _detached_error_text,
    _kill_child,
    build_dispatch_argv,
    child_environment,
    parse_child_payload,
)
from .cancel_watch import CANCEL_POLL_SECONDS, ensure_cancel_watch
from .remote import _run_remote_dispatch

logger = logging.getLogger(__name__)

__layer__ = "lanes"


_executor = None
_executor_lock = threading.Lock()
_executor_max_workers = 0

def _get_executor(max_workers: int):
    """The shared dispatch executor, resized when the configured cap grows.

    These workers no longer RUN turns — they supervise child processes — so the
    pool is a concurrency cap rather than a compute pool. It stays
    daemon-threaded: a supervisor blocked on a 30-minute child must never hold
    interpreter exit open (stdlib pool workers are joined unconditionally by an
    atexit hook).

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


#: Cancellations asked of dispatches THIS process supervises: dispatch id ->
#: reason. Written by :func:`request_cancel`, read by the supervisor at the
#: two points a cancel can land (before the spawn, and after the child exits)
#: and consumed by the settle. The supervisor owns the ``proc`` handle on its
#: own stack, so the request has to travel through here rather than a method
#: on something the canceller could reach.
_CANCEL_REQUESTED: dict[str, str] = {}
_CANCEL_LOCK = threading.Lock()

CANCEL_STOPPING = "stopping"
CANCEL_CANCELLED = "cancelled"
CANCEL_ALREADY_FINISHED = "already_finished"
CANCEL_NOT_OWNED_HERE = "not_owned_here"
#: D1.07 (owner ruling a): another process supervises a running child; the
#: durable mark is written and that process's cancel watch stops it.
CANCEL_REQUESTED = "cancel_requested"


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

    * ``cancelled`` -- it had not spawned yet (queued behind the concurrency
      cap); the row is settled ``cancelled`` here and the worker that later
      picks it up sees the mark and runs nothing.
    * ``stopping`` -- a child is running; it is tree-killed through the one
      identity-guarded kill, and the SUPERVISOR settles the row when the child
      is gone. "Stopping" is reported until that happens, never "stopped".
    * ``already_finished`` -- the row is terminal; its result is kept as is.

    A dispatch another process on this machine supervises is cancelled through
    the row (D1.07, owner ruling a): see :func:`_request_cancel_elsewhere`. The
    mark is set BEFORE the row is re-read and the spawn checks the mark AFTER
    stamping the owner, so a cancel racing a spawn is caught by one side or the
    other, never dropped by both — for the in-process mark and the durable one.
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
    if dispatch_id not in supervised_dispatch_ids():
        return _request_cancel_elsewhere(dispatch_id, row, reason)
    _request_cancel_mark(dispatch_id, reason)
    row = dispatch_store.get_dispatch(dispatch_id) or row
    owner_pid = row.get("owner_pid")
    if owner_pid and row.get("started_at"):
        _kill_child(int(owner_pid), row.get("owner_started_at"))
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_STOPPING, "reason": reason}
    # Not spawned: settle it now. The worker consults the mark before spawning.
    dispatch_store.record_completion(
        dispatch_id,
        state=dispatch_store.STATE_CANCELLED,
        error=_cancelled_text(reason, spawned=False),
        only_if_running=True,
    )
    return {"dispatch_id": dispatch_id, "outcome": CANCEL_CANCELLED, "reason": reason}


def _request_cancel_elsewhere(dispatch_id: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    """Cancel a dispatch another process supervises: through the row, never a pid.

    The durable mark is written first; then a row that never started is settled
    ``cancelled`` here, exactly as its owner would (its worker reads the mark
    and runs nothing), and a running child is left to its supervisor's cancel
    watch, which stops it within :data:`CANCEL_POLL_SECONDS` —
    ``cancel_requested`` says so rather than claiming a stop. A row no live
    process supervises keeps the mark and settles when the orphan sweep sees its
    child gone.
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
            error=_cancelled_text(reason, spawned=False),
            only_if_running=True,
        )
        return {"dispatch_id": dispatch_id, "outcome": CANCEL_CANCELLED, "reason": reason}
    return {
        "dispatch_id": dispatch_id,
        "outcome": CANCEL_REQUESTED,
        "reason": reason,
        "poll_seconds": CANCEL_POLL_SECONDS,
    }


def _cancelled_text(reason: str, *, spawned: bool) -> str:
    where = "before it replied" if spawned else "before it started"
    return f"the dispatch was cancelled {where} ({reason}); nothing was delivered"


def _run_dispatch(dispatch_id: str, spec: dict[str, Any]) -> None:
    """Spawn one child turn, wait for it, and record its outcome.

    Never raises, and that is now STRUCTURAL rather than a claim this docstring
    makes about the code below it. The body used to run unguarded, so a raise
    before the spawn — ``build_dispatch_argv`` subscripting a malformed spec,
    ``child_environment`` failing — left the row ``running`` and owned by the
    sender's still-live serve PID, which the orphan sweep can therefore never
    settle: running forever, with nobody waiting on a Future to notice, because
    ``executor.submit`` discards it. The wrapper below turns every such raise
    into a recorded terminal state.
    """

    try:
        _run_dispatch_guarded(dispatch_id, spec)
    except BaseException as exc:  # noqa: BLE001 - a detached turn must never vanish
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
    branch inside the spawn**: a cross-install dispatch does not spawn a child
    at all, so everything below — the argv, the environment, the PID stamp, the
    kill-after-grace — describes work that is not happening on this machine. The
    two legs meet again at ``record_completion``, which is the only thing the
    rest of the lane reads.
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
            error=_cancelled_text(durable, spawned=False),
            only_if_running=True,
        )
        return

    # ``spec["max_seconds"]`` everywhere: the tool always sets it, and reading
    # the same key two ways (subscript here, ``.get(...) or 1800`` there) is how
    # a spec-shape bug hides behind a default that looks deliberate.
    budget = float(spec["max_seconds"])
    # Minted HERE: the turn's clock starts when the turn starts, not when the
    # dispatch was enqueued behind the concurrency cap.
    deadline_epoch = time.time() + budget
    argv = build_dispatch_argv(spec, deadline_epoch=deadline_epoch)
    env = child_environment(spec)

    stdout_tail = _BoundedTail(_MAX_STREAM_CHARS)
    stderr_tail = _BoundedTail(_MAX_STREAM_CHARS)
    try:
        proc = _spawn_child(argv, env)
    except Exception as exc:
        logger.exception("detached dispatch %s could not spawn", dispatch_id)
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_ERROR,
            error=f"the dispatch process could not be started: {type(exc).__name__}: {exc}",
        )
        return

    # The row's owner becomes the CHILD the moment it exists. That is what keeps
    # the orphan sweep coherent without this supervisor: "is the work still
    # running" becomes a question about the process actually doing it, so a
    # serve that dies mid-dispatch leaves a row that settles when the child
    # exits rather than one frozen on a dead thread's PID.
    started_at = _child_identity(proc.pid)
    try:
        dispatch_store.set_dispatch_owner(
            dispatch_id, owner_pid=proc.pid, owner_started_at=started_at
        )
    except Exception:  # pragma: no cover - bookkeeping must not abort the run
        logger.debug("dispatch %s owner stamp failed", dispatch_id, exc_info=True)

    durable = "" if _peek_cancel_mark(dispatch_id) is not None else _durable_cancel_reason(dispatch_id)
    if durable:
        _request_cancel_mark(dispatch_id, durable)
    if _peek_cancel_mark(dispatch_id) is not None:
        # The cancel landed between the queue check and the owner stamp, so
        # nobody killed anything yet. This side does.
        _kill_child(proc.pid, started_at)

    out_thread = drain(proc.stdout, stdout_tail)
    err_thread = drain(proc.stderr, stderr_tail)

    exit_reason = ""
    try:
        returncode = proc.wait(timeout=budget + KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        # The child was supposed to settle itself at --max-seconds. It did not,
        # so it is wedged rather than slow, and the sender is owed a terminal
        # answer instead of an indefinitely `running` row.
        exit_reason = "budget_exceeded"
        _kill_child(proc.pid, started_at)
        try:
            returncode = proc.wait(timeout=30)
        except Exception:
            returncode = -1
    except Exception as exc:  # pragma: no cover - defensive
        exit_reason = f"wait_failed:{type(exc).__name__}"
        returncode = -1

    # Join the pumps so nothing the child wrote is missed, then force them loose
    # rather than leaking a thread per dispatch on a pipe a survivor holds open.
    release_pumps(proc, (out_thread, err_thread))
    try:
        _settle_local(
            dispatch_id, budget, returncode, exit_reason, stdout_tail.text(), stderr_tail.text(),
            cancel_reason=_peek_cancel_mark(dispatch_id),
        )
    finally:
        # Taken only once the row is settled: a cancel watch pass between a take
        # and the settle would read "running, no mark here" and ask again.
        _take_cancel_mark(dispatch_id)


def _spawn_child(argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start the child — :mod:`tools.agent_chat_dispatch.local_child`, behind ``conversations.subprocess_worker``.

    A profile that may start no subprocess (the phone: that switch off, the in-process
    peer its only worker) leaves ``local_child`` out; the dispatch then settles as an
    error that says so, through the caller's could-not-spawn path.
    """

    from agent_runtime.conversations.worker import subprocess_worker_enabled

    if not subprocess_worker_enabled():
        raise RuntimeError("this profile starts no subprocess (conversations.subprocess_worker is off)")
    from .local_child import spawn_child

    return spawn_child(argv, env)


def _settle_local(
    dispatch_id: str,
    budget: float,
    returncode: int,
    exit_reason: str,
    stdout_text: str,
    stderr_text: str,
    *,
    cancel_reason: str | None = None,
) -> None:
    """Record the local child's outcome: stopped, no payload, or its payload's verdict.

    ``cancel_reason`` is the mark a :func:`request_cancel` left. It decides the
    row only when the child produced NO payload: a child that had already
    replied when the kill arrived keeps its reply, because the sender asked for
    that answer before anyone stopped asking.
    """

    from agent_runtime import dispatch_store

    payload = parse_child_payload(stdout_text)
    if cancel_reason is not None and payload is None:
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_CANCELLED,
            error=_cancelled_text(cancel_reason, spawned=True),
        )
        return
    if exit_reason:
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_ERROR,
            error=(
                f"the dispatch exceeded its {budget:.0f}s budget (plus a "
                f"{KILL_GRACE_SECONDS:.0f}s grace) and was stopped. Anything it wrote "
                "before that is in its own chat thread."
                if exit_reason == "budget_exceeded"
                else f"the dispatch supervisor failed: {exit_reason}"
            ),
            target_session_id=str((payload or {}).get("session_id") or ""),
        )
        return

    if payload is None:
        # No payload is a runtime failure, not a result — say so rather than
        # inventing an empty reply the sender would read as "nothing to report".
        dispatch_store.record_completion(
            dispatch_id,
            state=dispatch_store.STATE_UNKNOWN,
            error=(
                f"the dispatch process exited with code {returncode} without a reply "
                "payload; the outcome is unknown."
                + (f" stderr: {stderr_text[-_STDERR_EXCERPT:]}" if stderr_text.strip() else "")
            ),
        )
        return

    ok = bool(payload.get("ok")) and returncode == 0
    # This process is the LAST one holding the child's payload — the row is all
    # the sender ever sees — so whether that turn produced anything visible has
    # to be recorded here or it is gone. `ok` does not answer it: a turn whose
    # model returned no content comes back `ok` with an empty reply, and the
    # sender then reads the same blank as a reply that never made it out.
    # Read, never re-derived: `agent_runtime.turn_visibility` owns the verdict.
    from agent_runtime.turn_visibility import TurnVisibility

    dispatch_store.record_completion(
        dispatch_id,
        state=dispatch_store.STATE_COMPLETED if ok else dispatch_store.STATE_ERROR,
        reply=str(payload.get("reply") or ""),
        error="" if ok else _detached_error_text(payload),
        target_session_id=str(payload.get("session_id") or payload.get("chat_session_id") or ""),
        total_tokens=payload.get("total_tokens"),
        visibility=TurnVisibility.from_payload(payload).as_dict(),
    )


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
    longer burns budget while it waits — the clock is minted at spawn.
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
        # How long it sat behind the concurrency cap before a child existed;
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
