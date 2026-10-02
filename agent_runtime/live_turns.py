"""Live chat turns in THIS process: who is executing, what tool call is in flight,
and the turn's interrupt seam.

The turn journal is the durable "an agent is thinking" fact and is readable from
anywhere, but it cannot say what the turn is DOING: which tool it is inside, how
long that tool has run, whether the foreground command under it has printed
anything, or how many model calls the turn has made. Only the process executing
the turn knows, so this registry is process-local by construction — the serve
that runs a turn registers it, and a reader in that same process (the snapshot's
running-work projection, the chat stream's heartbeat) asks it. A reader in any
other process finds nothing here and must keep saying "no live progress", which
is the honest durable answer (hermes ``runtime-queue.md`` RW1-RW3).

An MCP tool's server-reported progress joins the same way, on the same
thread id, through :mod:`tools.mcp_progress_relay`.

Writers: ``profile_runner.execute`` registers a turn around its conversation and
feeds the runner's ``run.tool.started`` / ``run.tool.finished`` callbacks in.
Those callbacks fire on the tool's worker thread, so the thread id recorded at
start is the one ``BaseEnvironment.execute`` waits on — the exact join to
:mod:`tools.environments.foreground_watch`, never a match on command text.

Reads never block a writer for longer than a dict copy, and nothing here signals
a process: :func:`interrupt_turn` is the agent's own ``interrupt`` — the seam
``/stop`` and the wall budget already use.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

__layer__ = "stores"

__all__ = [
    "LiveToolCall",
    "LiveTurn",
    "interrupt_turn",
    "live_turn",
    "live_turn_view",
    "tool_finished",
    "tool_started",
]

_FOREGROUND_WATCH = "tools.environments.foreground_watch"
_MCP_PROGRESS_RELAY = "tools.mcp_progress_relay"


@dataclass(frozen=True)
class LiveToolCall:
    """One in-flight tool call of a live turn, as of the read that produced it."""

    call_id: str
    tool_name: str
    preview: str
    command: str
    started_at: float
    elapsed_seconds: float
    timeout_seconds: int | None
    #: The foreground command this call is blocked on (``ForegroundCommand``), or
    #: None — a non-terminal tool, a command not yet spawned, or one already gone.
    foreground: Any = None
    #: The MCP call this tool is dispatching (``McpProgress``: what its server has
    #: reported, or that it has reported nothing), or None — not an MCP tool.
    mcp_progress: Any = None


@dataclass(frozen=True)
class LiveTurn:
    """A live turn: identity, the agent's own counters, and its in-flight calls."""

    turn_id: str
    session_id: str
    persona_instance_id: str
    started_at: float
    api_calls: int | None
    seconds_since_activity: float | None
    tools: tuple[LiveToolCall, ...] = ()


@dataclass
class _Call:
    call_id: str
    tool_name: str
    preview: str
    command: str
    timeout_seconds: int | None
    tid: int
    started_at: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)


@dataclass
class _Turn:
    turn_id: str
    session_id: str
    persona_instance_id: str
    agent: Any
    started_at: float = field(default_factory=time.time)
    calls: dict[str, _Call] = field(default_factory=dict)


_lock = threading.Lock()
_turns: dict[str, _Turn] = {}


@contextmanager
def live_turn(*, turn_id: str, session_id: str, persona_instance_id: str, agent: Any) -> Iterator[None]:
    """Register a turn for the duration of its conversation. A blank id is a no-op."""

    key = str(turn_id or "").strip()
    if not key:
        yield
        return
    turn = _Turn(
        turn_id=key,
        session_id=str(session_id or ""),
        persona_instance_id=str(persona_instance_id or ""),
        agent=agent,
    )
    with _lock:
        _turns[key] = turn
    try:
        yield
    finally:
        with _lock:
            if _turns.get(key) is turn:
                del _turns[key]


def tool_started(
    turn_id: str | None,
    call_id: Any,
    tool_name: Any,
    *,
    preview: str = "",
    command: str = "",
    timeout_seconds: int | None = None,
) -> None:
    """A tool call began on the CALLING thread. Unknown turn: no-op."""

    key, call = str(turn_id or "").strip(), str(call_id or "").strip()
    if not key or not call:
        return
    record = _Call(
        call_id=call,
        tool_name=str(tool_name or "tool"),
        preview=str(preview or ""),
        command=str(command or ""),
        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else None,
        tid=threading.get_ident(),
    )
    with _lock:
        turn = _turns.get(key)
        if turn is not None:
            turn.calls[call] = record


def tool_finished(turn_id: str | None, call_id: Any) -> None:
    key, call = str(turn_id or "").strip(), str(call_id or "").strip()
    with _lock:
        turn = _turns.get(key)
        if turn is not None:
            turn.calls.pop(call, None)


def _activity(agent: Any) -> tuple[int | None, float | None]:
    """``(api_calls, seconds_since_activity)`` off the agent's own summary, else Nones."""

    reader = getattr(agent, "get_activity_summary", None)
    if not callable(reader):
        return None, None
    try:
        summary = reader()
    except Exception:
        return None, None
    if not isinstance(summary, dict):
        return None, None
    calls = summary.get("api_call_count")
    quiet = summary.get("seconds_since_activity")
    return (
        int(calls) if isinstance(calls, int) and not isinstance(calls, bool) else None,
        float(quiet) if isinstance(quiet, (int, float)) and not isinstance(quiet, bool) else None,
    )


def _foreground_by_tid() -> dict[int, Any]:
    watch = sys.modules.get(_FOREGROUND_WATCH)
    if watch is None:
        return {}
    try:
        commands = watch.snapshot()
    except Exception:
        return {}
    by_tid: dict[int, Any] = {}
    for command in commands:
        if command.owner_tid is not None:
            by_tid.setdefault(command.owner_tid, command)
    return by_tid


def _mcp_progress_by_tid() -> dict[int, Any]:
    relay = sys.modules.get(_MCP_PROGRESS_RELAY)
    if relay is None:
        return {}
    try:
        return dict(relay.snapshot_by_tid())
    except Exception:
        return {}


def live_turn_view(turn_id: str | None) -> LiveTurn | None:
    """The live view of ``turn_id``, or None when this process is not executing it."""

    key = str(turn_id or "").strip()
    with _lock:
        turn = _turns.get(key)
        if turn is None:
            return None
        calls = sorted(turn.calls.values(), key=lambda item: item.started_mono)
    now = time.monotonic()
    foreground = _foreground_by_tid() if calls else {}
    mcp_progress = _mcp_progress_by_tid() if calls else {}
    api_calls, quiet = _activity(turn.agent)
    return LiveTurn(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        persona_instance_id=turn.persona_instance_id,
        started_at=turn.started_at,
        api_calls=api_calls,
        seconds_since_activity=quiet,
        tools=tuple(
            LiveToolCall(
                call_id=call.call_id,
                tool_name=call.tool_name,
                preview=call.preview,
                command=call.command,
                started_at=call.started_at,
                elapsed_seconds=round(max(0.0, now - call.started_mono), 1),
                timeout_seconds=call.timeout_seconds,
                foreground=foreground.get(call.tid),
                mcp_progress=mcp_progress.get(call.tid),
            )
            for call in calls
        ),
    )


def interrupt_turn(turn_id: str | None, *, reason: str) -> bool:
    """Interrupt a live turn through its agent's own seam. False when not live here."""

    key = str(turn_id or "").strip()
    with _lock:
        turn = _turns.get(key)
    if turn is None:
        return False
    interrupt = getattr(turn.agent, "interrupt", None)
    if not callable(interrupt):
        return False
    try:
        # The soft stop ``/stop`` sends: the running tool's thread gets the
        # interrupt bit (a foreground command is killed, rc 130) and the loop
        # ends the turn. ``reason`` is the caller's record, not the agent's.
        interrupt()
    except Exception:
        return False
    return True
