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
* **The cap.** At most ``max_parallel`` scheduled turns in flight — the root config's
  ``agent_runtime.scheduler.max_parallel``, read each tick (default 4, ``0`` unlimited); a due fire
  over the cap stays due, logs ``schedule.queued`` once, and its ``schedule.fire`` carries ``waited_s``
  (RT-D5 by construction).
* **WHEN_IDLE** is the Launcher's ``AfterReplyScheduler`` rule: the root reads idle (no turn holds its lease,
  nothing queued on it) on ``settle_ticks`` consecutive ticks, else it gives up after 15 minutes
  (``schedule.abandoned``).
* **Never during a drain** (``can_dispatch``), and only the owning machine fires a record.

Receipts: ``schedule.arm | disarm | fire | queued | abandoned``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .. import chat_root_send_queue as send_queue
from . import receipts, schedule_store
from .default_brain import this_machine
from .reasons import Reason, WorkRefused
from .schedule_store import ScheduleRecord
from .scheduler import KEY, Action, Armed, Fire, PersonaPrompt, RunAssignment, StartBatch, Trigger, TriggerKind

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


class ServeTickScheduler:
    """The ``Scheduler`` contract over ``store/schedules/``, fired by :meth:`tick`."""

    def __init__(
        self,
        *,
        executor: Any = None,
        start_batch: Callable[[StartBatch], dict[str, Any]] | None = None,
        start_assignment: Callable[[Any, dict[str, Any]], Any] | None = None,
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
        self._can_dispatch = can_dispatch
        self._root_idle = root_idle
        self._in_flight = in_flight
        self._automation = automation
        self._machine = machine
        self._max_parallel = None if max_parallel is None else max(0, int(max_parallel))
        self._clock = clock
        self._lock = threading.Lock()
        self._fires: dict[type, Callable[[Any, str, dict[str, Any]], dict[str, Any]]] = {
            PersonaPrompt: self._fire_prompt, RunAssignment: self._fire_assignment, StartBatch: self._fire_batch,
        }

    # ── the contract ─────────────────────────────────────────────────────

    def arm(self, key: str, trigger: Trigger, action: Action, *, armed_by: str = "operator") -> Armed:
        """Idempotent by key: a second arm JOINS the first and returns it unchanged."""

        if not KEY.match(str(key or "")):
            raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r}")
        if isinstance(action, StartBatch) and self._automation(action.workspace_id) != "start":
            raise WorkRefused(Reason.AUTOMATION_OFF, f"workspace {action.workspace_id} does not start batches on a fire")
        with self._lock:
            existing = schedule_store.load_one(key)
            if existing is None:
                now = self._clock()
                existing = ScheduleRecord(key, trigger, action, _NEXT_FIRE[trigger.kind](trigger, now), now,
                                          owner_machine=self._machine(), armed_by=armed_by)
                schedule_store.save(existing)
                joined = False
            else:
                joined = True
        receipts.emit("schedule.arm", key=key, trigger=existing.trigger.kind.value, next_fire=existing.next_fire,
                      action=type(existing.action).__name__, joined=joined, armed_by=existing.armed_by)
        return existing.armed()

    def disarm(self, key: str) -> bool:
        with self._lock:
            gone = schedule_store.remove(key)
        receipts.emit("schedule.disarm", key=key, disarmed=gone)
        return gone

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
                out.append(self._fire(record, now))
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

    def _fire(self, record: ScheduleRecord, now: datetime) -> dict[str, Any]:
        fire_id = f"{record.key}:{_stamp(record.next_fire or record.armed_at)}"
        origin = {ORIGIN_KEY: record.key, "fire": fire_id, "fired_at": now.isoformat(timespec="seconds")}
        waited = int((now - record.held_since).total_seconds()) if record.held_since else 0
        try:
            result, refused = self._fires[type(record.action)](record.action, fire_id, origin), None
        except WorkRefused as refusal:
            result, refused = {}, refusal
        nxt = None if record.trigger.kind in _ONE_SHOT else _NEXT_FIRE[record.trigger.kind](record.trigger, now)
        if nxt is None:
            schedule_store.remove(record.key)
        else:
            schedule_store.save(record.evolve(next_fire=nxt, last_fire=now, held_since=None, idle_ticks=0))
        return receipts.emit("schedule.fire", key=record.key, trigger=record.trigger.kind.value, next_fire=nxt,
                             action=type(record.action).__name__, fire=fire_id, waited_s=waited, **result,
                             refused=None if refused is None else refused.reason.value,
                             detail=None if refused is None else refused.detail)

    # ── the fires, one per Action type ───────────────────────────────────

    def _turns(self) -> Any:
        if self._executor is None:
            from .persona_turn import PersonaTurnExecutor

            self._executor = PersonaTurnExecutor(draining=lambda: not self._can_dispatch())
        return self._executor

    def _fire_prompt(self, action: PersonaPrompt, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        run = self._turns().queue_prompt(action.persona_instance_id, action.prompt, request_id=fire_id,
                                         origin={"owner": None, "gateway": False, **origin})
        return {"run_id": run.run_id}

    def _fire_assignment(self, action: RunAssignment, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
        if self._start_assignment is None:
            raise WorkRefused(Reason.DOOR_UNBOUND, "no Work engine is bound to this serve")
        return {"run_id": self._start_assignment(action.assignment, origin).run_id}

    def _fire_batch(self, action: StartBatch, fire_id: str, origin: dict[str, Any]) -> dict[str, Any]:
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
