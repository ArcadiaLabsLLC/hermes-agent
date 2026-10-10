"""Fork-owned MCP progress relay: a server's ``notifications/progress`` reaches the
calling tool's ``tool.progress`` beat.

hermes' MCP client sent no ``_meta.progressToken`` on ``tools/call``, so a server
that reports progress (the launcher QA server's ~5 min isolated rebuild: phase,
commit, elapsed, expected) was never allowed to, and the Agent Console card read
"running" with nothing else for the whole wait (hermes ``runtime-queue.md``, the
MCP-progress row). This module is the whole fork half; the upstream MCP client
keeps three one-line seams (``tools/mcp_tool_transport.py``: instrument the live
session and adopt its timeouts, tee the session's ``message_handler``; ``tools/registry.py``: bracket an
``mcp-*`` dispatch).

The join, end to end, with no name matching:

1. ``registry.dispatch`` runs an MCP handler on the tool's worker thread — the
   thread :mod:`agent_runtime.live_turns` recorded at ``tool_started``.
   :func:`enter_dispatch` opens a record keyed by THAT thread and by the identity
   of the ``args`` dict it hands the handler.
2. The handler awaits ``session.call_tool(name, arguments=args)`` on the MCP
   loop thread with the same dict object. :func:`instrument_session` finds the
   record by that identity and sends ``_meta.progressToken`` = the record's own
   token (one per attempt; a replayed call gets a fresh one).
3. The server's ``notifications/progress`` naming that token reaches the
   session's ``message_handler``; :func:`tee_message_handler` folds it into the
   record — ``progress``, ``total``, ``message``, and from ``_meta`` the
   ``phase`` and ``expected_ms`` a server states (top level, or under one vendor
   key such as the QA server's ``stagec_qa_build``).
4. ``live_turns.live_turn_view`` joins :func:`snapshot_by_tid` on the call's
   thread, and the heartbeat puts it on the frame.

An MCP call whose server reports nothing still beats, as ``progress_state:
"none_reported"`` — the console can say "no progress reported" instead of
leaving the operator to guess.

Reset-on-progress (the spec's ``resetTimeoutOnProgress``, with its
``maxTotalTimeout``): the configured per-server tool timeout (``mcp_servers.<name>
.timeout`` > ``timeouts.mcp.tool_call`` > 300 s) becomes an IDLE bound — each
progress report for the call restarts it — and the outer deadline the handler
waits on becomes the cap: ``mcp_servers.<name>.max_total_timeout`` >
``timeouts.mcp.tool_call_max_total`` > :data:`DEFAULT_MAX_TOTAL_TIMEOUT_S`
(1800 s); ``0`` turns it off. A silent call still times out at the base. The
upstream deadline lives in ``tools/mcp_tool_loop._run_on_mcp_loop``, which the
fork does not edit, so :func:`adopt_progress_timeout` raises
``server.tool_timeout`` to the cap at session start (before tools register)
and this module enforces the base inside the call. The resource/prompt utility
RPCs report no progress and keep the base. A server registered lazily from the
schema cache keeps the base on its FIRST call (its handler was built before the
session existed); every handler registered after the session starts gets the
cap. The agent's own per-call deadline (``timeouts.tools.sequential_call``,
420 s default) is a separate bound this does not move.

Nothing here blocks a writer longer than a dict operation, and a failure in the
relay never fails the call.
"""

from __future__ import annotations

import inspect
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

__layer__ = "stores"

__all__ = [
    "DEFAULT_MAX_TOTAL_TIMEOUT_S",
    "McpProgress",
    "adopt_progress_timeout",
    "enter_dispatch",
    "exit_dispatch",
    "instrument_session",
    "observe_notification",
    "snapshot_by_tid",
    "tee_message_handler",
]

logger = logging.getLogger(__name__)

#: The registry toolset prefix every MCP server's tools are registered under.
MCP_TOOLSET_PREFIX = "mcp-"
#: Bound on a phase a server names; a phase is a word, not a paragraph.
PHASE_MAX_CHARS = 64
#: The cap a progressing call may run to when nothing narrower is configured.
DEFAULT_MAX_TOTAL_TIMEOUT_S = 1800.0
#: The ``timeouts.*`` key (``agent.deadline.resolve_timeout``) for the process-wide cap.
MAX_TOTAL_TIMEOUT_KEY = "mcp.tool_call_max_total"
#: Session RPCs the registry's utility tools await; bounded by the base, never reset.
UTILITY_RPCS = ("read_resource", "get_prompt", "list_resources", "list_prompts")
_PROGRESS_METHOD = "notifications/progress"
_INSTRUMENTED = "__hermes_mcp_progress_relay__"


@dataclass(frozen=True)
class McpProgress:
    """One MCP call's progress, as of the read that produced it.

    ``reported`` is False until the server sends a notification for this call;
    every other field is then None except ``updates`` (0).
    """

    server: str
    tool: str
    reported: bool
    updates: int
    progress: float | None = None
    total: float | None = None
    message: str | None = None
    phase: str | None = None
    expected_ms: int | None = None
    seconds_since_update: float | None = None


@dataclass
class _Record:
    args: Any
    toolset: str
    owner_tid: int
    server: str = ""
    tool: str = ""
    token: str | None = None
    updates: int = 0
    progress: float | None = None
    total: float | None = None
    message: str | None = None
    phase: str | None = None
    expected_ms: int | None = None
    last_mono: float | None = None
    opened_mono: float = field(default_factory=time.monotonic)


_lock = threading.Lock()
_by_args: dict[int, _Record] = {}
_by_token: dict[str, _Record] = {}
#: server name -> (base idle timeout, cap) for servers with reset-on-progress adopted.
_adopted: dict[str, tuple[float, float]] = {}
_tokens = itertools.count(1)


# ------------------------------------------------------------ dispatch side

def enter_dispatch(args: Any, toolset: Any) -> _Record | None:
    """Open a record for an ``mcp-*`` dispatch on the CALLING thread; None otherwise.

    Called by ``registry.dispatch`` before the handler runs. Never raises.
    """

    if not isinstance(args, dict) or not str(toolset or "").startswith(MCP_TOOLSET_PREFIX):
        return None
    record = _Record(args=args, toolset=str(toolset), owner_tid=threading.get_ident())
    with _lock:
        _by_args[id(args)] = record
    return record


def exit_dispatch(record: _Record | None) -> None:
    """Close what :func:`enter_dispatch` opened. ``None`` is a no-op."""

    if record is None:
        return
    with _lock:
        if _by_args.get(id(record.args)) is record:
            del _by_args[id(record.args)]
        if record.token is not None and _by_token.get(record.token) is record:
            del _by_token[record.token]


def snapshot_by_tid() -> dict[int, McpProgress]:
    """Every open MCP dispatch's progress, keyed by the thread that dispatched it."""

    now = time.monotonic()
    with _lock:
        records = list(_by_args.values())
        return {record.owner_tid: _view(record, now) for record in records}


def _view(record: _Record, now: float) -> McpProgress:
    server = record.server or record.toolset[len(MCP_TOOLSET_PREFIX):]
    return McpProgress(
        server=server,
        tool=record.tool,
        reported=record.updates > 0,
        updates=record.updates,
        progress=record.progress,
        total=record.total,
        message=record.message,
        phase=record.phase,
        expected_ms=record.expected_ms,
        seconds_since_update=round(max(0.0, now - record.last_mono), 1) if record.last_mono is not None else None,
    )


# ------------------------------------------------------------ session side

def _begin_attempt(server_name: str, tool_name: str, arguments: Any) -> str | None:
    """A fresh token for this ``call_tool`` attempt, or None when no dispatch owns ``arguments``."""

    if arguments is None:
        return None
    with _lock:
        record = _by_args.get(id(arguments))
        if record is None or record.args is not arguments:
            return None
        if record.token is not None and _by_token.get(record.token) is record:
            del _by_token[record.token]
        token = f"hermes-progress-{next(_tokens)}"
        record.token, record.server, record.tool = token, str(server_name or ""), str(tool_name or "")
        _by_token[token] = record
    return token


def _end_attempt(token: str) -> None:
    with _lock:
        record = _by_token.pop(token, None)
        if record is not None and record.token == token:
            record.token = None


def _accepts_meta(call_tool: Any) -> bool:
    try:
        return "meta" in inspect.signature(call_tool).parameters
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------ timeouts

def _positive_seconds(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _resolve_cap(server: Any) -> float | None:
    """``mcp_servers.<name>.max_total_timeout`` > ``timeouts.mcp.tool_call_max_total`` >
    :data:`DEFAULT_MAX_TOTAL_TIMEOUT_S`. ``0`` (or negative) turns reset-on-progress off."""

    config = getattr(server, "_config", None)
    if isinstance(config, Mapping) and config.get("max_total_timeout") is not None:
        return _positive_seconds(config.get("max_total_timeout"))
    try:
        from agent.deadline import resolve_timeout

        return resolve_timeout(MAX_TOTAL_TIMEOUT_KEY, default=DEFAULT_MAX_TOTAL_TIMEOUT_S)
    except Exception:
        return DEFAULT_MAX_TOTAL_TIMEOUT_S


def adopt_progress_timeout(server: Any, server_name: str) -> tuple[float, float] | None:
    """Reset-on-progress for one server: its configured ``tool_timeout`` becomes the
    per-call IDLE bound this module enforces, and ``server.tool_timeout`` — the outer
    deadline every handler registered after this point waits on — becomes the cap.

    Idempotent across reconnects (a ``tool_timeout`` already raised to the recorded
    cap keeps the recorded base). None, and the base left in place, when the base is
    unbounded or no cap above it is configured.
    """

    current = _positive_seconds(getattr(server, "tool_timeout", None))
    with _lock:
        adopted = _adopted.get(server_name)
    base = adopted[0] if adopted is not None and current == adopted[1] else current
    if base is None:
        return None
    cap = _resolve_cap(server)
    if cap is None or cap <= base:
        with _lock:
            _adopted.pop(server_name, None)
        server.tool_timeout = base
        return None
    server.tool_timeout = cap
    with _lock:
        _adopted[server_name] = (base, cap)
    return base, cap


def _last_heard(token: str | None, started: float) -> float:
    if token is None:
        return started
    with _lock:
        record = _by_token.get(token)
        last = record.last_mono if record is not None else None
    return max(started, last) if last is not None else started


async def _idle_bounded(coro: Any, server_name: str, op: str, token: str | None) -> Any:
    """Await ``coro`` under the server's adopted idle bound; every progress report for
    ``token`` restarts it. Without an adoption, a plain await."""

    with _lock:
        limits = _adopted.get(server_name)
    if limits is None:
        return await coro
    base, cap = limits
    # Deferred: tools.registry imports this module, and a module-scope asyncio import puts
    # the event-loop stack (sockets/_overlapped on Windows) on every registry import path.
    import asyncio

    started = time.monotonic()
    task = asyncio.ensure_future(coro)
    try:
        while True:
            remaining = _last_heard(token, started) + base - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"MCP call timed out after {time.monotonic() - started:.1f}s: {op} on '{server_name}' "
                    f"reported no progress for {base:.1f}s (configured timeout: {base:.1f}s; "
                    f"progress extends it up to {cap:.1f}s)"
                )
            done, _pending = await asyncio.wait({task}, timeout=remaining)
            if task in done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _instrument_utility(session: Any, server_name: str, method: str) -> None:
    original = getattr(session, method, None)
    if not inspect.iscoroutinefunction(original) or getattr(original, _INSTRUMENTED, False):
        return

    async def bounded(*args: Any, **kwargs: Any) -> Any:
        return await _idle_bounded(original(*args, **kwargs), server_name, method, None)

    setattr(bounded, _INSTRUMENTED, True)
    setattr(session, method, bounded)


def instrument_session(session: Any, server_name: str, server: Any = None) -> bool:
    """Make ``session.call_tool`` ask for progress when a dispatch owns the call, and
    bound it by the server's idle timeout, restarted by each progress report.

    With ``server``, also adopts reset-on-progress for it
    (:func:`adopt_progress_timeout`); the utility RPCs the registry's
    resource/prompt tools await are bounded by the same base (they report no
    progress), so raising the outer deadline to the cap never lengthens them.
    Binds instance attributes, so ``server.session is session`` still holds.
    False (and the session untouched) when the SDK's ``call_tool`` takes no
    ``meta`` or the session cannot be patched. Idempotent.
    """

    original = getattr(session, "call_tool", None)
    if original is None or getattr(original, _INSTRUMENTED, False) or not _accepts_meta(original):
        return False

    async def call_tool(name: str, arguments: Any = None, *args: Any, **kwargs: Any) -> Any:
        meta = kwargs.get("meta")
        token = None
        if meta is None or (isinstance(meta, Mapping) and "progressToken" not in meta):
            try:
                token = _begin_attempt(server_name, name, arguments)
            except Exception:
                logger.debug("MCP progress relay: begin failed for %s/%s", server_name, name, exc_info=True)
        if token is not None:
            kwargs["meta"] = {**(meta or {}), "progressToken": token}
        try:
            return await _idle_bounded(
                original(name, arguments, *args, **kwargs), server_name, f"tools/call {name}", token)
        finally:
            if token is not None:
                _end_attempt(token)

    setattr(call_tool, _INSTRUMENTED, True)
    try:
        session.call_tool = call_tool
        for method in UTILITY_RPCS:
            _instrument_utility(session, server_name, method)
    except Exception:
        logger.debug("MCP progress relay: session for %s cannot be instrumented", server_name, exc_info=True)
        return False
    if server is not None:
        adopt_progress_timeout(server, server_name)
    return True


def tee_message_handler(handler: Any) -> Any:
    """Wrap a session ``message_handler`` so progress is observed first; the
    wrapped handler still sees every message, and a relay failure never reaches it."""

    async def _tee(message: Any) -> Any:
        try:
            observe_notification(message)
        except Exception:
            logger.debug("MCP progress relay: notification not observed", exc_info=True)
        return await handler(message)

    return _tee


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _stated(meta: Any, key: str) -> Any:
    """``meta[key]``, else the first ``meta[<vendor>][key]`` — where a server states it."""

    if not isinstance(meta, Mapping):
        return None
    if key in meta:
        return meta[key]
    for value in meta.values():
        if isinstance(value, Mapping) and key in value:
            return value[key]
    return None


def observe_notification(message: Any) -> bool:
    """Fold a ``notifications/progress`` for an owned token into its record.

    Accepts the SDK's typed notification (2.x: the payload IS the message; 1.x:
    under ``.root``). True when a record took it.
    """

    payload = getattr(message, "root", message)
    if getattr(payload, "method", None) != _PROGRESS_METHOD:
        return False
    params = getattr(payload, "params", None)
    token = getattr(params, "progress_token", None)
    if isinstance(token, bool) or not isinstance(token, (str, int)):
        return False
    progress = _number(getattr(params, "progress", None))
    total = _number(getattr(params, "total", None))
    text = getattr(params, "message", None)
    meta = getattr(params, "meta", None)
    expected = _number(_stated(meta, "expected_ms"))
    phase = _stated(meta, "phase")
    with _lock:
        record = _by_token.get(str(token))
        if record is None:
            return False
        record.updates += 1
        record.last_mono = time.monotonic()
        record.progress = progress
        record.total = total
        record.message = text if isinstance(text, str) else None
        if expected is not None and expected >= 0:
            record.expected_ms = int(expected)
        if isinstance(phase, str) and phase.strip():
            record.phase = phase.strip()[:PHASE_MAX_CHARS]
    return True
