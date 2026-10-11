"""The public surface: the collector table, ``build_running_work``, the row
lookup, ``peek_work`` and ``cancel_work``."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ..projection_accountant import ProjectionAccountant

from .lanes_build import _collect_builds
from .lanes_chat import _collect_chat_turns, _collect_delegations, _collect_dispatches
from .lanes_process import _collect_cron, _collect_mcp_jobs, _collect_terminal
from ..builds.registry import BuildLogRefused, build_log_tail
from ..builds.vocabulary import SOURCE_AGENT, SOURCE_ANNOUNCED, TAIL_SOURCE_TERMINAL
from .ownership import _ambient_context
from .rows import _module, bounded_operator_text, _source, _strip_ansi
from .vocabulary import KIND_BUILD, KIND_CHAT_TURN, KIND_CRON_JOB, KIND_DELEGATION, KIND_DISPATCH, KIND_MCP_JOB, KIND_TERMINAL, KIND_TOOL_CALL, KILL_NOT_FOUND, PEEK_TAIL_LIMIT, REASON_NOT_IN_PROCESS, RUNNING_WORK_KINDS, SOURCE_OK, SOURCE_UNAVAILABLE, STATUS_VALUES

__layer__ = "lanes"


_COLLECTORS = (
    (KIND_TERMINAL, _collect_terminal, True),
    (KIND_DELEGATION, _collect_delegations, True),
    (KIND_CHAT_TURN, _collect_chat_turns, True),
    (KIND_DISPATCH, _collect_dispatches, True),
    (KIND_MCP_JOB, _collect_mcp_jobs, True),
    # AFTER the terminal lane: it reclassifies the frame's terminal rows in place.
    (KIND_BUILD, _collect_builds, True),
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
        kwargs: dict[str, Any] = {"now": now, "accountant": accountant} if takes_now else {"accountant": accountant}
        if getattr(collector, "takes_frame_rows", False):
            # The build lane edits the frame so far IN PLACE (terminal → build), one producer step.
            kwargs["frame_rows"] = rows
        try:
            lane_rows, source = collector(**kwargs)
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

    peeker = _PEEKERS.get(kind)
    if peeker is None:
        # Every other kind reports progress, not output: the row already carries the
        # whole readable truth (status, elapsed, in_tool, seconds_since_progress).
        payload["tail_reason"] = "no_output_stream"
        return payload
    return peeker(payload, row, stable)


def _peek_tail(text: str) -> str:
    """The masked, whitespace-collapsed LAST ``PEEK_TAIL_LIMIT`` characters.

    Masked before it is bounded, and bounded from the END: a mask that lengthens the text
    (``KEY=v`` ⇒ ``KEY: [redacted]``) must cost the oldest output, never the newest line; the
    masked window is twice the tail so a secret cut at the window's edge falls outside the tail.
    """

    window = text[-PEEK_TAIL_LIMIT * 2:]
    masked = bounded_operator_text(window, limit=len(window) * 2 + 32)
    return masked[-PEEK_TAIL_LIMIT:]


def _peek_terminal(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """A background process's rolling buffer, read under its own lock — no consumption."""

    registry = _module("tools.process_registry")
    if registry is None:
        payload["tail_reason"] = REASON_NOT_IN_PROCESS
        return payload
    try:
        session = registry.process_registry.get(session_id)
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
    payload["tail"] = _peek_tail(tail)
    payload["truncated"] = len(buffered) > PEEK_TAIL_LIMIT
    return payload


def _peek_build(payload: dict[str, Any], row: dict[str, Any], stable: str) -> dict[str, Any]:
    """A build's output, by source: an agent build IS a terminal process, so its buffer;
    an announced build's writer-declared ``log_path`` tail (else the record's own ``tail``);
    a detected build has no output hermes can see. ``tail_source`` names which was read."""

    source, _sep, ident = stable.partition(":")
    if source == SOURCE_AGENT:
        payload["tail_source"] = TAIL_SOURCE_TERMINAL
        return _peek_terminal(payload, ident)
    if source != SOURCE_ANNOUNCED:
        payload["tail_reason"] = "no_output_stream"
        return payload
    from ..builds.control import announced_record

    record = announced_record(row)
    if record is None:
        payload["tail_reason"] = "build_record_unreadable"
        return payload
    try:
        text, truncated, origin = build_log_tail(record, limit=PEEK_TAIL_LIMIT)
    except BuildLogRefused as refused:
        payload["tail_reason"] = str(refused)
        return payload
    payload["tail_source"] = origin
    payload["tail_available"] = True
    payload["tail"] = _peek_tail(_strip_ansi(text))
    payload["truncated"] = truncated
    return payload


def _live_tool_call(row: dict[str, Any]) -> Any:
    """The ``LiveToolCall`` a ``tool_call`` row names, or None when not live here."""

    from ..live_turns import live_turn_view

    parent = str(row.get("parent_work_id") or "")
    turn_id = parent.partition(":")[2]
    view = live_turn_view(turn_id)
    if view is None:
        return None
    call_id = str(row.get("tool_call_id") or "")
    return next((call for call in view.tools if call.call_id == call_id), None)


def _peek_tool_call(payload: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """RW2: the foreground command's own output tail, read-only, bounded."""

    try:
        call = _live_tool_call(row)
    except Exception as exc:
        payload["tail_reason"] = f"live_turn_unreadable:{type(exc).__name__}"
        return payload
    command = getattr(call, "foreground", None)
    if command is None:
        # Ended between the row and the peek, or executing in another process.
        payload["tail_reason"] = "command_not_live"
        return payload
    buffered = _strip_ansi(command.tail or "")
    payload["tail_available"] = True
    payload["tail"] = _peek_tail(buffered)
    payload["truncated"] = command.output_chars > PEEK_TAIL_LIMIT
    payload["seconds_since_output"] = command.seconds_since_output
    return payload



#: The kinds whose peek reads OUTPUT, each ``(payload, row, stable) -> payload``; every other
#: kind answers ``no_output_stream``. Late-bound so a test may patch one reader by name.
_PEEKERS = {
    KIND_TERMINAL: lambda payload, row, stable: _peek_terminal(payload, stable),
    KIND_TOOL_CALL: lambda payload, row, stable: _peek_tool_call(payload, row),
    KIND_BUILD: lambda payload, row, stable: _peek_build(payload, row, stable),
}

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


def _stamp_epoch(text: str):
    """Epoch seconds for an ISO stamp; naive input is read as UTC.

    Every `started_at` on this wire carries an offset — the projection
    anchors the process registry's naive LOCAL stamps at its boundary
    precisely so this comparison cannot be made against two different
    frames of reference. Before that, a naive local stamp read as UTC
    landed hours in the FUTURE in any UTC-plus timezone, so a
    legitimate cancel issued seconds ago compared as "earlier than the
    work started" and was refused `stale_revision`. The naive branch
    stays as a defensive fallback for a caller-supplied `--issued-at`
    written without an offset, where UTC is the documented reading.
    """

    raw = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _cancel_is_superseded(issued_at: str, started_at: str) -> bool:
    """Replay guard. A cancel issued BEFORE this work started cannot have been
    aimed at it: work ids are stable per spawn, so a retried/queued command
    arriving after the original target died and a new one took its place would
    otherwise kill the wrong thing. Superseding is the same ruling the active
    realm/workspace writes make with --issued-at. An unparseable stamp on
    either side never supersedes."""

    if not (issued_at and started_at):
        return False
    issued_epoch, started_epoch = _stamp_epoch(issued_at), _stamp_epoch(started_at)
    return issued_epoch is not None and started_epoch is not None and issued_epoch < started_epoch


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

    canceller = _CANCELLERS.get(kind)
    if canceller is not None:
        return canceller(work_id, kind, stable, row, reason=reason)

    return {
        "status": "error",
        "code": "cancel_unsupported",
        "work_id": work_id,
        "kind": kind,
        "detail": f"{kind} work has no interrupt seam in v1",
    }


def _cancel_terminal(work_id: str, kind: str, stable: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Terminal work: ``process_registry.kill_process``, identity-guarded, in the owning process only."""
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
    killed = str(result.get("status")) != KILL_NOT_FOUND
    return {
        "status": "cancelled" if killed else "error",
        "code": "" if killed else "not_found",
        "work_id": work_id,
        "kind": kind,
        "result": bounded_operator_text(result.get("status"), limit=80),
    }


def _cancel_delegation(work_id: str, kind: str, stable: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """A delegation: ``interrupt_for_session`` from the process that dispatched it."""
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


def _cancel_tool_call_arm(work_id: str, kind: str, stable: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return _cancel_tool_call(work_id, row, reason=reason)


def _cancel_tool_call(work_id: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """RW2: stop a foreground command through its TURN's interrupt seam.

    Never a pid kill. ``agent.interrupt()`` is the soft stop ``/stop`` sends:
    the tool thread's interrupt bit kills the command (rc 130,
    ``[Command interrupted]``) and the turn ends interrupted. So the cancel is a
    cancel of the turn, and the reply names the turn it stopped.
    """

    from ..live_turns import interrupt_turn

    parent = str(row.get("parent_work_id") or "")
    if not interrupt_turn(parent.partition(":")[2], reason=reason):
        return {
            "status": "error",
            "code": "cancel_unavailable",
            "work_id": work_id,
            "detail": REASON_NOT_IN_PROCESS,
            "owning_lane": "serve",
        }
    return {
        "status": "cancelled",
        "code": "",
        "work_id": work_id,
        "kind": KIND_TOOL_CALL,
        "interrupted_turn": parent,
    }


def _cancel_build(work_id: str, kind: str, stable: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """A build: the source's own seam (``builds.control.stop_build``), every refusal typed."""
    from ..builds.control import stop_build

    return stop_build(row, reason=reason)


def _cancel_dispatch(work_id: str, kind: str, stable: str, row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """A dispatch: ``agent_chat_dispatch.request_cancel`` in the process that supervises it.

    The lane owns the child's handle and the identity-guarded kill; this only
    routes. A dispatch another serve on this machine supervises answers
    ``cancel_requested`` — the durable mark that serve's cancel watch acts on
    (D1.07), reported as a request and never as a kill. ``not_owned_here``
    remains for a process where the lane is not resident at all.
    """

    lane = _module("tools.agent_chat_dispatch")
    if lane is None:
        # The supervisor lives in that module; a process that never imported it
        # supervises nothing, so the row is simply not ours to stop.
        return {"status": "error", "code": "not_owned_here", "work_id": work_id, "kind": kind,
                "detail": "this process does not supervise that dispatch"}
    answer = lane.request_cancel(stable, reason=reason)
    outcome = str(answer.get("outcome") or "")
    if outcome in {"stopping", "cancelled"}:
        return {"status": "ok", "outcome": outcome, "work_id": work_id, "kind": kind, "reason": reason}
    if outcome == "cancel_requested":
        return {"status": "ok", "outcome": outcome, "work_id": work_id, "kind": kind, "reason": reason,
                "detail": "another process supervises it; that process stops it within "
                          f"{answer.get('poll_seconds')}s"}
    if outcome == "already_finished":
        return {"status": "ok", "outcome": outcome, "work_id": work_id, "kind": kind,
                "state": answer.get("state"), "detail": "already finished; its result is kept"}
    return {"status": "error", "code": outcome or "cancel_failed", "work_id": work_id, "kind": kind,
            "detail": "this process does not supervise that dispatch" if outcome == "not_owned_here" else ""}


#: ``cancel_work``'s interrupt seams by work kind; a kind absent here is ``cancel_unsupported``.
_CANCELLERS = {
    KIND_TERMINAL: _cancel_terminal,
    KIND_DELEGATION: _cancel_delegation,
    KIND_TOOL_CALL: _cancel_tool_call_arm,
    KIND_BUILD: _cancel_build,
    KIND_DISPATCH: _cancel_dispatch,
}
