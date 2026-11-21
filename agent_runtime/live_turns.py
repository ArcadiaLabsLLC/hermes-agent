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
a process: :func:`interrupt_tool_call` sets ONE call's thread interrupt bit — the bit the
command's own wait loop reads — and the turn carries on; ending a turn is the agent's own
``interrupt`` (``/stop``, the conversation's Stop), reached from here by :func:`stop_live_turn`: every reply
registers ONE stop handle when its handler starts (:func:`turn_stop_handle`, upstream's ``InterruptScope``),
whoever started it, and both Stop doors reach it through ``agent_runtime.turn_stop.stop_turn``
(``RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM``).
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
    "call_on_thread",
    "interrupt_tool_call",
    "interrupt_turn",
    "live_turn",
    "live_turn_view",
    "persona_instance_of",
    "set_call_worker",
    "stop_live_turn",
    "stop_when_started",
    "tool_finished",
    "tool_started",
    "turn_stop_handle",
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
    #: The agent's plan as of the read (its todo store's items, raw), or None when
    #: the agent keeps no store or it cannot be read. ``()`` is an empty plan.
    plan: tuple[dict[str, Any], ...] | None = None
    #: The folder the turn runs in (its run request's ``workdir``), or "" when none was set.
    workdir: str = ""
    #: The marker on the turn's user message (``relay_policy``): who asked; "" for the operator.
    asked_by_marker: str = ""


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
    #: The thread actually executing the call when a long-call bracket moved it onto a worker
    #: (``tools/long_tool_calls.py``); the foreground / MCP-progress joins key on this one.
    exec_tid: int | None = None


@dataclass
class _Turn:
    turn_id: str
    session_id: str
    persona_instance_id: str
    agent: Any
    started_at: float = field(default_factory=time.time)
    calls: dict[str, _Call] = field(default_factory=dict)
    workdir: str = ""
    asked_by_marker: str = ""


_lock = threading.Lock()
_turns: dict[str, _Turn] = {}


@dataclass(eq=False)
class _StopHandle:
    """One reply's stop handle, from the turn handler's first line to its last: upstream's ``InterruptScope``.

    ``args`` is the handler's namespace, read when a Stop looks: the handler mints a missing client message
    id and resolves the conversation as it goes, so neither is fixed at registration.
    """

    scope: Any
    args: Any

    def turn_id(self) -> str:
        from agent_runtime.serde import safe_assignment_token

        return safe_assignment_token(getattr(self.args, "client_message_id", None) or "")

    def session_id(self) -> str:
        return str(getattr(self.args, "session_id", None) or "")


class _ScopeLink:
    """The reply's own scope, tracked in the scope it was started under (a serve request's, or the turn of
    the agent that relayed it): a stop of the outer work still reaches this reply, never the reverse."""

    def __init__(self, scope: Any) -> None:
        self._scope = scope

    def hard_interrupt(self, message: str | None = None, *, tool_reason: str | None = None) -> None:
        self._scope.cancel(message or "Stopped", tool_reason=tool_reason)


_handles: list[_StopHandle] = []
#: Stops told to a reply still waiting in its conversation's send queue: ``turn id -> (conversation,
#: monotonic)``. Taken by the reply's handle when it starts; a stale one (the reply never started) expires.
_pending_stops: dict[str, tuple[str, float]] = {}
_PENDING_STOP_SECONDS = 6 * 3600.0
_STOP_REASON = "Stopped by the user"


@contextmanager
def turn_stop_handle(args: Any) -> Iterator[None]:
    """Register the reply's ONE stop handle for the handler's whole life (``RT-STOP-REACHES-EVERY-RUNNING-
    REPLY-THROUGH-ONE-SEAM``), whoever started it.

    A fresh ``InterruptScope`` is bound for the reply, so every agent its ``run_conversation`` builds joins
    it (``turn_facade``'s ``track_in_interrupt_scope``), and a cancel before the agent exists still lands —
    upstream interrupts an agent that joins a cancelled scope at once. The scope is tracked in the one the
    reply was started under, so the serve request's own cancel (a paired install's cancel, a disconnect)
    still reaches it. A stop told while the reply waited in its queue cancels the scope here.
    """

    from agent.interrupt_scope import InterruptScope, bind_interrupt_scope, track_in_interrupt_scope

    scope = InterruptScope()
    handle = _StopHandle(scope=scope, args=args)
    with _lock:
        _handles.append(handle)
        pending = _pending_stops.pop(handle.turn_id(), None)
    if pending is not None and pending[0] in ("", handle.session_id()) \
            and time.monotonic() - pending[1] < _PENDING_STOP_SECONDS:
        scope.cancel(_STOP_REASON, tool_reason=None)
    try:
        with track_in_interrupt_scope(_ScopeLink(scope)), bind_interrupt_scope(scope):
            yield
    finally:
        with _lock:
            if handle in _handles:
                _handles.remove(handle)


@contextmanager
def live_turn(
    *, turn_id: str, session_id: str, persona_instance_id: str, agent: Any, request: Any = None,
) -> Iterator[None]:
    """Register a turn for the duration of its conversation. A blank id is a no-op.

    ``request`` is the run's request: its ``workdir`` is the folder the card shows and its
    ``persona_chat_user_finish_reason`` the relay marker that says who asked.
    """

    key = str(turn_id or "").strip()
    if not key:
        yield
        return
    turn = _Turn(
        turn_id=key,
        session_id=str(session_id or ""),
        persona_instance_id=str(persona_instance_id or ""),
        agent=agent,
        workdir=str(getattr(request, "workdir", "") or ""),
        asked_by_marker=str(getattr(request, "persona_chat_user_finish_reason", "") or ""),
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


def call_on_thread(tid: int) -> tuple[str, str, str] | None:
    """``(turn_id, call_id, tool_name)`` of the live call that STARTED on thread *tid*, else None.

    The long-call bracket's arming test: only a serve turn's own tool thread answers."""

    with _lock:
        for turn in _turns.values():
            for call in turn.calls.values():
                if call.tid == tid:
                    return turn.turn_id, call.call_id, call.tool_name
    return None


def set_call_worker(turn_id: str | None, call_id: Any, tid: int) -> None:
    """The long-call bracket moved this call onto worker thread *tid*. Unknown call: no-op."""

    with _lock:
        turn = _turns.get(str(turn_id or "").strip())
        call = turn.calls.get(str(call_id or "").strip()) if turn is not None else None
        if call is not None:
            call.exec_tid = tid


def persona_instance_of(agent: Any) -> str | None:
    """The persona instance of the live turn running ``agent``, else None."""

    with _lock:
        return next((turn.persona_instance_id for turn in _turns.values()
                     if turn.agent is agent and turn.persona_instance_id), None)


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


def _todo_items_of(agent: Any) -> tuple[dict[str, Any], ...] | None:
    """The agent's todo items off its own store (``AIAgent._todo_store``), else None.

    ``TodoStore.read`` returns copies, so the reader never holds the writer's dicts."""

    reader = getattr(getattr(agent, "_todo_store", None), "read", None)
    if not callable(reader):
        return None
    try:
        items = reader()
    except Exception:
        return None
    if not isinstance(items, list):
        return None
    return tuple(item for item in items if isinstance(item, dict))


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
        plan=_todo_items_of(turn.agent),
        workdir=turn.workdir,
        asked_by_marker=turn.asked_by_marker,
        tools=tuple(
            LiveToolCall(
                call_id=call.call_id,
                tool_name=call.tool_name,
                preview=call.preview,
                command=call.command,
                started_at=call.started_at,
                elapsed_seconds=round(max(0.0, now - call.started_mono), 1),
                timeout_seconds=call.timeout_seconds,
                foreground=foreground.get(call.exec_tid or call.tid),
                mcp_progress=mcp_progress.get(call.exec_tid or call.tid),
            )
            for call in calls
        ),
    )


def interrupt_tool_call(turn_id: str | None, call_id: Any, *, reason: str) -> bool:
    """Stop ONE in-flight tool call of a live turn; the turn itself carries on. False when not live here.

    The interrupt bit goes to the thread executing the call only (the long-call worker when a
    bracket moved it, else the tool thread) — never ``agent.interrupt()``, which ends the turn.
    A foreground command sees the bit in its wait loop and is killed (rc 130,
    ``[Command interrupted]``); that is the tool result the model reads, and it replies on.
    Set under the registry lock, so a call that already finished is never signalled.
    """

    from tools import interrupt as _interrupt

    with _lock:
        turn = _turns.get(str(turn_id or "").strip())
        call = turn.calls.get(str(call_id or "").strip()) if turn is not None else None
        if call is None:
            return False
        _interrupt.set_interrupt(True, call.exec_tid or call.tid, reason=reason)
    return True


def stop_live_turn(turn_id: str, *, session_id: str, reason: str, any_session: bool = False) -> bool:
    """Stop the reply ``turn_id`` of conversation ``session_id`` running in this process: True when reached.

    Its stop handle's scope is cancelled (the human stop: no tool reason), and the agent registered for the
    turn, if any, gets its own interrupt too — a turn whose agent runs on a thread the scope's context did
    not follow is still reached. ``any_session``: the caller proved the turn's conversation already, so a
    handle that has not resolved its conversation yet matches. ``reason`` is the caller's record.
    """

    key, session = str(turn_id or "").strip(), str(session_id or "")
    if not key:
        return False
    with _lock:
        turn = _turns.get(key)
        turn_session = turn.session_id if turn is not None else None
        handles = [handle for handle in _handles if handle.turn_id() == key
                   and (any_session or session in (handle.session_id(), turn_session))]
    for handle in handles:
        handle.scope.cancel(_STOP_REASON, tool_reason=None)
    agent_reached = turn is not None and (any_session or turn_session == session) \
        and interrupt_turn(key, reason=reason, session_id=None if any_session else session)
    return bool(handles) or agent_reached


def stop_when_started(turn_id: str, *, session_id: str) -> bool:
    """Tell a reply still waiting in its queue to stop the moment it starts. True: recorded; False when it
    has started meanwhile (its handle is registered: stop it as a running reply) or names nothing."""

    key = str(turn_id or "").strip()
    if not key:
        return False
    now = time.monotonic()
    with _lock:
        if any(handle.turn_id() == key for handle in _handles):
            return False
        for stale in [k for k, (_s, at) in _pending_stops.items() if now - at >= _PENDING_STOP_SECONDS]:
            del _pending_stops[stale]
        _pending_stops[key] = (str(session_id or ""), now)
    return True


def interrupt_turn(turn_id: str | None, *, reason: str, session_id: str | None = None) -> bool:
    """End a live turn through its agent's own seam (the soft stop ``/stop`` sends). False when not live here.

    The running tool's thread gets the interrupt bit and the loop ends the turn, which settles
    ``stopped: true``. ``reason`` is the caller's record, not the agent's. ``session_id``, when given, must be the
    turn's own conversation: a Stop that names a turn of another conversation finds nothing here.
    """

    key = str(turn_id or "").strip()
    with _lock:
        turn = _turns.get(key)
        if turn is not None and session_id is not None and turn.session_id != str(session_id):
            turn = None
    interrupt = getattr(turn.agent, "interrupt", None) if turn is not None else None
    if not callable(interrupt):
        return False
    try:
        interrupt()
    except Exception:
        return False
    return True
