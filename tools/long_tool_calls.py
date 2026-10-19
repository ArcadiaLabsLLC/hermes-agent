"""Fork-owned long tool calls: a call that outlives its threshold moves to the background.

Owner ruling 2026-10-18 (``runtime-queue.md`` RT-LONG-TOOL-CALLS-BACKGROUND, design in
``docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md`` §2).

The join, end to end:

1. **Armed only inside a live serve turn.** ``tools/registry.py::dispatch`` asks :func:`armed`;
   it answers yes only when the calling thread is a tool call the serve's live-turn registry
   (``agent_runtime.live_turns``) recorded — so a CLI, gateway or TUI turn never pays a thread.
   :data:`NEVER_PROMOTE` tools are never bracketed (their result must land in-turn, or they own
   their own background door: ``terminal(background=True)``, ``delegate_task``).
2. **The bracket.** :func:`bracket` runs the call on a worker thread (the caller's contextvars
   copied) and waits. Past the threshold — :data:`DECLARED_GRACE_S` for a tool declared long-running
   (:func:`declare_long_running`), else :data:`THRESHOLD_S` — or on the operator's "Send to
   background" (:func:`request_promotion`, ``runtime.work.background.promote``), the caller
   returns :func:`running_in_background` — ``{"status": "running_in_background", "handle":
   "bg:<id>"}`` — so the provider gets its one tool_result per tool_use and the turn goes on.
   Nothing is promoted while the session holds a blocking approval prompt. An interrupt of the
   turn while the call is still foreground is forwarded to the worker (cooperative).
3. **Re-entry.** A promoted call's finish puts a :data:`EVENT_TYPE` event on
   ``process_registry.completion_queue``, routed like a background ``terminal``'s completion
   (``mcp_job_wake.routing_for_call``); the fork event table (``tools/fork_completion_events.py``)
   formats it and settles it; the serve drain forges the continuation turn.
4. **Background work.** Every promoted call is a row in ``<background-work home>/tool_calls.json``
   (``running`` -> ``ready`` / ``failed`` / ``cancelled``), read by ``running_work``'s
   ``BackgroundToolCallLane`` as a ``tool_call`` row (``work_id = tool_call:bg:<id>``), gone once
   a drain settles the wake or past its own ``expires_at``. Cancel (``runtime.work.cancel``) sets
   the worker thread's interrupt bit; the wake then carries ``cancelled``.
5. **Lost on restart.** A ``running`` row whose writer died never finishes; the serve boot's
   :func:`sweep_orphaned_rows` re-owns it as ``lost`` and queues a ``tool_call_finished`` wake with
   ``outcome = "lost"``, settled like any finish.
6. **Await semantics.** No turn blocks on a promoted call. The same tool with the same arguments in
   the same session while one runs returns the existing handle (:func:`bracket`'s dedupe).

Receipts are log lines (``long_tool_call_receipt {json}``), never keys on a wire envelope.

Stdlib-only at import: ``tools/registry.py`` imports this at module scope.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

EVENT_TYPE = "tool_call_finished"
#: The ruled default (owner 2026-10-18): a call still running at 45 s moves to the background.
THRESHOLD_S = 45.0
#: A tool declared long-running is promoted almost at once; a short grace keeps a quick answer inline.
DECLARED_GRACE_S = 5.0
_POLL_S = 0.2
#: Tools whose result must land in the turn that asked, or that own their own background door.
NEVER_PROMOTE = frozenset({
    "clarify",          # the question IS the turn
    "terminal",         # its own door: background=True + notify_on_complete, and the yield seam
    "process",          # manages terminal's background processes; quick by construction
    "delegate_task",    # its own async door
    "execute_code",     # its sandbox calls tools back into THIS turn
    "todo",             # mutates the conversation's plan
    "memory",           # mutates the agent's memory the turn reads next
})
CHECKPOINT_FILENAME = "tool_calls.json"
ROW_RUNNING, ROW_READY, ROW_FAILED, ROW_CANCELLED = "running", "ready", "failed", "cancelled"
#: A promoted call whose writer died before it finished (RT-LONG-CALL-WAKE-LOST-ON-RESTART): the
#: boot sweep re-owns the row and wakes the session with this outcome.
ROW_LOST = "lost"
LOST_RESULT = ("The runtime restarted while this call ran; its result was never produced. "
               "Re-issue the call if you still need it.")
_RESULT_CHARS = 12000
_LABEL_CHARS = 160
#: How long a running row is trusted with no finish (the worker thread is in this process; the
#: reader also proves the writer pid) and how long a finished row lingers unsettled.
_RUNNING_TTL_S = 24 * 3600.0
_FINISHED_TTL_S = 30 * 60.0
_LIVE_TURNS = "agent_runtime.live_turns"

_declared: set[str] = set()


def declare_long_running(*names: str) -> None:
    """Declare tools long-running: promoted after :data:`DECLARED_GRACE_S`, not :data:`THRESHOLD_S`."""
    _declared.update(str(name) for name in names if name)


def is_declared_long_running(name: str, entry: Any = None) -> bool:
    return name in _declared or bool(getattr(entry, "long_running", False))


@dataclass
class _Call:
    handle: str
    tool_name: str
    args_key: str
    routing: dict
    turn_id: str
    call_id: str
    label: str
    started_wall: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)
    worker_tid: Optional[int] = None
    done: threading.Event = field(default_factory=threading.Event)
    promote_requested: threading.Event = field(default_factory=threading.Event)
    promote_reason: str = ""
    result: Any = None
    promoted: bool = False
    cancel_requested: bool = False


_lock = threading.Lock()
_calls: dict[str, _Call] = {}
#: Rows of promoted calls this process wrote, keyed by handle; outlive the call until settled.
_rows: dict[str, dict] = {}


# ── arming ────────────────────────────────────────────────────────────────────


def _live_call() -> Optional[tuple[str, str, str]]:
    """``(turn_id, call_id, tool_name)`` when THIS thread runs a live serve turn's tool call."""
    live = sys.modules.get(_LIVE_TURNS)
    if live is None:
        return None
    try:
        return live.call_on_thread(threading.get_ident())
    except Exception:
        return None


def armed(name: str, entry: Any = None) -> bool:
    """Bracket this dispatch? Only a promotable tool, only on a live serve turn's tool thread."""
    if name in NEVER_PROMOTE:
        return False
    return _live_call() is not None


# ── the bracket ───────────────────────────────────────────────────────────────


def bracket(name: str, args: Any, call_kwargs: Mapping[str, Any], run: Callable[[], Any], *, entry: Any = None) -> Any:
    """Run *run* (the inline dispatch) on a worker; return its result, or the background handle."""
    live = _live_call()
    turn_id, call_id = (live[0], live[1]) if live else ("", "")
    routing = _routing(call_kwargs)
    args_key = _args_key(args)
    existing = _running_twin(name, args_key, routing.get("session_key", ""))
    if existing is not None:
        _receipt("deduplicated", existing, reason="same_tool_same_args")
        return running_in_background(existing, reused=True)
    call = _Call(handle=f"bg:{uuid.uuid4().hex[:12]}", tool_name=name, args_key=args_key, routing=routing,
                 turn_id=turn_id, call_id=call_id, label=_call_label(name, args))
    with _lock:
        _calls[call.handle] = call
    ctx = contextvars.copy_context()
    worker = threading.Thread(target=ctx.run, args=(_work, call, run), name=f"long-tool-{call.handle}", daemon=True)
    worker.start()
    call.worker_tid = worker.ident
    _note_worker(call)
    threshold = DECLARED_GRACE_S if is_declared_long_running(name, entry) else THRESHOLD_S
    return _await(call, threshold)


def _await(call: _Call, threshold: float) -> Any:
    from tools import interrupt as _interrupt

    deadline = call.started_mono + threshold
    forwarded = False
    while True:
        if call.done.wait(_POLL_S):
            return _take_inline(call)
        if not forwarded and _interrupt.is_interrupted():
            # The turn was stopped while the call is still ITS call: stop the worker too.
            forwarded = True
            if call.worker_tid is not None:
                _interrupt.set_interrupt(True, call.worker_tid, reason="turn_interrupted")
        if forwarded:
            continue
        due = call.promote_requested.is_set() or time.monotonic() >= deadline
        if not due or _approval_pending(call.routing):
            continue
        reason = call.promote_reason or ("declared" if threshold == DECLARED_GRACE_S else "threshold")
        with _lock:
            if call.done.is_set():
                break
            call.promoted = True
            _rows[call.handle] = _running_row(call)
            _write_checkpoint_locked(call.routing.get("checkpoint", ""))
        _receipt("promoted", call, reason=reason)
        return running_in_background(call)
    return _take_inline(call)


def _take_inline(call: _Call) -> Any:
    with _lock:
        _calls.pop(call.handle, None)
    return call.result


def _work(call: _Call, run: Callable[[], Any]) -> None:
    try:
        result = run()
    except BaseException as exc:  # the dispatch normalizes; this is the last guard
        result = json.dumps({"error": f"Tool execution failed: {type(exc).__name__}: {exc}"})
    finally:
        _clear_interrupt(call.worker_tid)
    with _lock:
        call.result = result
        call.done.set()
        promoted = call.promoted
        if promoted:
            _calls.pop(call.handle, None)
            outcome = _outcome(call, result)
            row = _rows.get(call.handle)
            if row is not None:
                wall = time.time()
                row.update(status=outcome, finished_at=wall, elapsed_ms=_elapsed_ms(call),
                           expires_at=wall + _FINISHED_TTL_S)
                _write_checkpoint_locked(row["checkpoint"])
    if promoted:
        _queue_wake(_wake_event(call, result))


def _clear_interrupt(tid: Optional[int]) -> None:
    if tid is None:
        return
    try:
        from tools import interrupt as _interrupt
        _interrupt.set_interrupt(False, tid)  # thread idents are reused: never leave the bit behind
    except Exception:
        pass


def running_in_background(call: _Call, *, reused: bool = False) -> str:
    """The synthetic tool result a promoted call returns to the turn."""
    note = ("An identical call is already running in the background; this is its handle. "
            if reused else "This call is still running and has moved to the background. ")
    return json.dumps({
        "status": "running_in_background",
        "handle": call.handle,
        "tool": call.tool_name,
        "message": note + "Its result will arrive as a new message when it finishes; do not poll "
                          "or call it again. Continue with anything that does not need its result.",
    })


# ── operator controls (runtime.work.background.promote / runtime.work.cancel) ──


def request_promotion(turn_id: str, call_id: str) -> dict:
    """Send a live foreground call to the background now. Typed answer, never raises."""
    with _lock:
        call = next((c for c in _calls.values()
                     if c.turn_id == str(turn_id or "") and c.call_id == str(call_id or "")), None)
        if call is None:
            return {"status": "error", "code": "not_promotable",
                    "detail": "no promotable foreground call with that id is running in this process"}
        if call.promoted:
            return {"status": "ok", "outcome": "already_background", "handle": call.handle}
        call.promote_reason = "operator"
        call.promote_requested.set()
    return {"status": "ok", "outcome": "promote_requested", "handle": call.handle}


def promotable_handle(turn_id: str, call_id: str) -> Optional[str]:
    """The handle of a bracketed, still-foreground call (the running card's Send-to-background test)."""
    with _lock:
        for call in _calls.values():
            if call.turn_id == turn_id and call.call_id == call_id and not call.promoted:
                return call.handle
    return None


def cancel(handle: str) -> dict:
    """Cancel a promoted call: the worker's interrupt bit (cooperative). Typed answer, never raises."""
    with _lock:
        call = _calls.get(str(handle or ""))
        if call is None or not call.promoted:
            return {"status": "error", "code": "not_owned_here", "detail": "no background call with that handle runs here"}
        call.cancel_requested = True
        tid = call.worker_tid
        row = _rows.get(call.handle)
        if row is not None:
            row["cancel_requested"] = True
            _write_checkpoint_locked(row["checkpoint"])
    if tid is not None:
        from tools import interrupt as _interrupt
        _interrupt.set_interrupt(True, tid, reason="operator_cancel")
    _receipt("cancel_requested", call, reason="operator")
    return {"status": "cancel_requested", "code": "", "handle": call.handle}


# ── the wake ──────────────────────────────────────────────────────────────────


def _outcome(call: _Call, result: Any) -> str:
    if call.cancel_requested:
        return ROW_CANCELLED
    text = _result_text(result)
    try:
        parsed = json.loads(text)
    except ValueError:
        return ROW_READY
    return ROW_FAILED if isinstance(parsed, dict) and parsed.get("error") else ROW_READY


def _result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        parts = [str(part.get("text") or "") for part in result["content"] if isinstance(part, dict)]
        return "\n".join(p for p in parts if p) or "(non-text result)"
    return str(result)


def _bounded_redacted(text: str) -> str:
    if len(text) > _RESULT_CHARS:
        text = text[:_RESULT_CHARS] + "… [truncated]"
    try:
        from agent.redact import redact_sensitive_text
        return redact_sensitive_text(text)
    except Exception:
        return text


def _wake_event(call: _Call, result: Any) -> dict:
    route = call.routing
    return {
        "type": EVENT_TYPE,
        "session_id": f"tool_call:{call.handle}",  # the drains' per-event identity
        "session_key": route.get("session_key", ""), "task_id": route.get("task_id", ""),
        "owner_task_id": route.get("owner_task_id", ""), "parent_session_id": route.get("parent_session_id", ""),
        "handle": call.handle, "tool": call.tool_name, "outcome": _outcome(call, result),
        "elapsed_ms": _elapsed_ms(call), "result": _bounded_redacted(_result_text(result)),
    }


def _wake_event_from_row(row: Mapping[str, Any], outcome: str, result: str) -> dict:
    """The row-shaped twin of :func:`_wake_event`: a wake for a call this process never ran."""
    return {
        "type": EVENT_TYPE,
        "session_id": f"tool_call:{row.get('handle')}",
        "session_key": str(row.get("session_key") or ""), "task_id": str(row.get("task_id") or ""),
        "owner_task_id": str(row.get("owner_task_id") or ""),
        "parent_session_id": str(row.get("parent_session_id") or ""),
        "handle": str(row.get("handle") or ""), "tool": str(row.get("tool_name") or "?"), "outcome": outcome,
        "elapsed_ms": int(row.get("elapsed_ms") or 0), "result": result,
    }


def sweep_orphaned_rows(homes: Iterable[Path], *, now: Callable[[], float] = time.time,
                        identity: Optional[Callable[[Any, Any], tuple]] = None) -> list[str]:
    """Serve boot: re-own every promoted call whose writer is provably gone, and wake its session.

    For each ``tool_calls.json`` under *homes*: a ``running`` row whose ``(pid, host_start_time)``
    is dead or recycled becomes a :data:`ROW_LOST` row owned by THIS process (so the reader keeps it
    and :func:`note_wake_settled` retires it), and a ``tool_call_finished`` wake with
    ``outcome = "lost"`` is queued. A ``lost`` row of a dead writer (a second restart before its wake
    settled) is re-owned and re-woken — the drains key the event by ``tool_call:<handle>``. An
    unprovable pid (no baseline, unreadable start time) is left alone. A ``running`` row past its own
    ``expires_at`` is left to expire (the reader already shows nothing). Returns the swept handles.
    Never raises per file: an unreadable checkpoint is skipped.
    """
    from agent_runtime.running_work.vocabulary import PID_DEAD, PID_RECYCLED
    if identity is None:
        from agent_runtime.running_work.ownership import _pid_identity as identity
    wall = float(now())
    pid, start = _writer()
    swept: list[tuple[dict, bool]] = []
    for home in homes:
        path = Path(home) / CHECKPOINT_FILENAME
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(stored, list):
            continue
        adopted: list[tuple[dict, bool]] = []
        for entry in stored:
            if not isinstance(entry, dict) or not entry.get("handle"):
                continue
            status = entry.get("status")
            if status not in (ROW_RUNNING, ROW_LOST) or entry.get("pid") == pid:
                continue
            expires = entry.get("expires_at")
            if status == ROW_RUNNING and isinstance(expires, (int, float)) and expires <= wall:
                continue
            if identity(entry.get("pid"), entry.get("host_start_time"))[2] not in (PID_DEAD, PID_RECYCLED):
                continue
            row = dict(entry)
            if status == ROW_RUNNING:
                started = row.get("started_at")
                elapsed = int(max(0.0, wall - float(started)) * 1000) if isinstance(started, (int, float)) else 0
                row.update(status=ROW_LOST, finished_at=wall, elapsed_ms=elapsed)
            row.update(pid=pid, host_start_time=start, checkpoint=str(path), expires_at=wall + _FINISHED_TTL_S)
            adopted.append((row, status == ROW_LOST))
        if not adopted:
            continue
        with _lock:
            for row, _again in adopted:
                _rows.setdefault(str(row["handle"]), row)
            _write_checkpoint_locked(str(path))
        swept.extend(adopted)
    for row, again in swept:
        logger.info("long_tool_call_receipt %s", json.dumps({
            "event": "lost", "handle": row["handle"], "tool": row.get("tool_name"),
            "session_key": row.get("session_key", ""), "rewoken": again}))
        _queue_wake(_wake_event_from_row(row, ROW_LOST, LOST_RESULT))
    return [str(row["handle"]) for row, _again in swept]


def _queue_wake(event: dict) -> None:
    from tools.process_registry import process_registry
    process_registry.completion_queue.put(event)
    logger.info("long_tool_call_receipt %s", json.dumps({
        "event": "finished", "handle": event["handle"], "tool": event["tool"], "outcome": event["outcome"],
        "elapsed_ms": event["elapsed_ms"], "session_key": event["session_key"]}))


def format_tool_call_finished(evt: Mapping[str, Any]) -> str:
    """The ``[IMPORTANT: ...]`` text a drain injects for a ``tool_call_finished`` event."""
    seconds = round((evt.get("elapsed_ms") or 0) / 1000)
    return (f"[IMPORTANT: Background tool call {evt.get('tool', '?')} ({evt.get('handle', '?')}) finished "
            f"({evt.get('outcome') or 'ready'}) after {seconds}s. Its result:\n{evt.get('result') or '(empty)'}]")


def note_wake_settled(evt: Mapping[str, Any]) -> bool:
    """A drain is done with this wake: retire its background-work row. True when a row was removed."""
    if not isinstance(evt, Mapping) or evt.get("type") != EVENT_TYPE:
        return False
    with _lock:
        row = _rows.pop(str(evt.get("handle") or ""), None)
        if row is not None:
            _write_checkpoint_locked(row["checkpoint"])
    return row is not None


# ── background-work rows (running_work's BackgroundToolCallLane reads these) ──


def _running_row(call: _Call) -> dict:
    pid, start = _writer()
    return {
        "handle": call.handle, "tool_name": call.tool_name, "label": call.label, "status": ROW_RUNNING,
        "started_at": call.started_wall, "finished_at": None, "elapsed_ms": None, "cancel_requested": False,
        "session_key": str(call.routing.get("session_key") or ""),
        "task_id": str(call.routing.get("task_id") or ""),
        "owner_task_id": str(call.routing.get("owner_task_id") or ""),
        "parent_session_id": str(call.routing.get("parent_session_id") or ""), "turn_id": call.turn_id,
        "tool_call_id": call.call_id, "expires_at": time.time() + _RUNNING_TTL_S,
        "pid": pid, "host_start_time": start, "checkpoint": str(call.routing.get("checkpoint") or ""),
    }


def _write_checkpoint_locked(path: str) -> None:
    """Rewrite *path*: this process's rows for it, plus other writers' unexpired rows."""
    if not path:
        return
    pid, wall = _writer()[0], time.time()
    mine = [dict(row) for row in _rows.values() if row["checkpoint"] == path]
    owned = {row["handle"] for row in mine}  # a row this process re-owned replaces the dead writer's copy
    try:
        from utils import atomic_json_write
        try:
            stored = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = []
        others = [e for e in stored if isinstance(e, dict) and e.get("pid") != pid and e.get("handle") not in owned
                  and isinstance(e.get("expires_at"), (int, float)) and e["expires_at"] > wall] \
            if isinstance(stored, list) else []
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, others + mine)
    except Exception:
        logger.warning("background tool-call checkpoint %s could not be written", Path(path).name, exc_info=True)


def _writer() -> tuple[int, Any]:
    from tools.mcp_job_wake import writer_identity
    return writer_identity()


# ── helpers ───────────────────────────────────────────────────────────────────


def _routing(call_kwargs: Mapping[str, Any]) -> dict:
    """The caller's routing (read on the CALLER's thread) plus this process's checkpoint path."""
    try:
        from tools.mcp_job_wake import routing_for_call
        routing = routing_for_call(call_kwargs)
    except Exception:
        routing = {"session_key": "", "task_id": str(call_kwargs.get("task_id") or "")}
    try:
        from agent_runtime.profile_home import get_hermes_background_work_home
        routing["checkpoint"] = str(Path(get_hermes_background_work_home()) / CHECKPOINT_FILENAME)
    except Exception:
        routing["checkpoint"] = ""
    return routing


def _approval_pending(routing: Mapping[str, Any]) -> bool:
    session_key = str(routing.get("session_key") or "")
    if not session_key:
        return False
    try:
        from tools.approval import has_blocking_approval
        return bool(has_blocking_approval(session_key))
    except Exception:
        return False


def _args_key(args: Any) -> str:
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except Exception:
        return repr(args)


def _running_twin(name: str, args_key: str, session_key: str) -> Optional[_Call]:
    with _lock:
        return next((c for c in _calls.values() if c.promoted and not c.done.is_set() and c.tool_name == name
                     and c.args_key == args_key and c.routing.get("session_key", "") == session_key), None)


def _call_label(name: str, args: Any) -> str:
    detail = ""
    if isinstance(args, dict):
        for value in args.values():
            if isinstance(value, str) and value.strip():
                detail = value.strip().splitlines()[0]
                break
    return (f"{name}: {detail}" if detail else name)[:_LABEL_CHARS]


def _elapsed_ms(call: _Call) -> int:
    return int((time.monotonic() - call.started_mono) * 1000)


def _note_worker(call: _Call) -> None:
    """Tell the live-turn registry which thread now executes the call (foreground/MCP progress join)."""
    live = sys.modules.get(_LIVE_TURNS)
    if live is None or call.worker_tid is None:
        return
    try:
        live.set_call_worker(call.turn_id, call.call_id, call.worker_tid)
    except Exception:
        logger.debug("live-turn worker join failed", exc_info=True)


def _receipt(event: str, call: _Call, *, reason: str) -> None:
    logger.info("long_tool_call_receipt %s", json.dumps({
        "event": event, "handle": call.handle, "tool": call.tool_name, "reason": reason,
        "elapsed_ms": _elapsed_ms(call), "turn_id": call.turn_id, "tool_call_id": call.call_id,
        "session_key": call.routing.get("session_key", "")}))


def reset_for_tests() -> None:
    with _lock:
        _calls.clear()
        _rows.clear()
