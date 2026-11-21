"""The operator chat's turn, run on the serve's in-process gateway engine (one turn engine).

Row ``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT``; plan
``docs/agent-runtime-harness/planned/operator-chat-on-the-gateway-engine-2026-11-21.md``. An
Intelligence conversation runs ``tui_gateway``'s ``prompt.submit`` on an in-process session
(``conversations/in_process_peer.py``); a Mission Control chat turn now runs the SAME function on a
gateway session of its own with ``source`` :data:`OPERATOR_SOURCE`, resumed on the chat's tip in the
store that holds the chat (the runner's ``session_db``: the persona's profile store, or the head's).

What the operator lane decides about a turn (``profile_runner.execute.AgentRunExecution``: scopes,
budgets, MCP admission, the persona's prompt policy, the tool block, the live-turn registry) is
supplied to the gateway as session policy through fork seams it calls:

* construction — the gateway's ``agent_factory._make_agent`` asks ``worker_app_functions.operator_agent``
  first, which hands an operator session's build to :func:`construct`: the agent the execution builds,
  with the turn door installed;
* the turn — ``worker_app_functions.bind`` pins the session's model (:func:`pin_session`), and the door
  wraps the agent's ``run_conversation``: the gateway calls it from its own turn thread and the door runs
  the execution's phases around the real call there.

The caller (:func:`run_turn`) acquires the chat's actor (the resident registry still decides when one
is built), submits an empty-text turn to the session (the agent writes the turn's user row, one
transcript), and waits for the door to hand back the turn's ``(raw result, agent, timing)`` or its
exception. A turn the gateway starts by itself on an operator session reaches the door with no pending
operator turn: its goal continuation runs nothing (the gateway judged; the operator settle continues,
:class:`EngineJudgedGoal`), and a completion its notification poller claimed is delivered as an operator
turn of the chat, run inline on this session's agent (:func:`inline_turn`).
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
from pathlib import Path
from typing import Any

__layer__ = "lanes"
__all__ = [
    "OPERATOR_SOURCE",
    "close_actor",
    "construct",
    "engine_judged_goals",
    "inline_turn",
    "is_operator",
    "open_actor",
    "pin_session",
    "release_turn",
    "run_turn",
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
    #: Set when the gateway has finished the turn, its goal judge included (its ``session.info``).
    settled: threading.Event = field(default_factory=threading.Event)
    #: Set when the operator lane has settled the turn (:func:`release_turn`): the gateway's goal judge
    #: waits for it, so a judge always reads a settled turn and the chat lists what is checking.
    released: threading.Event = field(default_factory=threading.Event)
    outcome: tuple | None = None
    error: BaseException | None = None
    agent: Any = None
    home: Path | None = None
    #: The chat's goal as the turn found it: the judge ran on this turn when it moved.
    goal_before: tuple | None = None


_building: ContextVar[_Build | None] = ContextVar("operator_gateway_build", default=None)
#: The agent whose door this thread is inside: the execution's own call into it passes straight through.
_inline: ContextVar[Any] = ContextVar("operator_gateway_inline_agent", default=None)

_lock = threading.Lock()
_pending: dict[str, deque[_Turn]] = {}
#: One in-process gateway peer per store home: the operator transcript of a persona with its own
#: profile is that profile's store, the head's otherwise (the runner's ``session_db``).
_peers: dict[Path, Any] = {}
#: The open actor on each chat session key: a key has one gateway session at a time.
_actors: dict[str, _SessionActor] = {}
#: Turns whose door returned, waiting for the gateway to settle them, by gateway session id.
_settling: dict[str, _Turn] = {}
#: The latest turn on each chat root: the goal loop's decision about it is read from here.
_last_turn: dict[str, _Turn] = {}

#: How long a settle waits for the gateway's goal judge (a model call; ~3 minutes held on the QA fixture).
JUDGE_WAIT_SECONDS = 900.0
#: How long the gateway's turn waits for the operator lane to settle the turn before it judges anyway.
RELEASE_WAIT_SECONDS = 120.0
#: Turns waiting for the operator lane's settle, by client message id.
_unreleased: dict[str, _Turn] = {}


def is_operator(session: dict | None) -> bool:
    return (session or {}).get("source") == OPERATOR_SOURCE


# ── the gateway seam ────────────────────────────────────────────────────────


def construct(sid: str) -> Any:
    """Build an operator session's agent (the gateway's ``_make_agent`` asks ``worker_app_functions.
    operator_agent`` first).

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


def pin_session(session: dict | None) -> None:
    """Before an operator session's turn (``worker_app_functions.bind``): its agent runs the model the
    operator lane resolved, so the gateway's per-turn config-model sync must leave it where it is, and the
    gateway's first-contact onboarding note stays out of it."""

    if not is_operator(session):
        return
    # The operator lane builds its own turn context (Eternia's onboarding, not the install's first-message
    # note), and that note's latch would write the store home's config.yaml on a fresh store.
    session["first_contact_owned"] = True
    agent = session.get("agent")
    if agent is not None:
        session["model_override"] = {"model": getattr(agent, "model", None),
                                     "provider": getattr(agent, "provider", None)}


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
            except BaseException as exc:
                turn.error = exc
                with _lock:
                    _settling[sid] = turn
                turn.done.set()
                raise
            _mark_checking(turn)
            with _lock:
                _settling[sid] = turn
            turn.done.set()
            if not turn.released.wait(RELEASE_WAIT_SECONDS):
                logger.warning("operator_gateway_release_late sid=%s: judging before the turn settled", sid)
            return turn.outcome[0]
        finally:
            _inline.reset(token)

    agent.run_conversation = run_conversation


@dataclass
class _Inline:
    """A turn the gateway started on an operator chat, run as that chat's operator turn on this thread."""

    agent: Any
    key: str
    outcome: tuple | None = None


_inline_turn: ContextVar[_Inline | None] = ContextVar("operator_gateway_inline_turn", default=None)


def _gateway_turn(agent: Any, sid: str, args: tuple, kwargs: dict) -> Any:
    """A turn the gateway started by itself on an operator chat.

    * Its goal continuation: the chat's goal loop is the gateway's (its judge ran on the turn before),
      and the operator lane turns the decision into its next turn, a queued send with the turn's own
      arguments (``work_store.goal_turns``). This turn runs nothing: an interrupted, empty turn, which
      the gateway neither judges nor records.
    * A completion the gateway's notification poller claimed for the chat (the one completion drain):
      delivered as an operator turn of the chat, through the mission-chat door like any delivery
      (``dispatch_delivery.forge``), and run right here, on this session's agent (:func:`inline_turn`).
    """

    text = args[0] if args else kwargs.get("user_message")
    actor = getattr(agent, "_operator_gateway_actor", None)
    if actor is None or not isinstance(text, str) or _is_goal_continuation(actor, agent, text):
        logger.info("operator_gateway_followup sid=%s: continued by the operator lane", sid)
        return _empty_turn(kwargs)
    return _deliver(agent, actor, text, kwargs)


def _empty_turn(kwargs: dict) -> dict:
    history = kwargs.get("conversation_history")
    return {"final_response": "", "interrupted": True, "completed": False,
            "messages": list(history) if isinstance(history, list) else []}


def _is_goal_continuation(actor: Any, agent: Any, text: str) -> bool:
    from hermes_cli.goals import GoalManager

    from agent_runtime.profile_context import process_home_scope

    with process_home_scope(actor.home):
        prompt = GoalManager(str(getattr(agent, "session_id", "") or actor.key)).next_continuation_prompt()
    return bool(prompt) and prompt.strip() == text.strip()


def _deliver(agent: Any, actor: Any, text: str, kwargs: dict) -> Any:
    import uuid

    from agent_runtime.dispatch_delivery.forge import _sender_persona, forge_delivery_turn

    owner = _sender_persona(actor.root) if actor.root else None
    if owner is None:
        logger.warning("operator_gateway_notice_unowned root=%s: no persona instance owns the chat", actor.root)
        return _empty_turn(kwargs)
    inline = _Inline(agent, actor.key)
    token = _inline_turn.set(inline)
    try:
        ok, _payload = forge_delivery_turn(root_session_id=actor.root, persona_id=owner[0],
                                           persona_instance_id=owner[1], message=text,
                                           client_message_id=f"notice-{uuid.uuid4().hex[:16]}")
    finally:
        _inline_turn.reset(token)
    if inline.outcome is None:
        logger.warning("operator_gateway_notice_not_run root=%s ok=%s", actor.root, ok)
        return _empty_turn(kwargs)
    return inline.outcome[0]


def inline_turn(request: Any) -> _Inline | None:
    """The gateway turn this thread is running for ``request``'s chat, else None: the runner then runs
    the request's execution on that turn's agent instead of submitting it."""

    inline = _inline_turn.get()
    if inline is None or inline.outcome is not None:
        return None
    if not request.session_id or request.session_id not in {inline.key, getattr(inline.agent, "session_id", None)}:
        return None
    return inline


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


def _gateway_call(home: Path, method: str, params: dict, *, timeout: float = 60) -> dict:
    """One gateway request; a refusal is the runner's typed error, naming what the gateway said."""

    from agent_runtime.conversations.model import ConversationError
    from agent_runtime.profile_runner.errors import ProfileRunnerError

    try:
        return _gateway_peer(home).call(method, params, timeout=timeout)
    except ConversationError as exc:
        detail = f"{method} refused: {exc} native_code={getattr(exc, 'native_code', None)}"
        logger.warning("operator_gateway_refused %s", detail)
        raise ProfileRunnerError(detail) from exc


def _gateway_peer(home: Path):
    with _lock:
        peer = _peers.get(home)
        if peer is not None and peer.alive:
            return peer
    from agent_runtime.conversations.in_process_peer import start_in_process_worker

    peer = start_in_process_worker(home, receive=_on_frame, lost=functools.partial(_on_lost, home))
    with _lock:
        _peers[home] = peer
    return peer


def _store_home(execution: Any) -> Path:
    """The profile home whose store holds the chat (the runner's ``session_db``), else the head's."""

    db = getattr(execution.runner, "_session_db", None)
    path = getattr(db, "db_path", None)
    if path:
        return Path(path).parent.resolve()
    from agent_runtime.profile_home import get_hermes_head_home

    return Path(get_hermes_head_home()).resolve()


def _on_frame(frame: dict) -> None:
    params = frame.get("params") if isinstance(frame.get("params"), dict) else {}
    kind = params.get("type")
    sid = str(params.get("session_id") or "")
    if kind == "session.info":
        # The gateway's end-of-turn info: emitted after the turn's goal judge, before any follow-up.
        with _lock:
            settled = _settling.pop(sid, None)
        if settled is not None:
            settled.settled.set()
        return
    if kind != "error":
        return
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
        turn.settled.set()
        turn.done.set()


def _on_lost(home: Path) -> None:
    with _lock:
        _peers.pop(home, None)
        turns = [turn for queue in _pending.values() for turn in queue]
        _pending.clear()
    from agent_runtime.profile_runner.errors import ProfileRunnerError

    for turn in turns:
        turn.error = ProfileRunnerError("the gateway engine stopped before the turn ran")
        turn.settled.set()
        turn.done.set()


class _SessionActor:
    """Closing the actor closes its gateway session (the registry closes actors it retires)."""

    def __init__(self, sid: str, key: str, home: Path, root: str | None) -> None:
        self.sid, self.key, self.home, self.root = sid, key, home, root
        self.closed = False


def open_actor(execution: Any) -> Any:
    """Open the chat's gateway session, building its agent through ``execution``; return the agent.

    The session is resumed on the chat's native tip (the session the turn's rows go to), in the store
    that holds it, so the gateway's session key, history and goal are the chat's own.
    """

    from agent_runtime.profile_runner.errors import ProfileRunnerError

    request = execution.request
    tip = request.session_id or request.root_chat_session_id
    if not tip:
        raise ProfileRunnerError("only a chat's turn runs on a gateway session")
    home = _store_home(execution)
    _ensure_session_row(execution, home, tip)
    with _lock:
        previous = _actors.pop(tip, None)
    if previous is not None:
        # One session per key: the gateway would hand the old one back (a fresh-actor turn, or a
        # rebuild whose old actor the registry retires after its factory returns).
        close_actor(previous)
    build = _Build(execution)
    token = _building.set(build)
    try:
        result = _gateway_call(home, "session.resume", {"session_id": tip, "source": OPERATOR_SOURCE,
                                                "eager_build": True, "omit_messages": True}, timeout=600)
    finally:
        _building.reset(token)
    agent = build.agent
    sid = str(result.get("session_id") or "")
    if agent is None or getattr(agent, "_operator_gateway_sid", None) != sid:
        with contextlib.suppress(Exception):
            _gateway_call(home, "session.close", {"session_id": sid})
        raise ProfileRunnerError("the gateway reused a session this turn did not build")
    actor = _SessionActor(sid, tip, home, request.root_chat_session_id)
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


def _ensure_session_row(execution: Any, home: Path, tip: str) -> None:
    """The tip's row in its store: the gateway resumes only a stored session. An operator chat's root is
    minted with its row (``persona_chat_continuity.mint_receipts``); a run on a session nothing minted
    gets the row the agent would write at its first message."""

    from agent_runtime.persona_runtime import PERSONA_CHAT_SCRATCH_SOURCE

    db = getattr(execution.runner, "_session_db", None)
    owned = None
    if db is None:
        from hermes_state_registry import acquire

        db = owned = acquire(home / "state.db")
    try:
        if not db.get_session(tip):
            db.create_session(tip, source=PERSONA_CHAT_SCRATCH_SOURCE)
    finally:
        if owned is not None:
            from hermes_state_registry import release_or_close

            release_or_close(owned)


def close_actor(actor: _SessionActor) -> None:
    if actor.closed:
        return
    actor.closed = True
    with _lock:
        if _actors.get(actor.key) is actor:
            _actors.pop(actor.key)
    with _lock:
        peer = _peers.get(actor.home)
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
    turn = _Turn(execution, "", agent=agent, home=actor.home)
    turn.goal_before = _goal_mark(actor.home, getattr(agent, "session_id", None))
    root = execution.request.root_chat_session_id
    cmid = execution.request.client_message_id
    with _lock:
        _pending.setdefault(actor.sid, deque()).append(turn)
        if root:
            _last_turn[root] = turn
        if cmid:
            _unreleased[str(cmid)] = turn
        else:
            turn.released.set()
    try:
        reply = _gateway_call(actor.home, "prompt.submit", {"session_id": actor.sid, "text": "", "queued": True})
    except BaseException:
        _withdraw(actor.sid, turn)
        raise
    if reply.get("status") not in {"streaming", "queued"}:
        _withdraw(actor.sid, turn)
        raise ProfileRunnerError(f"the gateway did not take the turn: {reply.get('status')}")
    wall = positive_float(execution.request.max_wall_seconds)
    if not turn.done.wait(None if wall is None else wall + _WAIT_GRACE_SECONDS):
        _withdraw(actor.sid, turn)
        turn.settled.set()
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


# ── the goal loop: the gateway judges, the operator lane continues ──────────


def _goal_mark(home: Path | None, key: str | None) -> tuple | None:
    """``(turns_used, last_turn_at, status, last_verdict, last_reason)`` of the chat goal on ``key``, read
    in the chat's store (``home``), where the gateway's judge writes it."""

    if not key:
        return None
    from hermes_cli.goals import load_goal

    from agent_runtime.profile_context import process_home_scope

    with contextlib.nullcontext() if home is None else process_home_scope(home):
        state = load_goal(key)
    if state is None:
        return None
    return (state.turns_used, state.last_turn_at, state.status, state.last_verdict, state.last_reason)


def _not_judged(status: Any) -> dict:
    return {"status": status, "should_continue": False, "continuation_prompt": None, "verdict": "waiting",
            "reason": "the turn engine did not judge this turn", "message": ""}


class EngineJudgedGoal:
    """A chat's goal whose judge is the turn engine's goal loop (one loop for every chat).

    Everything is the chat's goal (``chat_goal.manager``) except :meth:`evaluate_after_turn`, which
    asks nobody: it waits for the gateway to settle the chat's latest turn and answers the decision its
    judge left on the goal (``GoalState.last_verdict`` / ``status``), or a ``waiting`` decision when the
    judge did not run on that turn (a failed or stopped turn, no active goal).
    """

    def __init__(self, root: str) -> None:
        from agent_runtime import chat_goal

        self._root = root
        self._goal = chat_goal.manager(root)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._goal, name)

    def evaluate_after_turn(self, last_response: str = "", **_ignored: Any) -> dict:
        with _lock:
            turn = _last_turn.get(self._root)
        status = getattr(getattr(self._goal, "state", None), "status", None)
        if turn is None:
            return _not_judged(status)
        turn.settled.wait(JUDGE_WAIT_SECONDS)
        after = _goal_mark(turn.home, getattr(turn.agent, "session_id", None))
        if after is None or turn.goal_before is None or after[:2] == turn.goal_before[:2]:
            return _not_judged(after[2] if after else status)
        _turns, _at, status, verdict, reason = after
        return {"status": status, "should_continue": status == "active" and verdict == "continue",
                "continuation_prompt": None, "verdict": verdict, "reason": reason, "message": reason or ""}


def engine_judged_goals(root: str) -> EngineJudgedGoal:
    """The goal source the operator's goal loop reads (``PersonaTurnExecutor``'s default)."""

    return EngineJudgedGoal(root)


def release_turn(client_message_id: str | None) -> None:
    """The operator lane settled the turn ``client_message_id``: the gateway may go on and judge it."""

    if not client_message_id:
        return
    with _lock:
        turn = _unreleased.pop(str(client_message_id), None)
    if turn is not None:
        turn.released.set()


def _mark_checking(turn: _Turn) -> None:
    """A Work run's pass that just ended is listed as checking before the gateway's judge is asked
    (``goal_turns._checked`` binds the same mark when the settle reads the decision)."""

    import time

    from agent_runtime import chat_goal

    root = turn.execution.request.root_chat_session_id
    bound = chat_goal.binding(root) if root else None
    if bound is not None and not bound.stopping:
        chat_goal.bind(bound.advanced(checking_since=time.time()))
