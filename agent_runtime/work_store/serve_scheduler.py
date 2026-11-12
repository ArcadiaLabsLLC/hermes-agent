"""``ServeTickScheduler`` — the desktop runtime's scheduler, ticked by the serve (dispatcher plan §2.3, §4; B4).

RULED 2026-10-18 (``RT-DISPATCH-B4-SCHEDULER``): upstream cron is scrapped for this scheduler; nothing
here imports upstream's cron runner, and ``Trigger.from_cron_job`` is the one compatibility door. On a
phone a schedule rides the OS scheduler (the Launcher's ``OsReminderScheduler``); this module builds
nothing mobile, and its wire (``schedule_store.ScheduleRecord.wire``) is what a mirror reads.

Manual by default: nothing fires unless an operator armed it (``runtime.schedule.arm``, or the
``schedule_manage`` tool of a persona the operator opted into the ``schedule`` toolset).

* **State is files** (``schedule_store``): every verb and every tick reads ``store/schedules/``; the
  ticker holds nothing of its own.
* **A fire is a queued turn.** ``PersonaPrompt`` and ``RunAssignment`` enqueue on the instance's chat root
  through ``PersonaTurnExecutor.queue_prompt`` / ``start_from`` (``chat_root_send_queue``), so a busy root holds the fire until idle and
  never steers (RT-D3 by construction); the entry's origin names the schedule, which is what the
  ``running_work`` ``scheduled_turn`` lane reads. A ``RunAssignment`` goes through the Work engine's door
  the serve binds (``WorkEngine.adopt``: claim, record, start; ``door_unbound`` until it does), so its
  settle is written back to the row. ``StartBatch`` goes through the batch door the
  dispatcher binds (``door_unbound`` until it does) and is armed only when the workspace's
  ``batch_automation`` is ``start``. An Action is never a script (RT-D1).
* **A ``RunTask``** (``RT-SCHEDULE-RUN-TASK-REPEATS``) names a board task, an agent and a goal mode and
  no brief: each fire goes through ``WorkEngine.adopt_task`` under the request id ``<key>@<fire stamp>``,
  which builds the assignment from the row as it reads THEN; a run of an ``every`` / ``cron`` schedule
  that ends DONE leaves the row open and unclaimed, and a fire that finds the row gone removes the
  schedule (``schedule.abandoned``, ``reason: row_gone``).
* **``arm(..., replace=True)``** overwrites the record under the key (an edit); without it a second arm
  joins the first. An edit keeps the schedule's ``fires`` count and its ``last_result``.
* **Pause / resume** (``RT-SCHEDULE-PAUSE-END-AND-LAST-RESULT``) flip ``enabled``; a paused record never
  fires, and ``resume`` computes ``next_fire`` from now (a paused hour is not caught up).
* **An end.** ``ends_after_fires`` / ``ends_until``: a schedule whose started fires reached the count, or
  whose next fire falls after the time, is removed with a ``schedule.ended`` receipt.
* **``skip_while_running``** (default on for a ``RunTask``): a fire that finds the task's last run still
  live advances ``next_fire``, counts nothing and records a ``skipped`` ``last_result`` (``schedule.skipped``).
* **``last_result``** (``schedule_store.write_result``): written here for a ``skipped`` or ``refused`` fire,
  and by the Work engine when the fire's run settles (``RunRecord.schedule``).
* **The cap.** At most ``max_parallel`` scheduled turns in flight — the root config's
  ``agent_runtime.scheduler.max_parallel``, read each tick (default 4, ``0`` unlimited); a due fire
  over the cap stays due, logs ``schedule.queued`` once, and its ``schedule.fire`` carries ``waited_s``
  (RT-D5 by construction).
* **WHEN_IDLE** is the Launcher's ``AfterReplyScheduler`` rule: the root reads idle (no turn holds its lease,
  nothing queued on it) on ``settle_ticks`` consecutive ticks, else it gives up after 15 minutes
  (``schedule.abandoned``).
* **Never during a drain** (``can_dispatch``), and only the owning machine fires a record.

Receipts: ``schedule.arm | disarm | fire | queued | abandoned | pause | resume | ended | skipped``.

Pinned by ``tests/agent_runtime/work_store/test_serve_tick_scheduler.py``, ``test_schedule_tool.py`` and
``test_engine.py`` (the scheduled-run rows).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .. import chat_root_send_queue as send_queue
from . import receipts, schedule_store
from .default_brain import this_machine
from .reasons import Reason, WorkRefused
from .schedule_store import ScheduleRecord
from .scheduler import KEY, Action, Armed, Fire, PersonaPrompt, RunAssignment, RunTask, StartBatch, Trigger, TriggerKind

__layer__ = "lanes"
__all__ = ["ABANDON_AFTER", "DEFAULT_MAX_PARALLEL", "ORIGIN_KEY", "TICK_SECONDS", "ServeTickScheduler",
           "start_schedule_ticker"]

logger = logging.getLogger(__name__)

TICK_SECONDS = 60.0
DEFAULT_MAX_PARALLEL = 4
ABANDON_AFTER = timedelta(minutes=15)
#: The send-queue origin key a scheduled fire carries (the ``scheduled_turn`` lane reads it).
ORIGIN_KEY = send_queue.SCHEDULE_ORIGIN_KEY
_ONE_SHOT = frozenset({TriggerKind.AT, TriggerKind.WHEN_IDLE})
#: The kinds whose schedule fires again: a ``RunTask`` run of one leaves its task open when it ends DONE.
_REPEATING = frozenset({TriggerKind.EVERY, TriggerKind.CRON})


def _cron_next(trigger: Trigger, after: datetime) -> datetime:
    try:
        from croniter import croniter
    except ImportError as exc:  # upstream's own rule (cron/jobs.py::_ensure_croniter): no croniter, no CRON
        raise WorkRefused(Reason.SCHEDULE_INVALID, "a CRON trigger needs the croniter package") from exc
    try:
        local = after.astimezone(ZoneInfo(trigger.tz))
        return croniter(trigger.expr, local).get_next(datetime).astimezone(UTC)
    except (KeyError, ValueError) as exc:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"CRON {trigger.expr!r}: {exc}") from exc


#: Trigger kind -> its next fire after ``now`` (None: it never fires on the clock).
_NEXT_FIRE: dict[TriggerKind, Callable[[Trigger, datetime], datetime | None]] = {
    TriggerKind.MANUAL: lambda _t, _now: None,
    TriggerKind.AT: lambda t, _now: t.at.astimezone(UTC),
    TriggerKind.EVERY: lambda t, now: now + timedelta(minutes=t.minutes),
    TriggerKind.CRON: _cron_next,
    TriggerKind.WHEN_IDLE: lambda _t, _now: None,
}


def _root_idle(root: str) -> bool:
    """No turn holds the root's lease and nothing waits on it — the unresolved-turn count is zero."""

    from ..chat_root_send_runner import _root_is_idle

    return not send_queue.has_entries(root) and _root_is_idle(root)


def _in_flight() -> int:
    return len(send_queue.entries_from(ORIGIN_KEY))


def _workspace_automation(workspace_id: str) -> str:
    """The workspace's ``batch_automation``: the frontmatter of the default brain's ``batches/settings.md``
    (B2 owns the field, ``batch.manifest.automation_of`` reads it); ``off`` when it has none."""

    try:
        from ..batch.manifest import BrainManifestStore, automation_of

        return automation_of(BrainManifestStore().settings(workspace_id)).value
    except Exception:
        return "off"


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _per_fire(record: ScheduleRecord) -> Action:
    """The action one fire runs. A repeating ``RunAssignment`` fires under ``<armed request id>@<fire stamp>``,
    so each fire's claim, queued cmid and write-back replay by that fire's own id and a second fire after
    a release never converges on the first fire's replayed ops; a re-fire of the SAME due time (a crash
    before ``next_fire`` advanced) keeps the same stamp and so joins its own replay. A one-shot fires once
    under the armed id."""

    action = record.action
    if not isinstance(action, RunAssignment) or record.trigger.kind in _ONE_SHOT:
        return action
    stamp = _stamp(record.next_fire or record.armed_at)
    return RunAssignment(replace(action.assignment, request_id=f"{action.assignment.request_id}@{stamp}"))


class ServeTickScheduler:
    """The ``Scheduler`` contract over ``store/schedules/``, fired by :meth:`tick`."""

    def __init__(
        self,
        *,
        executor: Any = None,
        start_batch: Callable[[StartBatch], dict[str, Any]] | None = None,
        start_assignment: Callable[[Any, dict[str, Any]], Any] | None = None,
        start_task: Callable[..., Any] | None = None,
        can_dispatch: Callable[[], bool] = lambda: True,
        root_idle: Callable[[str], bool] = _root_idle,
        in_flight: Callable[[], int] = _in_flight,
        automation: Callable[[str], str] = _workspace_automation,
        machine: Callable[[], str] = this_machine,
        max_parallel: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._executor = executor
        self._start_batch = start_batch
        self._start_assignment = start_assignment
        self._start_task = start_task
        self._can_dispatch = can_dispatch
        self._root_idle = root_idle
        self._in_flight = in_flight
        self._automation = automation
        self._machine = machine
        self._max_parallel = None if max_parallel is None else max(0, int(max_parallel))
        self._clock = clock
        self._lock = threading.Lock()
        self._fires: dict[type, Callable[[ScheduleRecord, Any, str, dict[str, Any]], dict[str, Any]]] = {
            PersonaPrompt: self._fire_prompt, RunAssignment: self._fire_assignment, StartBatch: self._fire_batch,
            RunTask: self._fire_task,
        }

    # ── the contract ─────────────────────────────────────────────────────

    def arm(self, key: str, trigger: Trigger, action: Action, *, armed_by: str = "operator",
            replace: bool = False, ends: tuple[int | None, datetime | None] = (None, None),
            skip_while_running: bool | None = None) -> Armed:
        """Idempotent by key: a second arm JOINS the first and returns it unchanged — unless ``replace``,
        which overwrites the record under the key (an edit: new trigger, new action, ``next_fire`` from now)."""

        if not KEY.match(str(key or "")):
            raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r}")
        if isinstance(action, StartBatch) and self._automation(action.workspace_id) != "start":
            raise WorkRefused(Reason.AUTOMATION_OFF, f"workspace {action.workspace_id} does not start batches on a fire")
        with self._lock:
            existing = schedule_store.load_one(key)
            replaced = existing is not None and replace
            # MUTATION: drop ``or replaced`` and test_serve_tick_scheduler's "replace overwrites" reddens.
            if existing is None or replaced:
                now = self._clock()
                if not replaced:
                    schedule_store.remove(key)  # a result file a removed schedule's late settle left behind
                skip = isinstance(action, RunTask) and skip_while_running is not False
                existing = ScheduleRecord(key, trigger, action, _NEXT_FIRE[trigger.kind](trigger, now), now,
                                          owner_machine=self._machine(), armed_by=armed_by,
                                          ends_after_fires=ends[0], ends_until=ends[1], skip_while_running=skip,
                                          fires=existing.fires if replaced else 0)
                schedule_store.save(existing)
                joined = False
            else:
                joined = True
        receipts.emit("schedule.arm", key=key, trigger=existing.trigger.kind.value, next_fire=existing.next_fire,
                      action=type(existing.action).__name__, joined=joined, replaced=replaced,
                      armed_by=existing.armed_by)
        return existing.armed()

    def disarm(self, key: str) -> bool:
        with self._lock:
            gone = schedule_store.remove(key)
        receipts.emit("schedule.disarm", key=key, disarmed=gone)
        return gone

    def set_enabled(self, key: str, enabled: bool) -> ScheduleRecord:
        """Pause (``enabled=False``) or resume the schedule under ``key``; ``schedule_not_found`` for none.

        A resume counts from NOW: ``next_fire`` is recomputed (a paused stretch is never caught up), and a
        ``WHEN_IDLE`` schedule's 15-minute give-up starts over. Idempotent: the same state is returned as is.
        """

        with self._lock:
            record = schedule_store.load_one(key)
            if record is None:
                raise WorkRefused(Reason.SCHEDULE_NOT_FOUND, key)
            if record.enabled != enabled:
                changes: dict[str, Any] = {"enabled": enabled, "held_since": None, "idle_ticks": 0}
                if enabled:
                    now = self._clock()
                    # MUTATION: keep the stored next_fire and test_serve_tick_scheduler's "resume counts
                    # from now" reddens (the paused fires all run at once).
                    changes["next_fire"] = _NEXT_FIRE[record.trigger.kind](record.trigger, now)
                    if record.trigger.kind is TriggerKind.WHEN_IDLE:
                        changes["armed_at"] = now
                record = record.evolve(**changes)
                schedule_store.save(record)
        receipts.emit("schedule.resume" if enabled else "schedule.pause", key=key, next_fire=record.next_fire)
        return record

    def armed(self) -> list[Armed]:
        return [record.armed() for record in schedule_store.load_all()]

    def records(self) -> list[ScheduleRecord]:
        return schedule_store.load_all()

    def due(self, now: datetime) -> list[Fire]:
        """Pure: the clock triggers of this machine due at ``now`` (WHEN_IDLE is decided by the tick's probe)."""

        mine = self._mine()
        return [Fire(r.key, r.action, r.next_fire) for r in schedule_store.load_all()
                if r.enabled and r.owner_machine == mine and r.next_fire is not None and r.next_fire <= now]

    def tick(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Fire what is due, advance ``next_fire``, persist; one receipt per fire, hold or give-up."""

        now = now or self._clock()
        if not self._can_dispatch():
            return []
        with self._lock:
            mine = self._mine()
            out: list[dict[str, Any]] = []
            due: list[ScheduleRecord] = []
            for record in schedule_store.load_all():
                if not record.enabled or record.owner_machine != mine:
                    continue
                if self._ended(record, record.next_fire, now):
                    out.append(self._end(record))
                    continue
                if record.trigger.kind is TriggerKind.WHEN_IDLE:
                    record = self._idle_step(record, now, out)
                if record is not None and (record.next_fire is not None and record.next_fire <= now
                                           or self._idle_ripe(record)):
                    due.append(record)
            flying, cap = self._in_flight(), self._cap()
            for record in sorted(due, key=lambda r: (r.next_fire or now, r.key)):
                if cap and flying >= cap:
                    out += self._hold(record, now, cap)
                    continue
                out += self._fire(record, now)
                flying += 1
            return out

    # ── the tick's steps ─────────────────────────────────────────────────

    def _cap(self) -> int:
        """The constructor's ``max_parallel`` when given, else the root-config knob, read now."""

        if self._max_parallel is not None:
            return self._max_parallel
        from ..config import scheduler_max_parallel

        return scheduler_max_parallel(DEFAULT_MAX_PARALLEL)

    def _mine(self) -> str:
        try:
            return self._machine()
        except WorkRefused:
            return "\0unidentified"

    @staticmethod
    def _idle_ripe(record: ScheduleRecord) -> bool:
        return record.trigger.kind is TriggerKind.WHEN_IDLE and record.idle_ticks >= record.trigger.settle_ticks

    def _idle_step(self, record: ScheduleRecord, now: datetime, out: list[dict[str, Any]]) -> ScheduleRecord | None:
        if self._idle_ripe(record):
            return record  # ripe on an earlier tick and held by the cap: fire it, do not recount
        if now - record.armed_at > ABANDON_AFTER:
            schedule_store.remove(record.key)
            out.append(receipts.emit("schedule.abandoned", key=record.key, trigger=record.trigger.kind.value,
                                     root=record.trigger.root, action=type(record.action).__name__,
                                     waited_s=int((now - record.armed_at).total_seconds())))
            return None
        record = record.evolve(idle_ticks=record.idle_ticks + 1 if self._root_idle(record.trigger.root) else 0)
        schedule_store.save(record)
        return record

    def _hold(self, record: ScheduleRecord, now: datetime, cap: int) -> list[dict[str, Any]]:
        if record.held_since is not None:
            return []
        schedule_store.save(record.evolve(held_since=now))
        return [receipts.emit("schedule.queued", key=record.key, trigger=record.trigger.kind.value,
                              next_fire=record.next_fire, action=type(record.action).__name__,
                              reason=Reason.CAP_REACHED.value, max_parallel=cap)]

    @staticmethod
    def _ended(record: ScheduleRecord, next_fire: datetime | None, now: datetime) -> bool:
        """The schedule has run its course: its count is reached, or what it would fire next is past its date."""

        if record.ends_after_fires is not None and record.fires >= record.ends_after_fires:
            return True
        return record.ends_until is not None and (next_fire or now) > record.ends_until

    @staticmethod
    def _end(record: ScheduleRecord) -> dict[str, Any]:
        schedule_store.remove(record.key)
        return receipts.emit("schedule.ended", key=record.key, trigger=record.trigger.kind.value,
                             action=type(record.action).__name__, fires=record.fires,
                             after_fires=record.ends_after_fires, until=record.ends_until)

    def _fire(self, record: ScheduleRecord, now: datetime) -> list[dict[str, Any]]:
        fire_id = f"{record.key}:{_stamp(record.next_fire or record.armed_at)}"
        origin = {ORIGIN_KEY: record.key, "fire": fire_id, "fired_at": now.isoformat(timespec="seconds")}
        waited = int((now - record.held_since).total_seconds()) if record.held_since else 0
        try:
            result, refused = self._fires[type(record.action)](record, _per_fire(record), fire_id, origin), None
        except WorkRefused as refusal:
            result, refused = {}, refusal
        if refused is not None and refused.reason is Reason.ROW_GONE and isinstance(record.action, RunTask):
            # The task was closed or deleted: nothing is left to run, on this fire or any later one.
            schedule_store.remove(record.key)
            return [receipts.emit("schedule.abandoned", key=record.key, trigger=record.trigger.kind.value,
                                  action=type(record.action).__name__, fire=fire_id,
                                  reason=refused.reason.value, detail=refused.detail)]
        nxt = None if record.trigger.kind in _ONE_SHOT else _NEXT_FIRE[record.trigger.kind](record.trigger, now)
        live_run = refused.data.get("live_run") if refused is not None else None
        skipped = bool(live_run) and record.skip_while_running
        # MUTATION: count every fire (``fires + 1`` unconditionally) and test_serve_tick_scheduler's "a refused
        # fire counts nothing" reddens.
        after = record.evolve(next_fire=nxt, last_fire=now, held_since=None, idle_ticks=0,
                              fires=record.fires + (1 if refused is None else 0))
        if skipped:
            schedule_store.write_result(record.key, "skipped", at=now, run_id=str(live_run),
                                        detail="the task's last run was still going")
        elif refused is not None:
            schedule_store.write_result(record.key, "refused", at=now,
                                        detail=f"{refused.reason.value}: {refused.detail}")
        if skipped:
            receipt = receipts.emit("schedule.skipped", key=record.key, trigger=record.trigger.kind.value,
                                    next_fire=nxt, action=type(record.action).__name__, fire=fire_id,
                                    run_id=str(live_run))
        else:
            receipt = receipts.emit("schedule.fire", key=record.key, trigger=record.trigger.kind.value, next_fire=nxt,
                                    action=type(record.action).__name__, fire=fire_id, waited_s=waited, **result,
                                    refused=None if refused is None else refused.reason.value,
                                    detail=None if refused is None else refused.detail)
        if nxt is None:
            schedule_store.remove(record.key)
            return [receipt]
        if self._ended(after, nxt, now):
            return [receipt, self._end(after)]
        schedule_store.save(after)
        return [receipt]

    # ── the fires, one per Action type ───────────────────────────────────

    def _turns(self) -> Any:
        if self._executor is None:
            from .persona_turn import PersonaTurnExecutor

            self._executor = PersonaTurnExecutor(draining=lambda: not self._can_dispatch())
        return self._executor

    def _fire_prompt(self, _record: ScheduleRecord, action: PersonaPrompt, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        run = self._turns().queue_prompt(action.persona_instance_id, action.prompt, request_id=fire_id,
                                         origin={"owner": None, "gateway": False, **origin})
        return {"run_id": run.run_id}

    def _fire_assignment(self, _record: ScheduleRecord, action: RunAssignment, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        if self._start_assignment is None:
            raise WorkRefused(Reason.DOOR_UNBOUND, "no Work engine is bound to this serve")
        return {"run_id": self._start_assignment(action.assignment, origin).run_id}

    def _fire_task(self, record: ScheduleRecord, action: RunTask, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        if self._start_task is None:
            raise WorkRefused(Reason.DOOR_UNBOUND, "no Work engine is bound to this serve")
        request_id = f"{record.key}@{_stamp(record.next_fire or record.armed_at)}"
        run = self._start_task(action, request_id, origin, repeats=record.trigger.kind in _REPEATING)
        return {"run_id": run.run_id, "request_id": request_id}

    def _fire_batch(self, _record: ScheduleRecord, action: StartBatch, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        if self._start_batch is None:
            raise WorkRefused(Reason.DOOR_UNBOUND, "no batch dispatcher is bound to this serve")
        return dict(self._start_batch(action) or {})


def start_schedule_ticker(
    *,
    stop_event: threading.Event,
    scheduler: ServeTickScheduler,
    interval_s: float = TICK_SECONDS,
    home: Any = None,
) -> threading.Thread:
    """Tick ``scheduler`` on a daemon thread until ``stop_event``; a failed tick is logged, never fatal.

    ``home`` is the serve's request home, bound around every tick (``engine.home_scope``) so the
    schedules and the send queue are read where the queued-send runner reads them.
    """

    from .engine import home_scope

    def _loop() -> None:
        while not stop_event.wait(interval_s):
            try:
                with home_scope(home):
                    scheduler.tick()
            except Exception:
                logger.warning("schedule tick failed", exc_info=True)

    thread = threading.Thread(target=_loop, name="harness-serve-scheduler", daemon=True)
    thread.start()
    return thread
