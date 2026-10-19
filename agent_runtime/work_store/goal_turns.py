"""An ``UNTIL_DONE`` Work run: a goal on the instance's chat root, continued turn by turn (plan §2.2, §5; B3).

``PersonaTurnExecutor.start`` with ``goal_mode=UNTIL_DONE`` calls :func:`arm_run` before it queues the
first turn: the root's goal is set over upstream's ``GoalManager`` (``chat_goal.arm``) and a
``chat_goal.GoalBinding`` records that this run owns it. After EVERY terminal queued turn on a bound
root — the run's own and an operator's — the runner's settle reaches :func:`after_turn`, which runs
upstream's gates and judge (``evaluate_after_turn``) in the run's workdir and then either:

* continues — forges ``next_continuation_prompt`` as the run's next queued send on the root (never a
  direct turn: the queue's idle-root gate is the only door, RT-D3 by construction);
* holds — an operator send is already waiting on the root, so it wins the slot; its own settle
  evaluates again and continues then;
* ends — returns the run's ``RowEnding`` (the table :data:`DECISION_ENDINGS`), pauses a goal still
  active, and unbinds the root.

A reply's own ``work_report`` that says ``blocked`` or ``stopped`` ends the run at once; a ``done``
report is believed only when the judge agrees (a failing gate is evidence it is not done).

A turn that never sat in the queue — a DIRECT operator send on an idle root — reaches the same hook
from the serve's direct-turn settle (``settle_push.SettlePush._record_turn_settle``) as
:func:`direct_entry`: an operator turn with no queue entry. A queued turn reaches it only from the
runner's ``on_settle``, so no turn is evaluated twice. A root with an active goal and NO run bound
(``runtime.chat.goal.set``) goes through :func:`after_chat_goal_turn`: the judge, then a continuation
queued from the settled turn's own arguments (origin ``chat_goal``), never a Work report.
A judge ``wait`` parks the run on upstream's barrier (a pid, a process session, a deadline). Upstream's
CLI polls that barrier when idle; the serve's poll is :func:`wake_parked`, run on the Work engine's
tick, which continues a parked run whose barrier lifted and whose root has nothing queued — and a parked
chat goal no run owns, forged from the settled turn's arguments its ``wait`` recorded.
A run whose assignment lends skills carries them in its origin (:data:`SKILLS_ORIGIN`); every continuation
re-queues them for its own turn (``queued_skills`` is one turn deep, p10-work S1).
Receipts: ``work.goal_arm | goal_continue | goal_hold | goal_wake | goal_end | chat_goal_continue |
chat_goal_hold | chat_goal_settle | chat_goal_wake``.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .. import chat_goal
from .. import chat_root_send_queue as send_queue
from ..chat_turn_settles import outcome_from_payload
from . import receipts
from .executor import Assignment, RowEnding, RunStatus, Verdict
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = [
    "CHAT_GOAL_ORIGIN", "DECISION_ENDINGS", "SKILLS_ORIGIN", "after_chat_goal_turn", "after_turn", "arm_run", "direct_entry",
    "first_cmid", "run_status", "stop_run", "wake_parked",
]

#: The origin key a chat goal's own continuation carries (``user_initiated=False`` when it settles).
CHAT_GOAL_ORIGIN = "chat_goal"
#: The origin key a Work run's lent skills ride in (``PersonaTurnExecutor.start_from`` writes it).
SKILLS_ORIGIN = "skills"
#: Arguments of the settled turn a chat goal's continuation does NOT inherit: each names that one send.
_NOT_CARRIED = frozenset({send_queue.ORIGIN_ARG, "idempotency_key", "retry_of", "images", "clarify_token",
                          "title", "new_session"})

_RECOMMEND_BLOCKED = "re-scope the row, or resume the goal with runtime.chat.goal.resume"


def first_cmid(request_id: str) -> str:
    return f"work-{request_id}"


def _blocked(decision: Mapping[str, Any], report: RowEnding | None) -> RowEnding:
    return RowEnding(Verdict.BLOCKED, question=f"the goal judge ruled it blocked: {decision.get('reason') or '-'}",
                     recommend=_RECOMMEND_BLOCKED)


def _done(decision: Mapping[str, Any], report: RowEnding | None) -> RowEnding:
    if report is not None and report.verdict is Verdict.DONE:
        return report
    return RowEnding(Verdict.DONE, result=str(decision.get("reason") or "goal achieved"))


def _stopped(decision: Mapping[str, Any], report: RowEnding | None) -> RowEnding:
    why = decision.get("message") or decision.get("reason") or decision.get("status")
    return RowEnding(Verdict.STOPPED, reason=f"goal {decision.get('verdict') or 'ended'}: {why}")


#: A judge decision that does NOT continue → the run's ending; ``None`` keeps the run parked: the judge's
#: ``wait`` sets a barrier, and ``waiting`` is a turn that settled while one still held. Either way the run
#: resumes when :func:`wake_parked` finds the barrier lifted (or another turn settles on the root).
DECISION_ENDINGS: dict[str, Callable[[Mapping[str, Any], RowEnding | None], RowEnding | None]] = {
    "done": _done,
    "blocked": _blocked,
    "wait": lambda decision, report: None,
    "waiting": lambda decision, report: None,
}


def arm_run(root: str, a: Assignment, args: Mapping[str, Any], *, cwd: str | None,
            goals: Callable[[str], Any]) -> None:
    """Set the root's goal for ``a`` and bind the root to its run; a replay of the same run is a no-op."""

    bound = chat_goal.binding(root)
    if bound is not None and bound.request_id == a.request_id:
        return
    if bound is not None or goals(root).is_active():
        raise WorkRefused(Reason.EXECUTOR_BUSY, f"chat root {root} already works a goal")
    gates = a.brief.tests if a.goal_gates else ()
    chat_goal.arm(root, a.brief.objective or a.brief.title, acceptance=a.brief.acceptance, gates=gates, goals=goals)
    rows = tuple((ref.slot, ref.note, ref.id) for ref in a.rows)
    chat_goal.bind(chat_goal.GoalBinding(root, a.request_id, rows, dict(args), first_cmid(a.request_id), cwd=cwd))
    receipts.emit("work.goal_arm", root=root, request_id=a.request_id, gates=len(gates))


def run_status(bound: chat_goal.GoalBinding) -> RunStatus:
    entry = send_queue.find(bound.root_session_id, bound.cmid)
    return RunStatus.RUNNING if entry is not None and entry.state == send_queue.STATE_RUNNING else RunStatus.QUEUED


def stop_run(bound: chat_goal.GoalBinding, *, goals: Callable[[str], Any]) -> bool:
    """A queued or held run stops now (True); a running turn ends the run when it settles (False)."""

    root = bound.root_session_id
    entry = send_queue.find(root, bound.cmid)
    if entry is not None and entry.state == send_queue.STATE_RUNNING:
        chat_goal.bind(bound.advanced(stopping=True))
        return False
    if entry is not None:
        send_queue.remove(root, bound.cmid)
    _end_goal(bound, goals, "work run stopped")
    return True


@contextlib.contextmanager
def _gate_cwd(cwd: str | None) -> Iterator[None]:
    """Gates run where the persona works: the session cwd upstream's ``_gate_workspace`` reads."""

    if not cwd:
        yield
        return
    from agent.runtime_cwd import reset_session_cwd, set_session_cwd

    token = set_session_cwd(cwd)
    try:
        yield
    finally:
        reset_session_cwd(token)


def _end_goal(bound: chat_goal.GoalBinding, goals: Callable[[str], Any], why: str) -> None:
    goal = goals(bound.root_session_id)
    if goal.is_active():
        goal.pause(why)
    chat_goal.unbind(bound.root_session_id)


def _forge(bound: chat_goal.GoalBinding, entry: send_queue.QueuedSend, prompt: str, *,
           enqueue: Callable[..., Any], wake: Callable[[], None]) -> None:
    """Queue the continuation behind whatever is waiting — or hold when an operator send waits."""

    root = bound.root_session_id
    waiting = [e for e in send_queue.entries(root) if e.client_message_id != entry.client_message_id]
    if waiting:
        chat_goal.bind(bound.advanced(held=True, turns=bound.turns + 1))
        receipts.emit("work.goal_hold", root=root, request_id=bound.request_id, waiting=len(waiting))
        return
    cmid = f"{first_cmid(bound.request_id)}-g{bound.turns + 1}"
    chat_goal.bind(bound.advanced(cmid=cmid, turns=bound.turns + 1, held=False))
    _requeue_skills(bound)
    enqueue(root, cmid, {**bound.turn_args, "message": prompt, "client_message_id": cmid})
    wake()
    receipts.emit("work.goal_continue", root=root, request_id=bound.request_id, cmid=cmid, turn=bound.turns + 1)


def _requeue_skills(bound: chat_goal.GoalBinding) -> None:
    """The run's lent skills, queued again for the continuation's turn (they were consumed by the last one)."""

    origin = bound.turn_args.get(send_queue.ORIGIN_ARG)
    skills = list(origin.get(SKILLS_ORIGIN) or ()) if isinstance(origin, dict) else []
    if skills:
        from ..queued_skills import queue_skills_for_next_turn

        queue_skills_for_next_turn(persona_id=str(bound.turn_args.get("persona_id") or ""),
                                   session_id=bound.root_session_id, skills=skills,
                                   persona_instance_id=bound.turn_args.get("persona_instance_id"))


def _ending_now(bound: chat_goal.GoalBinding, payload: dict | None, report: RowEnding | None) -> RowEnding | None:
    """The endings no judge is asked about: a stop, a failed turn, a report that says blocked/stopped."""

    refusal = outcome_from_payload(payload).refusal_class
    if bound.stopping:
        return RowEnding(Verdict.STOPPED, reason="operator stop")
    if refusal:
        return RowEnding(Verdict.FAILED, reason=f"the turn ended {refusal}")
    if report is not None and report.verdict in (Verdict.BLOCKED, Verdict.STOPPED):
        return report
    return None


def after_turn(bound: chat_goal.GoalBinding, entry: send_queue.QueuedSend, payload: dict | None, *,
               goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None],
               parse_report: Callable[[str], RowEnding | None]) -> RowEnding | None:
    """One terminal turn on a bound root: the run's ending, or None when it goes on."""

    reply = str((payload or {}).get("reply") or "")
    report = parse_report(reply)
    ending = _ending_now(bound, payload, report)
    if ending is None:
        origin = entry.args.get(send_queue.ORIGIN_ARG)
        own = isinstance(origin, dict) and origin.get("work") == bound.request_id
        goal = goals(bound.root_session_id)
        with _gate_cwd(bound.cwd):
            decision = goal.evaluate_after_turn(reply, user_initiated=not own)
        if decision.get("should_continue"):
            _forge(bound, entry, str(decision.get("continuation_prompt") or goal.next_continuation_prompt()),
                   enqueue=enqueue, wake=wake)
            return None
        ending = DECISION_ENDINGS.get(str(decision.get("verdict")), _stopped)(decision, report)
        if ending is None:
            chat_goal.bind(bound.advanced(held=True))
            return None
    _end_goal(bound, goals, f"work run ended {ending.verdict.value}")
    receipts.emit("work.goal_end", root=bound.root_session_id, request_id=bound.request_id,
                  verdict=ending.verdict.value, turns=bound.turns + 1)
    return ending


def direct_entry(root: str, cmid: str, args: Mapping[str, Any] | None = None) -> send_queue.QueuedSend:
    """A turn that ran OUTSIDE the queue (a direct send), shaped as the entry the hook reads: no origin."""

    return send_queue.QueuedSend(root_session_id=root, client_message_id=cmid, seq=0, queued_at="",
                                 args=dict(args or {}))


def _chat_goal_cmid(after_cmid: str) -> str:
    """Deterministic per predecessor, so a replayed hook converges on the one queued continuation."""

    return "goal-" + hashlib.sha256(after_cmid.encode("utf-8")).hexdigest()[:16]


def _chat_goal_template(entry: send_queue.QueuedSend) -> dict[str, Any]:
    """The settled turn's arguments a chat goal's continuation inherits, its origin marked ``chat_goal``."""

    origin = entry.args.get(send_queue.ORIGIN_ARG)
    base = {key: value for key, value in entry.args.items() if key not in _NOT_CARRIED}
    carried = dict(origin) if isinstance(origin, dict) else {"owner": None, "gateway": False}
    return {**base, send_queue.ORIGIN_ARG: {**carried, CHAT_GOAL_ORIGIN: True}}


def _queue_chat_goal(root: str, after_cmid: str, template: Mapping[str, Any], prompt: str, *,
                     enqueue: Callable[..., Any], wake: Callable[[], None]) -> str:
    cmid = _chat_goal_cmid(after_cmid)
    enqueue(root, cmid, {**template, "message": prompt, "client_message_id": cmid})
    chat_goal.unpark(root)
    wake()
    return cmid


def after_chat_goal_turn(entry: send_queue.QueuedSend, payload: dict | None, *, goals: Callable[[str], Any],
                         enqueue: Callable[..., Any], wake: Callable[[], None]) -> bool:
    """A terminal turn on a root with an active goal and no Work run bound: judge it, maybe go on.

    True when the root's goal was evaluated. A failed turn is not judged (there is no reply to judge).
    A judge ``wait`` parks the goal with this turn's arguments (:class:`chat_goal.ChatGoalPark`) for
    :func:`wake_parked`; any other decision clears the park.
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
    if not decision.get("should_continue"):
        if _parked(goal):
            chat_goal.park(chat_goal.ChatGoalPark(root, _chat_goal_template(entry), entry.client_message_id))
        else:
            chat_goal.unpark(root)
        receipts.emit("work.chat_goal_settle", root=root, verdict=str(decision.get("verdict")))
        return True
    waiting = [e for e in send_queue.entries(root) if e.client_message_id != entry.client_message_id]
    if waiting:
        receipts.emit("work.chat_goal_hold", root=root, waiting=len(waiting))
        return True
    prompt = str(decision.get("continuation_prompt") or goal.next_continuation_prompt())
    cmid = _queue_chat_goal(root, entry.client_message_id, _chat_goal_template(entry), prompt,
                            enqueue=enqueue, wake=wake)
    receipts.emit("work.chat_goal_continue", root=root, cmid=cmid)
    return True


def _parked(goal: Any) -> bool:
    """The goal is active and carries a barrier (upstream ``GoalState.waiting_*``), lifted or not."""

    state = getattr(goal, "state", None)
    if state is None or getattr(state, "status", None) != "active":
        return False
    return (getattr(state, "waiting_on_pid", None) is not None
            or getattr(state, "waiting_on_session", None) is not None or bool(getattr(state, "waiting_until", 0)))


def _lifted_prompt(goal: Any) -> str | None:
    """The continuation prompt of a parked goal whose barrier has lifted, else None (still held, or gone)."""

    if not _parked(goal) or goal.is_waiting():
        return None
    return str(goal.next_continuation_prompt() or "") or None


def _wake_bound(*, goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None]) -> int:
    woken = 0
    for bound in chat_goal.bindings():
        root = bound.root_session_id
        if not bound.held or bound.stopping or send_queue.entries(root):
            continue
        prompt = _lifted_prompt(goals(root))
        if prompt is None:
            continue
        _forge(bound, direct_entry(root, bound.cmid), prompt, enqueue=enqueue, wake=wake)
        receipts.emit("work.goal_wake", root=root, request_id=bound.request_id)
        woken += 1
    return woken


def _wake_chat_goals(*, goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None]) -> int:
    """``RT-CHAT-GOAL-WAIT-NO-WAKER``: the same poll for a parked chat goal no Work run owns."""

    woken = 0
    for held in chat_goal.parked():
        root = held.root_session_id
        goal = goals(root)
        if chat_goal.binding(root) is not None or not goal.is_active():
            chat_goal.unpark(root)
            continue
        if send_queue.entries(root):
            continue
        prompt = _lifted_prompt(goal)
        if prompt is None:
            continue
        cmid = _queue_chat_goal(root, held.after_cmid, held.turn_args, prompt, enqueue=enqueue, wake=wake)
        receipts.emit("work.chat_goal_wake", root=root, cmid=cmid)
        woken += 1
    return woken


def wake_parked(*, goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None]) -> int:
    """``RT-GOAL-WAIT-WAKER``: continue every parked goal whose judge ``wait`` barrier has lifted.

    A bound run is parked when it is held, not stopping, its root has no send queued or running (that
    send's settle evaluates on its own), and its goal carries a barrier; a chat goal no run owns is parked
    when :func:`after_chat_goal_turn` recorded a :class:`chat_goal.ChatGoalPark`. ``is_waiting()`` is
    upstream's own test (pid alive, session still running, deadline ahead, the age cap) and clears a lifted
    barrier. Returns how many goals were continued.
    """

    return (_wake_bound(goals=goals, enqueue=enqueue, wake=wake)
            + _wake_chat_goals(goals=goals, enqueue=enqueue, wake=wake))
