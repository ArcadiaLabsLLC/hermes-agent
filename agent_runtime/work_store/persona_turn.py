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
not begun and waits on a running turn (RULED on ``RT-DISPATCH-B2-BATCH``). ``goal_mode=UNTIL_DONE``
is refused until the dispatcher's B3.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from .. import chat_root_send_queue as send_queue
from .. import paths
from ..chat_turn_settles import outcome_from_payload, read_settle, settle_id_for
from . import receipts
from .executor import (
    Assignment, ExecutorKind, GoalMode, Outcome, RowEnding, Run, RunStatus, StopReason, Verdict,
)
from .grammar import RowRef
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["BRIEF_MAX_LINES", "REPORT_INFO", "PersonaTurnExecutor", "parse_work_report", "render_brief"]

REPORT_INFO = "work_report"
BRIEF_MAX_LINES = 40
_REPORT_FENCE = re.compile(r"^[ \t]*```[ \t]*work_report[ \t]*\r?\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)
_VERDICTS = {"done": Verdict.DONE, "blocked": Verdict.BLOCKED, "stopped": Verdict.STOPPED}
_REPORT_TAIL = 4000
_CLOSING = (
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
    return "\n".join([*head, *body][:BRIEF_MAX_LINES - len(_CLOSING)] + list(_CLOSING))


def _norm(value: Any) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def _same_root(runtime_root: str) -> bool:
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
    ) -> None:
        self._enqueue = enqueue
        self._wake = wake
        self._open_chat = open_chat
        self._instances = instances
        self._root_of = root_of
        self._draining = draining
        self._callback: Callable[[Run, Outcome], None] | None = None

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

    def _open(self, instance: Any, a: Assignment) -> str:
        from ..mission_chat_door import MissionChatDoorUnbound, run_open_chat

        args = SimpleNamespace(
            persona_id=instance.persona_id, persona_instance_id=instance.id, session_id=None, new_session=False,
            client_scope=None, kill_active=False, idempotency_key=f"work-open-{a.request_id}",
            requested_by=f"work:{a.request_id}", add_instance=False, placement_id=None, display_name=None,
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
        if a.goal_mode is GoalMode.UNTIL_DONE:
            return Reason.GOAL_MODE_UNSUPPORTED
        if self._draining():
            return Reason.DRAIN_BEGUN
        instance = self._instance(a.persona_instance_id)
        if instance is None or not _same_root(getattr(instance, "runtime_root", "")):
            return Reason.PERSONA_UNAVAILABLE
        return None

    def start(self, a: Assignment) -> Run:
        refusal = self.can_start(a)
        if refusal is not None:
            raise WorkRefused(refusal, a.persona_instance_id)
        instance = self._instance(a.persona_instance_id)
        root = self._root(instance) or self._open(instance, a)
        cmid = f"work-{a.request_id}"
        origin = {"owner": None, "gateway": False, "work": a.request_id,
                  "rows": [[ref.slot, ref.note, ref.id] for ref in a.rows]}
        entry, _position, _replay = self._enqueue(
            root, cmid, send_queue.persistable_args(_turn_args(instance, root, cmid, a), origin=origin))
        (self._wake or _wake_runner)()
        receipts.emit("work.exec_start", run_id=_run_id(root, cmid), request_id=a.request_id,
                      persona_instance_id=a.persona_instance_id, rows=[ref.id for ref in a.rows],
                      executor=self.kind.value)
        return Run(_run_id(root, cmid), a.request_id, a, root, cmid, entry.queued_at, RunStatus.QUEUED)

    def status(self, run_id: str) -> RunStatus:
        root, _sep, cmid = run_id.partition("/")
        if read_settle(settle_id_for(root, cmid)) is not None:
            return RunStatus.SETTLED
        entry = send_queue.find(root, cmid)
        if entry is None:
            return RunStatus.STOPPED
        return RunStatus.RUNNING if entry.state == send_queue.STATE_RUNNING else RunStatus.QUEUED

    def stop(self, run_id: str, reason: StopReason) -> dict[str, Any]:
        root, _sep, cmid = run_id.partition("/")
        entry = send_queue.find(root, cmid)
        stopped = entry is not None and entry.state == send_queue.STATE_QUEUED and send_queue.remove(root, cmid)
        detail = "" if stopped else "the turn ends on its own"
        return receipts.emit("work.exec_stop", run_id=run_id, reason=StopReason(reason).value, stopped=bool(stopped),
                             detail=detail)

    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None:
        self._callback = cb

    # ── the runner's hook ────────────────────────────────────────────────

    def settled(self, entry: send_queue.QueuedSend, exit_code: int, payload: dict | None) -> None:
        """``RunnerPolicy.on_settle``: a queued send ended; report it when it was a Work run."""

        origin = entry.args.get(send_queue.ORIGIN_ARG)
        request_id = origin.get("work") if isinstance(origin, dict) else None
        if not request_id or self._callback is None:
            return
        rows = tuple(RowRef(*map(str, item)) for item in origin.get("rows") or [] if len(item) == 3)
        outcome = outcome_of(exit_code, payload, rows)
        run = Run(_run_id(entry.root_session_id, entry.client_message_id), str(request_id), None,
                  entry.root_session_id, entry.client_message_id, entry.queued_at, RunStatus.SETTLED)
        receipts.emit("work.exec_settle", run_id=run.run_id, request_id=run.request_id, rows=[r.id for r in rows],
                      executor=self.kind.value, verdict=outcome.verdict.value, tool_calls=outcome.tool_calls)
        self._callback(run, outcome)


def outcome_of(exit_code: int, payload: dict | None, rows: tuple[RowRef, ...]) -> Outcome:
    """The run's outcome: the reply's ``work_report`` ending, else ``FAILED`` with what the turn said."""

    reply = str((payload or {}).get("reply") or "")
    ending = parse_work_report(reply)
    if ending is None:
        refusal = outcome_from_payload(payload).refusal_class
        detail = f"the turn ended {refusal}" if refusal else f"no readable {REPORT_INFO} block (exit {exit_code})"
        ending = RowEnding(Verdict.FAILED, reason=detail)
    return Outcome(ending.verdict, {ref: ending for ref in rows}, report=reply[-_REPORT_TAIL:])


def _wake_runner() -> None:
    from ..chat_root_send_runner import wake_queued_send_runner

    wake_queued_send_runner()


def _turn_args(instance: Any, root: str, cmid: str, a: Assignment) -> SimpleNamespace:
    """The namespace ``dispatch_delivery.forge.forge_delivery_turn`` builds, carrying the brief."""

    from ..config import mission_chat_default_max_seconds

    return SimpleNamespace(
        persona_id=instance.persona_id, persona_instance_id=instance.id, session_id=root, clarify_token=None,
        new_session=False, task_id=None, goal_id=None, title=None, message=render_brief(a), provider=None,
        model=None, use_agent_default=False, surface_prompt="", intent_hint="chat",
        requested_by=f"work:{a.request_id}", client_message_id=cmid, stream=False,
        max_seconds=float(mission_chat_default_max_seconds()), json=True, requested_by_session=root,
        relay_chain=[], relay_deadline_epoch=None,
    )
