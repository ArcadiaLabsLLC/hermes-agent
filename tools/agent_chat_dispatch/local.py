"""The supervisor pool and the local leg: spawn, stamp, wait, settle; and the status the tool returns.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any

from .child import (
    _MAX_STREAM_CHARS,
    _STDERR_EXCERPT,
    KILL_GRACE_SECONDS,
    _BoundedTail,
    _child_identity,
    _detached_error_text,
    _drain,
    _kill_child,
    _release_pumps,
    build_dispatch_argv,
    child_environment,
    parse_child_payload,
)
from .remote import _run_remote_dispatch

logger = logging.getLogger(__name__)

__layer__ = "lanes"


_executor = None
_executor_lock = threading.Lock()
_executor_max_workers = 0

#: Dispatch ids this process is actively supervising — and the guard that keeps
#: the orphan sweep from answering for them.
#:
#: The sweep became PERIODIC in the previous commit, which turned a theoretical
#: second writer into a real one: from the instant a child exits until this
#: supervisor's ``record_completion`` lands — across ``proc.wait()`` and two
#: pump joins — the sweep sees a dead PID on a ``running`` row and settles it
#: ``unknown``. The 5s drain then delivers "the outcome is unknown" for a
#: dispatch that COMPLETED, and the supervisor's real answer, written moments
#: later, is absorbed by the delivery-turn replay dedup — so the sender is told
#: nothing is known and never receives the answer sitting in the row.
#:
#: A row still supervised HERE is not an orphan by definition, so the sweep
#: skips it. Process-local on purpose, and sufficient: the race is between two
#: threads of one serve process, and a row whose supervisor died is exactly the
#: row the sweep SHOULD settle.
_supervised: set[str] = set()
_supervised_lock = threading.Lock()


def _mark_supervised(dispatch_id: str) -> None:
    with _supervised_lock:
        _supervised.add(str(dispatch_id))


def _forget_supervised(dispatch_id: str) -> None:
    with _supervised_lock:
        _supervised.discard(str(dispatch_id))


def supervised_dispatch_ids() -> set[str]:
    """A snapshot of every dispatch this process is actively supervising.

    The orphan sweep reads this to know which ``running`` rows are not orphans
    at all. Returns a COPY: the sweep iterates while supervisors come and go,
    and handing out the live set would make that a mutation-during-iteration
    bug on a background thread.
    """

    with _supervised_lock:
        return set(_supervised)


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
        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            # Never inherit the parent's stdin: in serve that is the launcher's
            # request pipe, and a child reading from it would steal requests.
            "stdin": subprocess.DEVNULL,
            "env": env,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            try:
                from hermes_cli._subprocess_compat import windows_hide_flags

                popen_kwargs["creationflags"] = windows_hide_flags()
            except Exception:
                pass
        proc = subprocess.Popen(argv, **popen_kwargs)
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

    out_thread = _drain(proc.stdout, stdout_tail)
    err_thread = _drain(proc.stderr, stderr_tail)

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
    _release_pumps(proc, (out_thread, err_thread))

    stdout_text = stdout_tail.text()
    stderr_text = stderr_tail.text()
    payload = parse_child_payload(stdout_text)

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
