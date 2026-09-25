"""The public surface: the collector table, ``build_running_work``, the row
lookup, ``peek_work`` and ``cancel_work``."""

from __future__ import annotations

import time
from typing import Any

from ..parity import ProjectionAccountant

from .lanes_chat import _collect_chat_turns, _collect_delegations, _collect_dispatches
from .lanes_process import _collect_cron, _collect_terminal
from .ownership import _ambient_context
from .rows import _module, _safe_text, _source, _strip_ansi
from .vocabulary import KIND_CHAT_TURN, KIND_CRON_JOB, KIND_DELEGATION, KIND_DISPATCH, KIND_TERMINAL, PEEK_TAIL_LIMIT, REASON_NOT_IN_PROCESS, RUNNING_WORK_KINDS, SOURCE_OK, SOURCE_UNAVAILABLE, STATUS_VALUES

__layer__ = "wiring"


_COLLECTORS = (
    (KIND_TERMINAL, _collect_terminal, True),
    (KIND_DELEGATION, _collect_delegations, True),
    (KIND_CHAT_TURN, _collect_chat_turns, True),
    (KIND_DISPATCH, _collect_dispatches, True),
    (KIND_CRON_JOB, _collect_cron, False),
)


def build_running_work(
    accountant: ProjectionAccountant | None = None,
) -> dict[str, Any]:
    """The ``running_work`` projection: rows + per-source health + counts + ambient.

    Never raises. A lane that blows up in an unforeseen way still yields an
    ``unavailable`` source entry, because a projection that can crash the
    snapshot build is worse than one that admits a blind spot.

    ``rows`` / ``sources`` / ``counts`` are CONTRACT. ``ambient`` is not: it is
    machine-local context (see :func:`_ambient_context`), carried in its own
    named block precisely so it can never again be concatenated into a field a
    consumer branches on.
    """

    now = time.time()
    rows: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}

    for name, collector, takes_now in _COLLECTORS:
        try:
            if takes_now:
                lane_rows, source = collector(now=now, accountant=accountant)
            else:
                lane_rows, source = collector(accountant=accountant)
        except Exception as exc:  # noqa: BLE001 - a lane must never break the frame
            lane_rows, source = [], _source(
                SOURCE_UNAVAILABLE,
                reason="collector_failed",
                detail=type(exc).__name__,
            )
        rows.extend(lane_rows)
        sources[name] = source

    counts = {"total": len(rows)}
    for status in STATUS_VALUES:
        matched = sum(1 for row in rows if row.get("status") == status)
        if matched:
            counts[status] = matched
    counts["unavailable_sources"] = sum(
        1 for entry in sources.values() if entry.get("status") != SOURCE_OK
    )

    return {
        "rows": rows,
        "sources": sources,
        "counts": counts,
        "ambient": _ambient_context(),
    }


def find_work_row(work_id: str) -> dict[str, Any] | None:
    """The single row matching ``work_id``, or None."""

    target = str(work_id or "").strip()
    if not target:
        return None
    for row in build_running_work().get("rows") or []:
        if row.get("work_id") == target:
            return row
    return None


def split_work_id(work_id: str) -> tuple[str, str]:
    """``("terminal", "sess-1")`` for ``"terminal:sess-1"``; ``("", "")`` if malformed.

    Split on the FIRST colon only — session ids and job ids may contain them.
    """

    text = str(work_id or "").strip()
    kind, sep, stable = text.partition(":")
    if not sep or kind not in RUNNING_WORK_KINDS or not stable:
        return "", ""
    return kind, stable


def peek_work(work_id: str) -> dict[str, Any]:
    """Bounded read-only look at what one piece of work is doing.

    Mirrors ``process_registry.poll()``'s READ side and nothing else. It must
    never mark ``_completion_consumed`` (which is what ``read_log``/``wait``
    do), and unlike ``poll`` it does not even record a poll observation: this is
    an operator surface, and letting it register as consumption would suppress
    the autonomous ``notify_on_complete`` delivery turn the agent is waiting on.

    Output buffers are process-local, so a peek from a lane that did not spawn
    the work honestly reports ``tail_available: false`` instead of an empty tail
    that would read as "no output".
    """

    kind, stable = split_work_id(work_id)
    if not kind:
        return {
            "work_id": str(work_id or ""),
            "found": False,
            "error": "malformed_work_id",
        }

    row = find_work_row(work_id)
    payload: dict[str, Any] = {
        "work_id": work_id,
        # ``work_kind``, not ``kind``: this payload is emitted through the
        # stage42 object envelope, whose own ``kind`` names the ENVELOPE shape.
        # A row-level ``kind`` here would silently overwrite it and every
        # consumer branching on envelope kind would mis-route the response.
        "work_kind": kind,
        "found": row is not None,
        "row": row,
        "tail_available": False,
        "tail": "",
        "tail_limit": PEEK_TAIL_LIMIT,
        "consumed": False,
    }
    if row is None:
        return payload

    if kind == KIND_TERMINAL:
        registry = _module("tools.process_registry")
        if registry is None:
            payload["tail_reason"] = REASON_NOT_IN_PROCESS
            return payload
        try:
            session = registry.process_registry.get(stable)
        except Exception:
            session = None
        if session is None:
            payload["tail_reason"] = "session_not_in_registry"
            return payload
        try:
            # Read the rolling buffer directly under the session's own lock.
            # No reconcile, no consumption flag, no state transition.
            with session._lock:  # noqa: SLF001 - the buffer's only guard
                buffered = session.output_buffer or ""
            tail = _strip_ansi(buffered)[-PEEK_TAIL_LIMIT:]
        except Exception as exc:
            payload["tail_reason"] = f"buffer_unreadable:{type(exc).__name__}"
            return payload
        payload["tail_available"] = True
        payload["tail"] = _safe_text(tail, limit=PEEK_TAIL_LIMIT)
        payload["truncated"] = len(buffered) > PEEK_TAIL_LIMIT
        return payload

    # Every other kind reports progress, not output: the row already carries the
    # whole readable truth (status, elapsed, in_tool, seconds_since_progress).
    payload["tail_reason"] = "no_output_stream"
    return payload


def _delegation_owned_here(mod: Any, delegation_id: str) -> bool:
    """True when THIS process holds the live record for ``delegation_id``.

    Ownership is per-record, not per-module: a process can hold some
    delegations and know nothing about others, and only the holder has the
    ``interrupt_fn`` that can actually stop the child.
    """

    try:
        return any(
            str((record or {}).get("delegation_id") or "") == delegation_id
            for record in mod.list_async_delegations()
        )
    except Exception:
        return False


def cancel_work(work_id: str, *, reason: str = "operator_cancel") -> dict[str, Any]:
    """Route a cancel to the owning subsystem's interrupt seam.

    Never a bare PID kill. Terminal work goes through
    ``process_registry.kill_process``, whose tree-kill is identity-guarded by
    the same ``host_start_time`` baseline this projection verifies; delegations
    go through ``interrupt_for_session``, which lets the child unwind and
    deliver partial results through the normal finalize path. Kinds with no
    interrupt seam return a typed ``cancel_unsupported`` rather than pretending.
    """

    kind, stable = split_work_id(work_id)
    if not kind:
        return {"status": "error", "code": "invalid_request", "work_id": str(work_id or "")}

    row = find_work_row(work_id)
    if row is None:
        return {"status": "error", "code": "not_found", "work_id": work_id}

    if kind == KIND_TERMINAL:
        registry = _module("tools.process_registry")
        session = None
        if registry is not None:
            try:
                session = registry.process_registry.get(stable)
            except Exception:
                session = None
        if session is None:
            # The row exists — it came from the durable checkpoint — but the
            # handle lives in another process, so there is nothing here to kill.
            # The same positive-ownership rule the read lanes apply: falling
            # through to `kill_process` would return `not_found` and report
            # "no such work" about work that is demonstrably running.
            return {
                "status": "error",
                "code": "cancel_unavailable",
                "work_id": work_id,
                "detail": REASON_NOT_IN_PROCESS,
                "owning_lane": "serve",
            }
        try:
            # consume_output=False: a cancel is not the agent reading its
            # output, so it must not suppress the completion notification.
            result = registry.process_registry.kill_process(
                stable, source="harness.work_cancel", consume_output=False
            )
        except Exception as exc:
            return {
                "status": "error",
                "code": "cancel_failed",
                "work_id": work_id,
                "detail": type(exc).__name__,
            }
        killed = str(result.get("status")) != "not_found"
        return {
            "status": "cancelled" if killed else "error",
            "code": "" if killed else "not_found",
            "work_id": work_id,
            "kind": kind,
            "result": _safe_text(result.get("status"), limit=80),
        }

    if kind == KIND_DELEGATION:
        mod = _module("tools.async_delegation")
        if mod is None or not _delegation_owned_here(mod, stable):
            # The interrupt callable lives in the record map of the process that
            # dispatched the child. From anywhere else `interrupt_for_session`
            # matches nothing and returns 0, which the caller would otherwise
            # read as "the cancel failed" rather than "ask the owning lane".
            return {
                "status": "error",
                "code": "cancel_unavailable",
                "work_id": work_id,
                "detail": REASON_NOT_IN_PROCESS,
                "owning_lane": "serve",
            }
        session_id = (row.get("owner") or {}).get("session_id") or ""
        if not session_id:
            return {
                "status": "error",
                "code": "cancel_unavailable",
                "work_id": work_id,
                "detail": "delegation row carries no owning session",
            }
        try:
            interrupted = mod.interrupt_for_session(
                parent_session_id=str(session_id), reason=reason
            )
        except Exception as exc:
            return {
                "status": "error",
                "code": "cancel_failed",
                "work_id": work_id,
                "detail": type(exc).__name__,
            }
        if not interrupted:
            return {
                "status": "error",
                "code": "cancel_failed",
                "work_id": work_id,
                "detail": "no running delegation matched the owning session",
            }
        return {
            "status": "cancelled",
            "code": "",
            "work_id": work_id,
            "kind": kind,
            "interrupted": int(interrupted),
        }

    return {
        "status": "error",
        "code": "cancel_unsupported",
        "work_id": work_id,
        "kind": kind,
        "detail": f"{kind} work has no interrupt seam in v1",
    }
