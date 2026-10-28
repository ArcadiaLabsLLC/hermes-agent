"""``PersonaTurnExecutor`` — a claimed row runs as one chat turn of the claiming persona instance.

Work plan ``work-on-markdown-2026-10-18.md`` §6.3 (W3), behind the dispatcher plan's §2.2 contract
(``executor.py``). ``start`` never runs a turn itself: it ENQUEUES the brief on the instance's chat
root through the busy-root send queue (``chat_root_send_queue.enqueue``) and wakes the serve's
queued-send runner, so the runner's idle-root gate is the hold-until-idle rule and the turn runs
through the mission-chat door exactly as a queued operator send does. The entry carries its origin
(``{"work": <request_id>, "rows": [...]}``), so when the runner settles it (``RunnerPolicy.on_settle``
→ :meth:`PersonaTurnExecutor.settled`) the run and its rows are known even after a restart.

The ending is the LAST fenced ``work_report`` block of the reply (:func:`parse_work_report`); no block,
an unknown verdict, or a ``blocked`` with no question is ``FAILED``. ``stop`` removes a send that has
not begun and waits on a running turn (RULED on ``RT-DISPATCH-B2-BATCH``).

``goal_mode=UNTIL_DONE`` (dispatcher B3): ``start`` sets a goal on the root and binds the root to the
run (``goal_turns.arm_run``); every terminal settle on a bound root goes to ``goal_turns.after_turn``,
which continues the run as further queued sends until upstream's gates and judge end it.

A settle is routed by its origin's KIND through one table (:class:`OriginKind`, RT-SEND-ORIGIN-KIND-TABLE,
p10-messaging §3 M3): ``work`` reports the run, ``goal`` is the root's chat goal, and a lane registers its
own kind (:meth:`PersonaTurnExecutor.register_origin_listener`; the messaging bridge's ``messaging``).
Pinned by ``tests/agent_runtime/work_store/test_origin_listener_table.py`` and
``tests/agent_runtime/messaging/test_bridge_inbound.py``.

``Assignment.skills`` (a row's ``skills:`` segment, p10-work S1): before anything is armed or queued the
skills are queued for the run's turn on the root (``chat_verbs.queue_skill.queue_skills_next_turn``, the
``runtime.chat.queue_skill`` row); one unloadable skill refuses the run ``skills_not_loadable`` with nothing
enqueued. The origin carries them, so every ``UNTIL_DONE`` continuation re-queues them (``goal_turns``).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from enum import StrEnum
from types import SimpleNamespace
from typing import Any, NamedTuple

from .. import chat_goal
from .. import chat_root_send_queue as send_queue
from .. import paths
from ..chat_turn_settles import outcome_from_payload, read_settle, settle_id_for
from ..mission_chat_workdir import RUN_WORKDIR_ARG
from . import goal_turns, receipts
from .executor import (
    Assignment, Brief, ExecutorKind, GoalMode, Outcome, RowEnding, Run, RunStatus, StopReason, Verdict,
)
from .grammar import RowRef
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
logger = logging.getLogger(__name__)
__all__ = ["BRIEF_MAX_LINES", "ORIGIN_KIND_KEY", "REPORT_CLOSING", "REPORT_INFO", "OriginKind", "OriginListener",
           "PersonaTurnExecutor", "Queued", "origin_kind", "parse_work_report", "render_brief", "runs_here"]

REPORT_INFO = "work_report"
BRIEF_MAX_LINES = 40
_REPORT_FENCE = re.compile(r"^[ \t]*```[ \t]*work_report[ \t]*\r?\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)
_VERDICTS = {"done": Verdict.DONE, "blocked": Verdict.BLOCKED, "stopped": Verdict.STOPPED}
_REPORT_TAIL = 4000
REPORT_CLOSING = (
    "",
    f"When you finish, END your reply with a fenced code block whose info string is `{REPORT_INFO}`:",
    f"```{REPORT_INFO}",
    "verdict: done | blocked | stopped",
    "result: <one line: what you did, or why you stopped>",
    "question: <blocked only: the one question for the owner>",
    "recommend: <blocked only: the answer you recommend>",
    "```",
)


def parse_work_report(reply: str) -> RowEnding | None:
    """The ending the LAST fenced ``work_report`` block carries, or None when it is unreadable."""

    blocks = _REPORT_FENCE.findall(str(reply or ""))
    if not blocks:
        return None
    fields: dict[str, str] = {}
    for line in blocks[-1].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip().lower()] = " ".join(value.split())
    verdict = _VERDICTS.get(fields.get("verdict", "").lower())
    if verdict is None or (verdict is Verdict.BLOCKED and not fields.get("question")):
        return None
    return RowEnding(verdict, result=fields.get("result", ""), question=fields.get("question", ""),
                     recommend=fields.get("recommend", ""), reason=fields.get("reason") or fields.get("result", ""))


def _clip(lines: list[str], budget: int) -> list[str]:
    return lines if len(lines) <= budget else [*lines[:budget - 1], "…"]


def render_brief(a: Assignment) -> str:
    """The turn's message, at most :data:`BRIEF_MAX_LINES` lines: the row(s), the brief, the closing ask.

    ``brief.inputs`` carries the row line(s) verbatim first, then each pointer (the engine builds it so).
    """

    brief = a.brief
    head = [f"Work assignment: {brief.title}", "", "Rows (slot, note, ID):"]
    head += _clip([f"- {ref.slot} · {ref.note} · {ref.id}" for ref in a.rows], 4)
    body = ["", "Objective:", *_clip([line for line in brief.objective.splitlines() if line.strip()] or
                                     [brief.title], 12)]
    if brief.inputs:
        body += ["", "Inputs:", *_clip([f"- {item}" for item in brief.inputs], 8)]
    if brief.constraints:
        body += ["", "Constraints:", *_clip([f"- {item}" for item in brief.constraints], 3)]
    if brief.acceptance:
        body += ["", f"Done when: {' '.join(brief.acceptance.split())[:500]}"]
    return "\n".join([*head, *body][:BRIEF_MAX_LINES - len(REPORT_CLOSING)] + list(REPORT_CLOSING))


class OriginKind(StrEnum):
    """Who a queued send's settle is reported to — the key of :class:`PersonaTurnExecutor`'s listener table."""

    WORK = "work"
    GOAL = "goal"
    MESSAGING = "messaging"


#: The origin field naming its kind. An entry queued before the field existed is read by its legacy shape.
ORIGIN_KIND_KEY = "kind"
#: The root's own arms: on a root bound to an ``UNTIL_DONE`` run the goal hook replaces them; a registered
#: kind (a platform reply) is still told.
_ROOT_ARMS = frozenset({OriginKind.WORK, OriginKind.GOAL})

OriginListener = Callable[[send_queue.QueuedSend, int, "dict | None"], None]


def origin_kind(origin: Any) -> OriginKind:
    """The settle's kind: the origin's own ``kind``, else (an entry queued before it) ``work`` when a Work
    request names it and ``goal`` for any other origin — an operator send, a scheduled prompt."""

    if not isinstance(origin, Mapping):
        return OriginKind.GOAL
    try:
        return OriginKind(origin.get(ORIGIN_KIND_KEY))
    except ValueError:
        return OriginKind.WORK if origin.get("work") else OriginKind.GOAL


class Queued(NamedTuple):
    """What :meth:`PersonaTurnExecutor.queue_inbound` did: the run, its 1-based place on the root (0 once
    settled), and whether it converged on an entry or a settle that already existed."""

    run: Run
    position: int
    replay: bool


def _norm(value: Any) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def runs_here(runtime_root: str) -> bool:
    """The instance lives in THIS runtime's store (an instance of another machine is not runnable here)."""

    return bool(str(runtime_root or "").strip()) and _norm(runtime_root) == _norm(paths.store_root())


def _run_id(root: str, cmid: str) -> str:
    return f"{root}/{cmid}"


class PersonaTurnExecutor:
    """One chat turn per assignment, queued on the instance's own chat root."""

    kind = ExecutorKind.PERSONA_TURN

    def __init__(
        self,
        *,
        enqueue: Callable[..., Any] = send_queue.enqueue,
        wake: Callable[[], None] | None = None,
        open_chat: Callable[[Any], tuple[int, dict | None]] | None = None,
        instances: Any = None,
        root_of: Callable[..., str | None] | None = None,
        draining: Callable[[], bool] = lambda: False,
        goals: Callable[[str], Any] = chat_goal.manager,
        workdir_of: Callable[[Any], str | None] | None = None,
        queue_skills: Callable[..., dict] | None = None,
    ) -> None:
        self._enqueue = enqueue
        self._wake = wake
        self._open_chat = open_chat
        self._instances = instances
        self._root_of = root_of
        self._draining = draining
        self._goals = goals
        self._workdir_of = workdir_of or _persona_workdir
        self._queue_skills = queue_skills
        self._callbacks: list[Callable[[Run, Outcome], None]] = []
        self._origin_listeners: dict[OriginKind, OriginListener] = {
            OriginKind.WORK: self._work_settled, OriginKind.GOAL: self._goal_settled}

    # ── the seams, resolved on first use (the serve builds this before the door is bound) ──

    def _store(self) -> Any:
        if self._instances is None:
            from ..persona_assignments.store import PersonaInstanceStore

            self._instances = PersonaInstanceStore()
        return self._instances

    def _instance(self, instance_id: str) -> Any | None:
        try:
            return self._store().get(instance_id)
        except Exception:
            return None

    def _root(self, instance: Any) -> str | None:
        if self._root_of is None:
            from ..persona_assignments.lookups import resolve_default_chat_session_id_for_instance

            self._root_of = resolve_default_chat_session_id_for_instance
        return self._root_of(self._store(), persona_id=instance.persona_id, persona_instance_id=instance.id)

    def current_root(self, instance_id: str) -> str | None:
        """The instance's current chat root, or None (no such instance, or no chat yet); never mints."""

        instance = self._instance(instance_id)
        return None if instance is None else self._root(instance)

    def _open(self, instance: Any, request_id: str) -> str:
        from ..mission_chat_door import MissionChatDoorUnbound, run_open_chat

        args = SimpleNamespace(
            persona_id=instance.persona_id, persona_instance_id=instance.id, session_id=None, new_session=False,
            client_scope=None, idempotency_key=f"work-open-{request_id}",
            requested_by=f"work:{request_id}", add_instance=False, placement_id=None, display_name=None,
            workspace_id=None, realm_id=None, coordinator_id=None, coordinator_max_spawns=None,
            coordinator_spawns_used=0, coordinator_may_kill_own=None, coordinator_no_kill_own=None,
            coordinator_may_kill_others=None, json=True, stream=False,
        )
        try:
            _code, payload = (self._open_chat or run_open_chat)(args)
        except MissionChatDoorUnbound as exc:
            raise WorkRefused(Reason.DOOR_UNBOUND, str(exc)) from exc
        session = str((payload or {}).get("session_id") or "").strip()
        if not session:
            raise WorkRefused(Reason.PERSONA_UNAVAILABLE, "opening the instance's chat returned no session")
        return session

    # ── the contract ─────────────────────────────────────────────────────

    def can_start(self, a: Assignment) -> Reason | None:
        if self._draining():
            return Reason.DRAIN_BEGUN
        instance = self._instance(a.persona_instance_id)
        if instance is None or not runs_here(getattr(instance, "runtime_root", "")):
            return Reason.PERSONA_UNAVAILABLE
        return None

    def start(self, a: Assignment) -> Run:
        return self.start_from(a, {})

    def start_from(self, a: Assignment, origin: Mapping[str, Any], *, message: str | None = None,
                   workdir: str | None = None) -> Run:
        """:meth:`start`, with ``origin`` added to the queued entry's origin (a scheduled fire names itself there).

        ``message`` replaces the rendered brief and ``workdir`` is the run's own working directory (the
        turn's ``run_workdir``, on top of the persona's ladder): a batch lane's brief and worktree (B5).
        """

        refusal = self.can_start(a)
        if refusal is not None:
            raise WorkRefused(refusal, a.persona_instance_id)
        instance = self._instance(a.persona_instance_id)
        root = self._root(instance) or self._open(instance, a.request_id)
        cmid = goal_turns.first_cmid(a.request_id)
        until_done = a.goal_mode is GoalMode.UNTIL_DONE
        origin = {**dict(origin), "owner": None, "gateway": False, ORIGIN_KIND_KEY: OriginKind.WORK.value,
                  "work": a.request_id,
                  "rows": [[ref.slot, ref.note, ref.id] for ref in a.rows], "goal": until_done,
                  **({goal_turns.SKILLS_ORIGIN: list(a.skills)} if a.skills else {})}
        if a.skills:
            self._lend(instance, root, a)
        turn = _turn_args(instance, root, cmid, message or render_brief(a), f"work:{a.request_id}")
        if workdir:
            setattr(turn, RUN_WORKDIR_ARG, workdir)
        args = send_queue.persistable_args(turn, origin=origin)
        if until_done:
            goal_turns.arm_run(root, a, args, cwd=workdir or self._workdir_of(instance), goals=self._goals)
        entry, _position, _replay = self._enqueue(root, cmid, args)
        (self._wake or _wake_runner)()
        receipts.emit("work.exec_start", run_id=_run_id(root, cmid), request_id=a.request_id,
                      persona_instance_id=a.persona_instance_id, rows=[ref.id for ref in a.rows],
                      executor=self.kind.value)
        return Run(_run_id(root, cmid), a.request_id, a, root, cmid, entry.queued_at, RunStatus.QUEUED)

    def _lend(self, instance: Any, root: str, a: Assignment) -> None:
        """Queue the assignment's skills for the run's turn; an unloadable one refuses the whole run."""

        if self._queue_skills is None:
            from ..chat_verbs.queue_skill import queue_skills_next_turn

            self._queue_skills = queue_skills_next_turn
        reply = self._queue_skills(persona_id=instance.persona_id, session_id=root,
                                   persona_instance_id=instance.id, skills=list(a.skills))
        if not reply.get("ok"):
            rejected = dict(reply.get("rejected_skills") or {})
            raise WorkRefused(Reason.SKILLS_NOT_LOADABLE, ", ".join(sorted(rejected)) or str(reply.get("error") or ""),
                              data={"rejected_skills": rejected})

    def queue_prompt(self, persona_instance_id: str, message: str, *, request_id: str,
                     origin: Mapping[str, Any]) -> Run:
        """Queue ``message`` as one turn of the instance's chat root — a scheduled ``PersonaPrompt`` (B4).

        :meth:`queue_inbound` with the scheduler's cmid (``schedule-<request_id>``) and requester; its settle
        is the root's chat goal's, reporting to no Work run.
        """

        return self.queue_inbound(persona_instance_id, message, request_id=request_id, origin=origin,
                                  cmid_prefix="schedule-", requested_by=f"schedule:{request_id}").run

    def queue_inbound(self, persona_instance_id: str, message: str, *, request_id: str, origin: Mapping[str, Any],
                      cmid_prefix: str, requested_by: str) -> Queued:
        """Queue ``message`` verbatim as one turn of the instance's chat root (p10-messaging §3 M3).

        The same hold-until-idle path as :meth:`start` (the root's send queue, never the door): a busy root
        holds the entry until idle. Idempotent by ``cmid_prefix + request_id``: a re-presented request
        converges on the one queued entry, or on the turn's settle once it ran (``replay`` True, nothing
        queued). The root is the instance's current one, or minted (``open_chat``), at queue time.
        """

        probe = Assignment((), persona_instance_id, Brief(title="", objective=""), request_id)
        refusal = self.can_start(probe)
        if refusal is not None:
            raise WorkRefused(refusal, persona_instance_id)
        instance = self._instance(persona_instance_id)
        root = self._root(instance) or self._open(instance, request_id)
        cmid = f"{cmid_prefix}{request_id}"
        if send_queue.find(root, cmid) is None and read_settle(settle_id_for(root, cmid)) is not None:
            return Queued(Run(_run_id(root, cmid), request_id, None, root, cmid, "", RunStatus.SETTLED), 0, True)
        turn = _turn_args(instance, root, cmid, message, requested_by)
        entry, position, replay = self._enqueue(root, cmid, send_queue.persistable_args(turn, origin=origin))
        (self._wake or _wake_runner)()
        return Queued(Run(_run_id(root, cmid), request_id, None, root, cmid, entry.queued_at, RunStatus.QUEUED),
                      int(position), bool(replay))

    def status(self, run_id: str) -> RunStatus:
        root, _sep, cmid = run_id.partition("/")
        bound = chat_goal.binding(root)
        if bound is not None and goal_turns.first_cmid(bound.request_id) == cmid:
            return goal_turns.run_status(bound)
        if read_settle(settle_id_for(root, cmid)) is not None:
            return RunStatus.SETTLED
        entry = send_queue.find(root, cmid)
        if entry is None:
            return RunStatus.STOPPED
        return RunStatus.RUNNING if entry.state == send_queue.STATE_RUNNING else RunStatus.QUEUED

    def stop(self, run_id: str, reason: StopReason) -> dict[str, Any]:
        root, _sep, cmid = run_id.partition("/")
        bound = chat_goal.binding(root)
        if bound is not None and goal_turns.first_cmid(bound.request_id) == cmid:
            stopped = goal_turns.stop_run(bound, goals=self._goals)
        else:
            entry = send_queue.find(root, cmid)
            stopped = entry is not None and entry.state == send_queue.STATE_QUEUED and send_queue.remove(root, cmid)
        detail = "" if stopped else "the turn ends on its own"
        return receipts.emit("work.exec_stop", run_id=run_id, reason=StopReason(reason).value, stopped=bool(stopped),
                             detail=detail)

    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None:
        """Add a listener: the W3 engine and the batch dispatcher (B2) each hear every settle and
        ignore a run they did not start (the engine by run record, the dispatcher by ``BATCH-`` id)."""

        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def register_origin_listener(self, kind: OriginKind, cb: OriginListener) -> None:
        """Route the settles whose origin is ``kind`` to ``cb(entry, exit_code, payload)`` (one per kind)."""

        kind = OriginKind(kind)
        if kind in _ROOT_ARMS:
            raise ValueError(f"the {kind.value} arm is the executor's own")
        self._origin_listeners[kind] = cb

    def unregister_origin_listener(self, kind: OriginKind) -> None:
        if OriginKind(kind) not in _ROOT_ARMS:
            self._origin_listeners.pop(OriginKind(kind), None)

    # ── the runner's hook ────────────────────────────────────────────────

    def settled(self, entry: send_queue.QueuedSend, exit_code: int, payload: dict | None) -> None:
        """``RunnerPolicy.on_settle``: a queued send ended; route it by its origin's kind.

        On a root bound to an ``UNTIL_DONE`` run every settle — the run's own or an operator's, queued or
        direct (:func:`goal_turns.direct_entry`) — is the goal's after-turn hook; the run is reported only
        when the hook ends it, and a registered kind (a platform reply) is told as well. On any other root
        the kind's listener alone hears it; a kind nobody registered falls to the root's chat goal.
        """

        kind = origin_kind(entry.args.get(send_queue.ORIGIN_ARG))
        bound = chat_goal.binding(entry.root_session_id)
        if bound is not None:
            self._bound_settled(bound, entry, payload)
            listener = None if kind in _ROOT_ARMS else self._origin_listeners.get(kind)
        else:
            listener = self._origin_listeners.get(kind) or self._origin_listeners[OriginKind.GOAL]
        if listener is None:
            return
        if kind in _ROOT_ARMS:
            listener(entry, exit_code, payload)
            return
        try:
            listener(entry, exit_code, payload)
        except Exception:
            logger.warning("the %s settle listener failed on %s", kind.value, entry.client_message_id, exc_info=True)

    def _bound_settled(self, bound: Any, entry: send_queue.QueuedSend, payload: dict | None) -> None:
        ending = goal_turns.after_turn(bound, entry, payload, goals=self._goals, enqueue=self._enqueue,
                                       wake=self._wake or _wake_runner, parse_report=parse_work_report)
        if ending is not None:
            rows = tuple(RowRef(*row) for row in bound.rows)
            outcome = Outcome(ending.verdict, {ref: ending for ref in rows},
                              report=str((payload or {}).get("reply") or "")[-_REPORT_TAIL:])
            self._report(bound.request_id, bound.root_session_id, goal_turns.first_cmid(bound.request_id),
                         entry.queued_at, rows, outcome)

    def _work_settled(self, entry: send_queue.QueuedSend, exit_code: int, payload: dict | None) -> None:
        origin = entry.args.get(send_queue.ORIGIN_ARG) or {}
        rows = tuple(RowRef(*map(str, item)) for item in origin.get("rows") or [] if len(item) == 3)
        self._report(str(origin.get("work")), entry.root_session_id, entry.client_message_id, entry.queued_at, rows,
                     outcome_of(exit_code, payload, rows))

    def _goal_settled(self, entry: send_queue.QueuedSend, _exit_code: int, payload: dict | None) -> None:
        goal_turns.after_chat_goal_turn(entry, payload, goals=self._goals, enqueue=self._enqueue,
                                        wake=self._wake or _wake_runner)

    def direct_settled(self, root: str, cmid: str, exit_code: int, payload: dict | None,
                       args_of: Callable[[], Mapping[str, Any]]) -> None:
        """The serve's direct-turn settle: a send that ran outside the queue reaches :meth:`settled` once.

        Only a root with a goal (a bound run, or an active chat goal) pays for ``args_of`` — the parse of
        the turn's argv its continuation would be queued from.
        """

        if chat_goal.binding(root) is None and not self._goals(root).is_active():
            return
        self.settled(goal_turns.direct_entry(root, cmid, args_of()), exit_code, payload)

    def wake_parked(self) -> int:
        """The serve's waker for a judge ``wait`` (``goal_turns.wake_parked``), run on the engine's tick."""

        return goal_turns.wake_parked(goals=self._goals, enqueue=self._enqueue, wake=self._wake or _wake_runner)

    def _report(self, request_id: str, root: str, cmid: str, queued_at: str, rows: tuple[RowRef, ...],
                outcome: Outcome) -> None:
        if not self._callbacks:
            return
        run = Run(_run_id(root, cmid), request_id, None, root, cmid, queued_at, RunStatus.SETTLED)
        receipts.emit("work.exec_settle", run_id=run.run_id, request_id=run.request_id, rows=[r.id for r in rows],
                      executor=self.kind.value, verdict=outcome.verdict.value, tool_calls=outcome.tool_calls)
        for callback in list(self._callbacks):
            try:
                callback(run, outcome)
            except Exception:
                logger.warning("a settle listener failed on %s", run.request_id, exc_info=True)


def outcome_of(exit_code: int, payload: dict | None, rows: tuple[RowRef, ...]) -> Outcome:
    """The run's outcome: the reply's ``work_report`` ending, else ``FAILED`` with what the turn said."""

    reply = str((payload or {}).get("reply") or "")
    ending = parse_work_report(reply)
    if ending is None:
        refusal = outcome_from_payload(payload).refusal_class
        detail = f"the turn ended {refusal}" if refusal else f"no readable {REPORT_INFO} block (exit {exit_code})"
        ending = RowEnding(Verdict.FAILED, reason=detail)
    return Outcome(ending.verdict, {ref: ending for ref in rows}, report=reply[-_REPORT_TAIL:])


def _persona_workdir(instance: Any) -> str | None:
    """Where the instance's persona works — the cwd its goal gates run in."""

    from ..mission_chat_workdir import mission_chat_workdir_for_persona

    return mission_chat_workdir_for_persona(SimpleNamespace(id=instance.persona_id)).path


def _wake_runner() -> None:
    from ..chat_root_send_runner import wake_queued_send_runner

    wake_queued_send_runner()


def _turn_args(instance: Any, root: str, cmid: str, message: str, requested_by: str) -> SimpleNamespace:
    """The namespace ``dispatch_delivery.forge.forge_delivery_turn`` builds, carrying ``message``."""

    from ..config import mission_chat_default_max_seconds

    return SimpleNamespace(
        persona_id=instance.persona_id, persona_instance_id=instance.id, session_id=root, clarify_token=None,
        new_session=False, task_id=None, goal_id=None, title=None, message=message, provider=None,
        model=None, use_agent_default=False, surface_prompt="", intent_hint="chat",
        requested_by=requested_by, client_message_id=cmid, stream=False,
        max_seconds=float(mission_chat_default_max_seconds()), json=True, requested_by_session=root,
        relay_chain=[], relay_deadline_epoch=None,
    )
