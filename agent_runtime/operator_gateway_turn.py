"""The operator chat's turn, run on the serve's in-process gateway engine (one turn engine).

Row ``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT``; plan
``docs/agent-runtime-harness/planned/operator-chat-on-the-gateway-engine-2026-11-21.md``. An
Intelligence conversation runs ``tui_gateway``'s ``prompt.submit`` on an in-process session
(``conversations/in_process_peer.py``); a Mission Control chat turn now runs the SAME function on a
gateway session of its own, opened on the serve's launch scope (the operator transcript lives in the
head store) with ``source`` :data:`OPERATOR_SOURCE`.

What the operator lane decides about a turn (``profile_runner.execute.AgentRunExecution``: scopes,
budgets, MCP admission, the persona's prompt policy, the tool block, the live-turn registry) is
supplied to the gateway as session policy through the two fork seams it already calls:

* construction — ``worker_app_functions.create_agent`` hands an operator session's build to
  :func:`construct`, which builds the agent the execution would have built and installs the turn door;
* the turn — the door wraps that agent's ``run_conversation``: the gateway calls it from its own turn
  thread and the door runs the execution's phases around the real call there.

The caller (:func:`run_turn`) acquires the chat root's actor (the resident registry still decides
when one is built), submits the composed user message to the session, and waits for the door to hand
back the turn's ``(raw result, agent, timing)`` or its exception. A turn the gateway starts by itself on
an operator session (its goal continuation, a completion notice) reaches the door with no pending
operator turn and runs as an operator turn through :data:`ON_GATEWAY_TURN` (``chat_goal_door``).
"""

from __future__ import annotations

import contextlib
import functools
import logging
import threading
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

__layer__ = "lanes"
__all__ = [
    "OPERATOR_SOURCE",
    "close_actor",
    "construct",
    "inline_agent",
    "is_operator",
    "open_actor",
    "run_turn",
    "set_gateway_turn_handler",
]

logger = logging.getLogger(__name__)

#: The ``source`` an operator chat's gateway session carries; the seams dispatch on it.
OPERATOR_SOURCE = "eternia_operator"

#: How long a turn may run past its wall budget before the caller stops waiting for the door.
_WAIT_GRACE_SECONDS = 60.0


@dataclass
class _Build:
    execution: Any
    agent: Any = None


@dataclass
class _Turn:
    execution: Any
    text: str
    done: threading.Event = field(default_factory=threading.Event)
    outcome: tuple | None = None
    error: BaseException | None = None


_building: ContextVar[_Build | None] = ContextVar("operator_gateway_build", default=None)
#: The agent of the operator turn this thread is running inside the gateway, or None.
_inline: ContextVar[Any] = ContextVar("operator_gateway_inline_agent", default=None)

_lock = threading.Lock()
_pending: dict[str, deque[_Turn]] = {}
_peer: Any = None
#: The open actor on each chat session key: a key has one gateway session at a time.
_actors: dict[str, "_SessionActor"] = {}
_on_gateway_turn: Callable[[Any, str, tuple, dict], Any] | None = None


def is_operator(session: dict | None) -> bool:
    return (session or {}).get("source") == OPERATOR_SOURCE


def inline_agent() -> Any:
    """The agent whose gateway turn this thread is inside (a turn the gateway started), else None."""

    return _inline.get()


def set_gateway_turn_handler(handler: Callable[[Any, str, tuple, dict], Any] | None) -> None:
    """Bind who runs a turn the gateway starts on an operator session (``handler(agent, sid, args,
    kwargs)`` — the gateway's own ``run_conversation`` call); the chat-goal door binds it at serve
    boot. Unbound, such a turn runs bare."""

    global _on_gateway_turn
    _on_gateway_turn = handler


# ── the gateway seam ────────────────────────────────────────────────────────


def construct(sid: str, session: dict) -> Any:
    """Build an operator session's agent (``worker_app_functions.create_agent``'s operator branch).

    The build is the execution that asked for the session (:func:`open_actor`), so the agent is the
    one ``AgentRunExecution.construct_agent`` builds on the runner path, under the same scopes.
    """

    build = _building.get()
    if build is None:
        raise RuntimeError("an operator chat session is built only by its own turn")
    from agent_runtime.profile_context import persona_profile_context

    execution = build.execution
    # The gateway binds its own (launch) scope around a build; the persona's profile is bound again
    # here so the agent is constructed where the runner path constructs it.
    with persona_profile_context(execution.binding, runtime_root=execution.request.runtime_root):
        agent = execution.construct_agent()
    _install_door(agent, sid)
    build.agent = agent
    return agent


def _install_door(agent: Any, sid: str) -> None:
    original = agent.run_conversation
    agent._operator_gateway_sid = sid

    @functools.wraps(original)
    def run_conversation(*args: Any, **kwargs: Any) -> Any:
        if _inline.get() is agent:  # the execution's own call into the agent
            return original(*args, **kwargs)
        message = args[0] if args else kwargs.get("user_message")
        turn = _take(sid, message)
        token = _inline.set(agent)
        try:
            if turn is None:
                return _gateway_turn(agent, sid, args, kwargs)
            try:
                turn.execution.given_agent = agent
                turn.outcome = turn.execution.run()
                return turn.outcome[0]
            except BaseException as exc:
                turn.error = exc
                raise
            finally:
                turn.done.set()
        finally:
            _inline.reset(token)

    agent.run_conversation = run_conversation


def _gateway_turn(agent: Any, sid: str, args: tuple, kwargs: dict) -> Any:
    handler = _on_gateway_turn
    if handler is None:
        logger.warning("operator_gateway_turn unhandled sid=%s: no operator turn and no handler bound", sid)
        return agent.run_conversation(*args, **kwargs)
    return handler(agent, sid, args, kwargs)


def _take(sid: str, message: Any) -> _Turn | None:
    """The oldest pending operator turn on ``sid`` when the gateway runs an operator submit, else None.

    An operator turn is submitted with no text (:func:`run_turn`): the gateway then writes no user row
    and the door supplies the message. A turn with text is one the gateway started itself.
    """

    if not isinstance(message, str) or message.strip():
        return None
    with _lock:
        queue = _pending.get(sid)
        if not queue:
            return None
        turn = queue.popleft()
        if not queue:
            _pending.pop(sid, None)
        return turn


# ── the actor: a gateway session per chat root ──────────────────────────────


def _gateway_peer():
    global _peer
    with _lock:
        if _peer is not None and _peer.alive:
            return _peer
    from agent_runtime.conversations.in_process_peer import start_in_process_worker

    peer = start_in_process_worker(None, receive=_on_frame, lost=_on_lost)
    with _lock:
        _peer = peer
    return peer


def _on_frame(frame: dict) -> None:
    params = frame.get("params") if isinstance(frame.get("params"), dict) else {}
    if params.get("type") != "error":
        return
    sid = str(params.get("session_id") or "")
    payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
    with _lock:
        queue = _pending.get(sid)
        turn = queue[0] if queue else None
    if turn is not None and not turn.done.is_set() and turn.execution.given_agent is None:
        # The gateway refused the turn before it reached the door (context injection, a build that
        # failed): nothing ran, the caller hears why.
        with _lock:
            if _pending.get(sid) and _pending[sid][0] is turn:
                _pending[sid].popleft()
        from agent_runtime.profile_runner.errors import ProfileRunnerError

        turn.error = ProfileRunnerError(str(payload.get("message") or "the gateway refused the turn"))
        turn.done.set()


def _on_lost() -> None:
    global _peer
    with _lock:
        _peer = None
        turns = [turn for queue in _pending.values() for turn in queue]
        _pending.clear()
    from agent_runtime.profile_runner.errors import ProfileRunnerError

    for turn in turns:
        turn.error = ProfileRunnerError("the gateway engine stopped before the turn ran")
        turn.done.set()


class _SessionActor:
    """Closing the actor closes its gateway session (the registry closes actors it retires)."""

    def __init__(self, sid: str, key: str) -> None:
        self.sid, self.key = sid, key
        self.closed = False


def open_actor(execution: Any) -> Any:
    """Open the chat's gateway session, building its agent through ``execution``; return the agent.

    The session is resumed on the chat's native tip (the session the turn's rows go to), so the
    gateway's submit row and history are the turn's own.
    """

    from agent_runtime.profile_runner.errors import ProfileRunnerError

    request = execution.request
    tip = request.session_id or request.root_chat_session_id
    if not tip:
        raise ProfileRunnerError("an operator turn on the gateway engine needs its chat session")
    with _lock:
        previous = _actors.pop(tip, None)
    if previous is not None:
        # One session per key: the gateway would hand the old one back (a fresh-actor turn, or a
        # rebuild whose old actor the registry retires after its factory returns).
        close_actor(previous)
    build = _Build(execution)
    token = _building.set(build)
    try:
        peer = _gateway_peer()
        result = peer.call("session.resume", {"session_id": tip, "source": OPERATOR_SOURCE,
                                              "eager_build": True, "omit_messages": True}, timeout=600)
    finally:
        _building.reset(token)
    agent = build.agent
    sid = str(result.get("session_id") or "")
    if agent is None or getattr(agent, "_operator_gateway_sid", None) != sid:
        with contextlib.suppress(Exception):
            peer.call("session.close", {"session_id": sid})
        raise ProfileRunnerError("the gateway reused a session this turn did not build")
    actor = _SessionActor(sid, tip)
    with _lock:
        _actors[tip] = actor
    original_close = getattr(agent, "close", None)

    def close() -> None:
        close_actor(actor)
        if callable(original_close):
            original_close()

    agent.close = close
    agent._operator_gateway_actor = actor
    return agent


def close_actor(actor: _SessionActor) -> None:
    if actor.closed:
        return
    actor.closed = True
    with _lock:
        if _actors.get(actor.key) is actor:
            _actors.pop(actor.key)
    peer = _peer
    if peer is None or not peer.alive:
        return
    try:
        peer.call("session.close", {"session_id": actor.sid}, timeout=60)
    except Exception:
        logger.warning("operator gateway session %s did not close", actor.sid, exc_info=True)


# ── the caller ──────────────────────────────────────────────────────────────


def run_turn(execution: Any, agent: Any) -> tuple[Any, Any, dict]:
    """Submit one operator turn to ``agent``'s gateway session and wait for the door's outcome."""

    from agent_runtime.profile_runner.errors import ProfileRunnerError
    from agent_runtime.serde import positive_float

    actor = getattr(agent, "_operator_gateway_actor", None)
    if actor is None or actor.closed:
        raise ProfileRunnerError("the chat's gateway session is gone")
    # No text of its own: the gateway writes no submit row, the door supplies the composed message,
    # and the agent writes the turn's user row as the operator lane always has (one transcript).
    turn = _Turn(execution, "")
    with _lock:
        _pending.setdefault(actor.sid, deque()).append(turn)
    try:
        peer = _gateway_peer()
        reply = peer.call("prompt.submit", {"session_id": actor.sid, "text": "", "queued": True})
    except BaseException:
        _withdraw(actor.sid, turn)
        raise
    if reply.get("status") not in {"streaming", "queued"}:
        _withdraw(actor.sid, turn)
        raise ProfileRunnerError(f"the gateway did not take the turn: {reply.get('status')}")
    wall = positive_float(execution.request.max_wall_seconds)
    if not turn.done.wait(None if wall is None else wall + _WAIT_GRACE_SECONDS):
        _withdraw(actor.sid, turn)
        raise ProfileRunnerError("the gateway never ran the turn")
    if turn.error is not None:
        raise turn.error
    return turn.outcome


def _withdraw(sid: str, turn: _Turn) -> None:
    with _lock:
        queue = _pending.get(sid)
        if queue and turn in queue:
            queue.remove(turn)
            if not queue:
                _pending.pop(sid, None)
