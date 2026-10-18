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
Receipts: ``work.goal_arm | goal_continue | goal_hold | goal_end``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .. import chat_goal
from .. import chat_root_send_queue as send_queue
from ..chat_turn_settles import outcome_from_payload
from . import receipts
from .executor import Assignment, RowEnding, RunStatus, Verdict
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["DECISION_ENDINGS", "after_turn", "arm_run", "first_cmid", "run_status", "stop_run"]

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


#: A judge decision that does NOT continue → the run's ending; ``None`` keeps the run (a parked wait).
DECISION_ENDINGS: dict[str, Callable[[Mapping[str, Any], RowEnding | None], RowEnding | None]] = {
    "done": _done,
    "blocked": _blocked,
    "wait": lambda decision, report: None,
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
    enqueue(root, cmid, {**bound.turn_args, "message": prompt, "client_message_id": cmid})
    wake()
    receipts.emit("work.goal_continue", root=root, request_id=bound.request_id, cmid=cmid, turn=bound.turns + 1)


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
