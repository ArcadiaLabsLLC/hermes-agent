"""A chat's standing goal, continued turn by turn: the one loop, for any chat.

Row ``RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT``. Owner ruling
2026-11-21: "yea that logic should be decoupled from tasks so it could be a slash command". A chat's goal
is upstream's ``GoalManager`` on the chat root (``chat_goal``), set through ``runtime.chat.goal.*`` by the
operator's own composer, or by a Work task's Until done. Its judge is the turn engine's goal loop
(``operator_gateway_turn.EngineJudgedGoal``): one judge per turn. This module turns that decision into the
chat's next step, the same for every caller:

* continue: the continuation prompt is sent as the chat's next queued send, unless another send already
  waits on the root, which wins the slot (its own settle is judged in turn);
* park: the judge said ``wait`` (a pid, a process session, a deadline), so the chat records a
  :class:`chat_goal.ChatGoalPark` and :func:`wake` continues it when the barrier lifts;
* settle: anything else; the goal is done, blocked, paused or out of turns, and nothing is sent.

WHO sends a continuation is the caller's: a chat goal no Work run owns queues it from the settled turn's
own arguments (:func:`after_turn`, origin ``chat_goal``); a Work run (``work_store.goal_turns``) sends it
as the run's next pass and keeps only its bookkeeping (rows, report, stop). Never two loops.
Receipts: ``work.chat_goal_continue | chat_goal_hold | chat_goal_settle | chat_goal_wake``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from . import chat_goal
from . import chat_root_send_queue as send_queue
from .chat_turn_settles import outcome_from_payload
from .work_store import receipts

__layer__ = "lanes"
__all__ = ["CHAT_GOAL_ORIGIN", "Step", "after_turn", "pass_max_seconds", "step", "wake"]

#: The origin key a chat goal's own continuation carries (``user_initiated=False`` when it settles).
CHAT_GOAL_ORIGIN = "chat_goal"
#: Arguments of the settled turn a chat goal's continuation does NOT inherit: each names that one send.
_NOT_CARRIED = frozenset({send_queue.ORIGIN_ARG, "idempotency_key", "retry_of", "images", "clarify_token",
                          "title", "new_session"})

#: Sends ``prompt`` as the chat's next turn; answers the send's client message id.
Send = Callable[[str], str]


class Step(StrEnum):
    CONTINUED = "continued"
    HELD = "held"
    PARKED = "parked"
    SETTLED = "settled"


def pass_max_seconds() -> float:
    """The wall budget of ONE pass of a keep-going-until-done loop: the detached-dispatch budget.

    Owner ruling 2026-11-12 (``RT-UNTIL-DONE-PASS-FOUR-MINUTE-CLOCK``): 30 minutes per pass, at most
    upstream's 20 passes (``hermes_cli.goals.DEFAULT_MAX_TURNS``). A pass is unattended work, so it runs
    on ``agent_runtime.mission_chat.dispatch_max_seconds`` (default 1800 s), not on the 240 s an
    unattended conversational turn gets (a pass was checkpointed at about 180 s).
    """

    from .config import mission_chat_dispatch_max_seconds

    return float(mission_chat_dispatch_max_seconds())


def _parked(goal: Any) -> bool:
    """The goal is active and carries a barrier (upstream ``GoalState.waiting_*``), lifted or not."""

    state = getattr(goal, "state", None)
    if state is None or getattr(state, "status", None) != "active":
        return False
    return (getattr(state, "waiting_on_pid", None) is not None
            or getattr(state, "waiting_on_session", None) is not None or bool(getattr(state, "waiting_until", 0)))


def step(root: str, after_cmid: str, goal: Any, decision: Mapping[str, Any], *, send: Send,
         template: Mapping[str, Any] | None = None) -> Step:
    """The chat's next step after the judge's ``decision`` on the turn ``after_cmid``.

    ``template`` is what a park keeps for :func:`wake` (the settled turn's arguments); a caller whose
    continuation is forged from its own record passes none.
    """

    if decision.get("should_continue"):
        waiting = [e for e in send_queue.entries(root) if e.client_message_id != after_cmid]
        # MUTATION: drop this hold and test_chat_goal_rpc's test_operator_send_wins_slot reddens.
        if waiting:
            return Step.HELD
        send(str(decision.get("continuation_prompt") or goal.next_continuation_prompt()))
        chat_goal.unpark(root)
        return Step.CONTINUED
    if _parked(goal):
        chat_goal.park(chat_goal.ChatGoalPark(root, dict(template or {}), after_cmid))
        return Step.PARKED
    chat_goal.unpark(root)
    return Step.SETTLED


def _cmid(after_cmid: str) -> str:
    """Deterministic per predecessor, so a replayed hook converges on the one queued continuation."""

    return "goal-" + hashlib.sha256(after_cmid.encode("utf-8")).hexdigest()[:16]


def _template(entry: send_queue.QueuedSend) -> dict[str, Any]:
    """The settled turn's arguments a chat goal's continuation inherits, its origin marked ``chat_goal``.

    A continuation is the runtime's own pass, not a send somebody is waiting on: when the settled turn
    stated no budget (an attended send runs with no wall clock) the pass gets :func:`pass_max_seconds`.
    """

    origin = entry.args.get(send_queue.ORIGIN_ARG)
    base = {key: value for key, value in entry.args.items() if key not in _NOT_CARRIED}
    # MUTATION: drop this line and test_goal_direct_turns' chat-goal continuation row reddens.
    base["max_seconds"] = base.get("max_seconds") or pass_max_seconds()
    carried = dict(origin) if isinstance(origin, dict) else {"owner": None, "gateway": False}
    return {**base, send_queue.ORIGIN_ARG: {**carried, CHAT_GOAL_ORIGIN: True}}


def _queue(root: str, after_cmid: str, template: Mapping[str, Any], *, enqueue: Callable[..., Any],
           wake_runner: Callable[[], None]) -> Send:
    def send(prompt: str) -> str:
        cmid = _cmid(after_cmid)
        enqueue(root, cmid, {**template, "message": prompt, "client_message_id": cmid})
        wake_runner()
        return cmid

    return send


def after_turn(entry: send_queue.QueuedSend, payload: dict | None, *, goals: Callable[[str], Any],
               enqueue: Callable[..., Any], wake_runner: Callable[[], None]) -> bool:
    """A terminal turn on a root with an active goal and no Work run bound: read the judge, take the step.

    True when the root's goal was evaluated. A failed turn is not judged (there is no reply to judge).
    """

    root = entry.root_session_id
    origin = entry.args.get(send_queue.ORIGIN_ARG)
    if chat_goal.binding(root) is not None or (isinstance(origin, dict) and origin.get("work")):
        return False
    goal = goals(root)
    if not goal.is_active() or outcome_from_payload(payload).refusal_class:
        return False
    own = isinstance(origin, dict) and origin.get(CHAT_GOAL_ORIGIN) is True
    decision = goal.evaluate_after_turn(str((payload or {}).get("reply") or ""), user_initiated=not own)
    template = _template(entry)
    sent: list[str] = []
    send = _queue(root, entry.client_message_id, template, enqueue=enqueue, wake_runner=wake_runner)
    moved = step(root, entry.client_message_id, goal, decision, template=template,
                 send=lambda prompt: sent.append(send(prompt)) or sent[-1])
    if moved is Step.CONTINUED:
        receipts.emit("work.chat_goal_continue", root=root, cmid=sent[-1])
    elif moved is Step.HELD:
        receipts.emit("work.chat_goal_hold", root=root)
    else:
        receipts.emit("work.chat_goal_settle", root=root, verdict=str(decision.get("verdict")))
    return True


def _lifted_prompt(goal: Any) -> str | None:
    """The continuation prompt of a parked goal whose barrier has lifted, else None (still held, or gone)."""

    if not _parked(goal) or goal.is_waiting():
        return None
    return str(goal.next_continuation_prompt() or "") or None


def wake(*, goals: Callable[[str], Any], enqueue: Callable[..., Any], wake_runner: Callable[[], None],
         sender_of: Callable[[str], Send | None]) -> int:
    """``RT-GOAL-WAIT-WAKER``: continue every parked chat goal whose judge ``wait`` barrier has lifted.

    A parked goal waits while its root has a send queued or running (that send's settle is judged on its
    own). ``sender_of(root)`` is the owner's sender (a Work run's next pass), ``None`` when the root has no
    owner (the park's own template is queued), or raises ``LookupError`` when the owner will not go on (a
    run told to stop), which drops the park. ``is_waiting()`` is upstream's own test (pid alive, session
    still running, deadline ahead, the age cap) and clears a lifted barrier. Answers how many continued.
    """

    woken = 0
    for held in chat_goal.parked():
        root = held.root_session_id
        goal = goals(root)
        if not goal.is_active():
            chat_goal.unpark(root)
            continue
        if send_queue.entries(root):
            continue
        prompt = _lifted_prompt(goal)
        if prompt is None:
            continue
        try:
            send = sender_of(root) or _queue(root, held.after_cmid, held.turn_args, enqueue=enqueue,
                                              wake_runner=wake_runner)
        except LookupError:
            chat_goal.unpark(root)
            continue
        cmid = send(prompt)
        chat_goal.unpark(root)
        receipts.emit("work.chat_goal_wake", root=root, cmid=cmid)
        woken += 1
    return woken
