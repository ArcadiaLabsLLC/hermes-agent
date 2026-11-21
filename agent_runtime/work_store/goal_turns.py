"""An ``UNTIL_DONE`` Work run: one user of its chat's standing goal (plan §2.2, §5; B3).

Row ``RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT``: a chat's goal and its
loop are the chat's own (``chat_goal``, ``chat_goal_loop``); a Work run arms that goal and links itself to
it for its bookkeeping, never a second continuation loop.

``PersonaTurnExecutor.start`` with ``goal_mode=UNTIL_DONE`` calls :func:`arm_run` before it queues the
first turn: the root's goal is set over upstream's ``GoalManager`` (``chat_goal.arm``) and a
``chat_goal.GoalBinding`` records that this run owns it. After EVERY terminal turn on a bound root — the
run's own and an operator's, queued or direct (:func:`direct_entry`) — :func:`after_turn` reads the judge's
decision (the turn engine's goal loop judged it; gates run in the run's workdir) and then either:

* ends — a stop, a failed turn, a report that says blocked/stopped, the judge's ending (the table
  :data:`DECISION_ENDINGS`), or the chat's goal paused or cleared under the run: the run's ``RowEnding``,
  a goal still active is paused, the root unbound;
* takes the chat goal loop's step (``chat_goal_loop.step``) — continue (sent as the run's next pass, its
  lent skills re-queued: :data:`SKILLS_ORIGIN`), hold (another send waits on the root and wins the slot),
  or park (the judge's ``wait``; :func:`wake_parked` sends the next pass when the barrier lifts).

A reply's own ``work_report`` that says ``blocked`` or ``stopped`` ends the run at once; a ``done``
report is believed only when the judge agrees (a failing gate is evidence it is not done).
Receipts: ``work.goal_arm | goal_continue | goal_hold | goal_wake | goal_stop | goal_end``.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .. import chat_goal, chat_goal_loop
from .. import chat_root_send_queue as send_queue
from ..chat_turn_settles import outcome_from_payload
from . import receipts
from .executor import CAUSE_OUT_OF_TIME, OPERATOR_STOP_REASON, Assignment, RowEnding, RunStatus, Verdict
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = [
    "DECISION_ENDINGS", "SKILLS_ORIGIN", "after_turn", "arm_run", "direct_entry",
    "end_stopped", "first_cmid", "out_of_time_ending", "pass_max_seconds", "run_status", "stop_from_conversation",
    "stop_run", "stop_with_goal", "stopping_pass", "wake_parked",
]

#: The origin key a Work run's lent skills ride in (``PersonaTurnExecutor.start_from`` writes it).
SKILLS_ORIGIN = "skills"
_RECOMMEND_BLOCKED = "re-scope the row, or resume the goal with runtime.chat.goal.resume"


#: One pass's wall budget: the chat goal loop's (a Work run's pass is a chat-goal continuation).
pass_max_seconds = chat_goal_loop.pass_max_seconds


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
    # MUTATION: drop ``max_turns`` and test_until_done_claim's "a run takes at most twenty passes" reddens.
    chat_goal.arm(root, a.brief.objective or a.brief.title, acceptance=a.brief.acceptance, gates=gates,
                  max_turns=chat_goal.MAX_PASSES, goals=goals)
    rows = tuple(tuple(ref.items()) for ref in a.rows)
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


def _names_pass(bound: chat_goal.GoalBinding, turn_id: str) -> bool:
    """``turn_id`` names a pass of ``bound``'s run — this one or an earlier one — as a client spells it:
    the send's client message id, or the turn id made of it (``serde.safe_assignment_token``)."""

    from ..serde import safe_assignment_token

    named, first = safe_assignment_token(turn_id), safe_assignment_token(first_cmid(bound.request_id))
    return bool(named) and (named == first or named.startswith(f"{first}-g"))


def stopping_pass(root: str, turn_id: str) -> bool:
    """``turn_id`` is a pass of the run bound to ``root`` and that run has been told to stop."""

    bound = chat_goal.binding(root)
    return bound is not None and bound.stopping and _names_pass(bound, turn_id)


def stop_from_conversation(root: str, turn_id: str) -> tuple[chat_goal.GoalBinding, bool] | None:
    """The conversation's own Stop on a pass of the ``UNTIL_DONE`` run bound to ``root``; None for any other turn.

    ``RT-UNTIL-DONE-CHAT-STOP-DOES-NOT-END-RUN``: a pass is a send the engine queued, so the Stop door's
    admission receipt never knew it and refused the Stop (``execution_not_admitted``, live 2026-11-12); the
    pass then settled a plain reply and the run went on. Here the run is marked ``stopping`` — its pass's
    settle ends the WHOLE run ``STOPPED`` however that pass settles (:func:`_ending_now` asks no judge) —
    and a pass that has not begun is taken off the root, so it never begins; the run then ends at the
    engine's next tick (:func:`end_stopped`). Returns the binding and whether its pass is running now (the
    caller interrupts a running one). A Stop naming an EARLIER pass of the run (it raced that pass's
    settle) stops the run just the same.
    """

    bound = chat_goal.binding(root)
    if bound is None or not _names_pass(bound, turn_id):
        return None
    return bound, _mark_stopping(bound)


def _mark_stopping(bound: chat_goal.GoalBinding) -> bool:
    """Tell the run to stop: a pass not yet begun leaves the root; answers whether a pass is running now."""

    root = bound.root_session_id
    entry = send_queue.find(root, bound.cmid)
    running = entry is not None and entry.state == send_queue.STATE_RUNNING
    # MUTATION: drop this bind and test_until_done_conversation_stop's plain-reply row reddens (the judge is
    # asked and the next pass is queued).
    chat_goal.bind(bound.advanced(stopping=True))
    if entry is not None and not running:
        send_queue.remove(root, bound.cmid)
    receipts.emit("work.goal_stop", root=root, request_id=bound.request_id, turn=bound.turns + 1, running=running)
    return running


def stop_with_goal(root: str) -> bool:
    """The chat's goal was paused or cleared (``runtime.chat.goal.pause | clear``): the Work run that uses it,
    if any, stops with it — a running pass ends the run at its settle, a queued one never begins, and the
    engine's tick reports a run with nothing in flight (:func:`end_stopped`). True when a run was told."""

    bound = chat_goal.binding(root)
    if bound is None or bound.stopping:
        return False
    _mark_stopping(bound)
    return True


def end_stopped(bound: chat_goal.GoalBinding, *, goals: Callable[[str], Any]) -> RowEnding | None:
    """The ending of a run told to stop that has NO pass on its root (queued or running), else None.

    A running pass ends the run at its own settle; this is the run whose stop found nothing in flight
    (:func:`stop_from_conversation` between two passes). The runner tells a settle before it removes the
    entry, so an absent entry is a pass that is not coming.
    """

    if not bound.stopping or send_queue.find(bound.root_session_id, bound.cmid) is not None:
        return None
    ending = RowEnding(Verdict.STOPPED, reason=OPERATOR_STOP_REASON)
    _end_goal(bound, goals, f"work run ended {ending.verdict.value}")
    receipts.emit("work.goal_end", root=bound.root_session_id, request_id=bound.request_id,
                  verdict=ending.verdict.value, turns=bound.turns)
    return ending


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
    chat_goal.unpark(bound.root_session_id)
    chat_goal.unbind(bound.root_session_id)


def _send_pass(bound: chat_goal.GoalBinding, prompt: str, *, enqueue: Callable[..., Any],
               wake: Callable[[], None]) -> str:
    """The run's next pass on its root: the continuation the chat's goal loop decided (``chat_goal_loop``)."""

    root = bound.root_session_id
    cmid = f"{first_cmid(bound.request_id)}-g{bound.turns + 1}"
    chat_goal.bind(bound.advanced(cmid=cmid, turns=bound.turns + 1, held=False))
    _requeue_skills(bound)
    enqueue(root, cmid, {**bound.turn_args, "message": prompt, "client_message_id": cmid})
    wake()
    receipts.emit("work.goal_continue", root=root, request_id=bound.request_id, cmid=cmid, turn=bound.turns + 1)
    return cmid


def _requeue_skills(bound: chat_goal.GoalBinding) -> None:
    """The run's lent skills, queued again for the continuation's turn (they were consumed by the last one)."""

    origin = bound.turn_args.get(send_queue.ORIGIN_ARG)
    skills = list(origin.get(SKILLS_ORIGIN) or ()) if isinstance(origin, dict) else []
    if skills:
        from ..queued_skills import queue_skills_for_next_turn

        queue_skills_for_next_turn(persona_id=str(bound.turn_args.get("persona_id") or ""),
                                   session_id=bound.root_session_id, skills=skills,
                                   persona_instance_id=bound.turn_args.get("persona_instance_id"))


def out_of_time_ending(payload: dict | None) -> RowEnding | None:
    """The ending of a run whose turn ended on its time budget; None when the turn did not.

    A turn that ran out of wall clock either settles ``chat_turn_budget_exhausted`` (the hard wall: no
    reply) or lands a checkpoint reply flagged ``budget_exhausted`` — and a checkpoint reply reports what
    is still in flight, so it rarely carries a ``work_report``. Either way the run did not fail for want
    of a report: it ran out of time, and the ending says so (:data:`executor.CAUSE_OUT_OF_TIME`).
    """

    from ..mission_chat_outcome import ChatErrorKind

    data = payload if isinstance(payload, dict) else {}
    hard_wall = outcome_from_payload(data).refusal_class == ChatErrorKind.CHAT_TURN_BUDGET_EXHAUSTED.value
    if not hard_wall and data.get("budget_exhausted") is not True:
        return None
    block = data.get("wall_budget")
    total = block.get("total_seconds") if isinstance(block, dict) else None
    budget = f"{total:g} s time budget" if isinstance(total, (int, float)) and not isinstance(total, bool) else "time budget"
    return RowEnding(Verdict.FAILED, reason=f"the turn used its {budget} before it reported", cause=CAUSE_OUT_OF_TIME)


def _ending_now(bound: chat_goal.GoalBinding, payload: dict | None, report: RowEnding | None, *,
                own: bool) -> RowEnding | None:
    """The endings no judge is asked about: a stop, a failed turn, a report that says blocked/stopped.

    A stop is the run's ``stopping`` mark (``runtime.work.cancel`` on the pass's running-work row, or the
    conversation's own Stop — :func:`stop_from_conversation`) or the run's OWN pass settling
    ``stopped: true``: either ends the WHOLE run, never one pass (``RT-WORK-CLAIM-RUNS-UNTIL-DONE``),
    however the pass itself settled. An operator's own turn stopped on the root ends nothing.
    """

    refusal = outcome_from_payload(payload).refusal_class
    # MUTATION: drop the ``own and stopped`` arm and test_until_done_claim's "Stop on a pass ends the whole
    # run" reddens (the judge is asked and the run goes on).
    if bound.stopping or (own and (payload or {}).get("stopped") is True):
        return RowEnding(Verdict.STOPPED, reason=OPERATOR_STOP_REASON)
    if refusal:
        return out_of_time_ending(payload) or RowEnding(Verdict.FAILED, reason=f"the turn ended {refusal}")
    if report is not None and report.verdict in (Verdict.BLOCKED, Verdict.STOPPED):
        return report
    return None


def _checked(bound: chat_goal.GoalBinding, goal: Any, reply: str, *, own: bool) -> Mapping[str, Any]:
    """The judge's decision on a pass that ended, with the run marked as checking while it is asked.

    The judge is a model call made from the runner's settle, before the pass's queue entry is removed, so the
    chat stays held for it — seconds with a real model, ~3 minutes on the QA fixture (three attempts, each held
    by the brief's own ``[[qa:hold …]]``). ``checking_since`` puts the run on ``running_work`` for that time
    (``running_work/lanes_chat.py``), so a message sent meanwhile waits behind something the app can show
    (RT-CHAT-HELD-BETWEEN-UNTIL-DONE-PASSES-LISTS-NOTHING-RUNNING). Every bind that follows starts from
    ``bound`` and so clears it; a judge that raises restores ``bound`` itself.
    """

    # MUTATION: drop this bind and test_until_done_run_says_it_is_checking reddens (no row while it checks).
    chat_goal.bind(bound.advanced(checking_since=time.time()))
    try:
        with _gate_cwd(bound.cwd):
            return goal.evaluate_after_turn(reply, user_initiated=not own)
    except BaseException:
        chat_goal.bind(bound)
        raise


def _stopped_while_checking(bound: chat_goal.GoalBinding) -> bool:
    """A Stop on the checking row (``runtime.work.cancel`` marks the binding ``stopping``) wins over the judge."""

    current = chat_goal.binding(bound.root_session_id)
    return current is not None and current.request_id == bound.request_id and current.stopping


def _goal_put_down(goal: Any) -> RowEnding | None:
    """The run's ending when its chat goal was paused or cleared under it (``runtime.chat.goal.pause|clear``,
    the operator's own ``/goal``): the run is a user of the chat's goal, so it stops with it."""

    state = getattr(goal, "state", None)
    status = getattr(state, "status", None) if state is not None else "cleared"
    if status not in ("paused", "cleared"):
        return None
    return RowEnding(Verdict.STOPPED, reason=f"the chat's goal was {status}")


def after_turn(bound: chat_goal.GoalBinding, entry: send_queue.QueuedSend, payload: dict | None, *,
               goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None],
               parse_report: Callable[[str], RowEnding | None]) -> RowEnding | None:
    """One terminal turn on a bound root: the run's ending, or None when it goes on."""

    # The turn engine marks a pass that ended as checking before its judge runs
    # (``operator_gateway_turn._mark_checking``); every bind below starts from an unmarked ``bound``.
    bound = bound.advanced(checking_since=None)
    reply = str((payload or {}).get("reply") or "")
    report = parse_report(reply)
    origin = entry.args.get(send_queue.ORIGIN_ARG)
    own = isinstance(origin, dict) and origin.get("work") == bound.request_id
    ending = _ending_now(bound, payload, report, own=own)
    if ending is None:
        goal = goals(bound.root_session_id)
        decision = _checked(bound, goal, reply, own=own)
        if _stopped_while_checking(bound):
            ending = RowEnding(Verdict.STOPPED, reason=OPERATOR_STOP_REASON)
        elif not decision.get("should_continue"):
            put_down = _goal_put_down(goal) if decision.get("verdict") == "waiting" else None
            ending = put_down or DECISION_ENDINGS.get(str(decision.get("verdict")), _stopped)(
                decision, report)
        if ending is None:
            moved = chat_goal_loop.step(bound.root_session_id, entry.client_message_id, goal, decision,
                                        send=lambda prompt: _send_pass(bound, prompt, enqueue=enqueue, wake=wake))
            if moved is chat_goal_loop.Step.HELD:
                chat_goal.bind(bound.advanced(held=True, turns=bound.turns + 1))
                receipts.emit("work.goal_hold", root=bound.root_session_id, request_id=bound.request_id)
            elif moved is not chat_goal_loop.Step.CONTINUED:
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


def _sender_of(*, enqueue: Callable[..., Any], wake: Callable[[], None]) -> Callable[[str], Any]:
    """The waker's sender for a root: a bound run's next pass; ``None`` for a root no run owns."""

    def sender_of(root: str) -> Any:
        bound = chat_goal.binding(root)
        if bound is None:
            return None
        if bound.stopping:
            raise LookupError(root)
        receipts.emit("work.goal_wake", root=root, request_id=bound.request_id)
        return lambda prompt: _send_pass(bound, prompt, enqueue=enqueue, wake=wake)

    return sender_of


def wake_parked(*, goals: Callable[[str], Any], enqueue: Callable[..., Any], wake: Callable[[], None]) -> int:
    """``RT-GOAL-WAIT-WAKER``: continue every parked chat goal whose judge ``wait`` barrier has lifted
    (``chat_goal_loop.wake``), a bound run's as its next pass. Returns how many goals were continued."""

    return chat_goal_loop.wake(goals=goals, enqueue=enqueue, wake_runner=wake,
                               sender_of=_sender_of(enqueue=enqueue, wake=wake))
