"""Armed schedules on disk — ``store/schedules/<key>.json``, one file per key (dispatcher plan §2.3, §3.4).

The files ARE the scheduler's state: ``ServeTickScheduler`` re-reads them on every tick and every
verb, so the RPC, the ``schedule_manage`` tool and the serve's ticker share no memory and a restart
loses nothing. A record carries the contract's ``Armed`` fields plus the tick's own bookkeeping
(``armed_at`` for the ``WHEN_IDLE`` give-up, ``idle_ticks``, ``held_since`` for an over-cap fire's
``waited_s``). Its JSON is the wire ``runtime.schedule.list`` answers and the Launcher mirrors.

A record also carries how it ends (``ends_after_fires`` / ``ends_until``, the wire's ``ends``), how many
fires started a run (``fires``) and ``skip_while_running`` (``RT-SCHEDULE-PAUSE-END-AND-LAST-RESULT``).

``last_result`` — how the schedule's last fire ended — is its OWN file, ``store/schedules/results/<key>.json``,
because two writers own it: the scheduler (a ``skipped`` or ``refused`` fire) and the Work engine (the fire's
run settling, minutes later, on another thread). Each write replaces the whole value, so neither can lose
the other's edit of the record, and the engine never takes the scheduler's lock. :func:`record_wire` is the
record with its ``last_result`` — the wire the verbs answer.

An unreadable file is skipped (and logged), never fired; ``save`` writes tmp + rename.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from .executor import Assignment, Brief, GoalMode
from .grammar import RowRef
from .reasons import Reason, WorkRefused
from .scheduler import KEY, Action, Armed, PersonaPrompt, RunAssignment, RunTask, StartBatch, Trigger, TriggerKind

__layer__ = "lanes"
__all__ = ["RESULT_VERDICTS", "SCHEMA_VERSION", "ScheduleRecord", "action_from_wire", "action_wire", "ends_from_wire",
           "last_result", "load_all", "load_one", "record_wire", "remove", "save", "trigger_from_wire", "trigger_wire",
           "write_result"]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


#: ``last_result.verdict``: a run's four endings, plus the two a fire that started no run can have.
RESULT_VERDICTS: frozenset[str] = frozenset({"done", "blocked", "stopped", "failed", "skipped", "refused"})
_RESULT_DETAIL = 500


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _when(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def trigger_wire(trigger: Trigger) -> dict[str, Any]:
    return {"kind": trigger.kind.value, "at": _stamp(trigger.at), "minutes": trigger.minutes, "expr": trigger.expr,
            "tz": trigger.tz, "root": trigger.root, "settle_ticks": trigger.settle_ticks}


def trigger_from_wire(raw: Mapping[str, Any]) -> Trigger:
    """A trigger from its wire; a malformed one refuses ``schedule_invalid`` (``Trigger.__post_init__``)."""

    try:
        return Trigger(TriggerKind(str(raw.get("kind") or "manual")), at=_when(raw.get("at")),
                       minutes=None if raw.get("minutes") is None else int(raw["minutes"]),
                       expr=" ".join(str(raw.get("expr") or "").split()), tz=str(raw.get("tz") or "UTC"),
                       root=str(raw.get("root") or ""), settle_ticks=int(raw.get("settle_ticks") or 2))
    except WorkRefused:
        raise
    except (TypeError, ValueError) as exc:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"trigger: {exc}") from exc


def _assignment_wire(action: RunAssignment) -> dict[str, Any]:
    wire = asdict(action.assignment)
    wire["rows"] = [ref.items() for ref in action.assignment.rows]
    wire["goal_mode"] = action.assignment.goal_mode.value
    return {"type": "run_assignment", "assignment": wire}


def _assignment_from_wire(raw: Mapping[str, Any]) -> RunAssignment:
    a = dict(raw["assignment"])
    brief = dict(a["brief"])
    brief = Brief(**{**brief, **{name: tuple(brief.get(name) or ()) for name in ("inputs", "constraints", "tests")}})
    return RunAssignment(Assignment(
        rows=tuple(RowRef(*map(str, row)) for row in a["rows"]), persona_instance_id=str(a["persona_instance_id"]),
        brief=brief, request_id=str(a["request_id"]), heavy=bool(a.get("heavy")),
        goal_mode=GoalMode(a.get("goal_mode") or "none"), goal_gates=bool(a.get("goal_gates", True))))


def _prompt_from_wire(raw: Mapping[str, Any]) -> PersonaPrompt:
    instance, prompt = str(raw.get("persona_instance_id") or "").strip(), str(raw.get("prompt") or "")
    if not instance or not prompt.strip():
        raise ValueError("a persona_prompt needs a persona_instance_id and a prompt")
    return PersonaPrompt(instance, prompt)


_TASK_FIELDS = ("workspace_id", "slot", "task_id", "persona_instance_id")


def _task_wire(action: RunTask) -> dict[str, Any]:
    return {"type": "run_task", **{name: getattr(action, name) for name in _TASK_FIELDS},
            "goal_mode": action.goal_mode.value}


def _task_from_wire(raw: Mapping[str, Any]) -> RunTask:
    """``{type: run_task, workspace_id, slot, task_id, persona_instance_id, goal_mode}``; every id is required."""

    fields = {name: str(raw.get(name) or "").strip() for name in _TASK_FIELDS}
    missing = [name for name, value in fields.items() if not value]
    if missing:
        raise ValueError(f"a run_task needs {', '.join(missing)}")
    return RunTask(**fields, goal_mode=GoalMode(raw.get("goal_mode") or "none"))


#: Action type -> (wire word, to wire); the wire word -> from wire. An Action is never a script (RT-D1).
_ACTION_TO_WIRE: dict[type, Callable[[Any], dict[str, Any]]] = {
    StartBatch: lambda a: {"type": "start_batch", "workspace_id": a.workspace_id, "plan_id": a.plan_id},
    PersonaPrompt: lambda a: {"type": "persona_prompt", "persona_instance_id": a.persona_instance_id,
                              "prompt": a.prompt},
    RunAssignment: _assignment_wire,
    RunTask: _task_wire,
}
_ACTION_FROM_WIRE: dict[str, Callable[[Mapping[str, Any]], Action]] = {
    "start_batch": lambda raw: StartBatch(str(raw["workspace_id"]), str(raw["plan_id"])),
    "persona_prompt": _prompt_from_wire,
    "run_assignment": _assignment_from_wire,
    "run_task": _task_from_wire,
}


def action_wire(action: Action) -> dict[str, Any]:
    return _ACTION_TO_WIRE[type(action)](action)


def action_from_wire(raw: Mapping[str, Any]) -> Action:
    build = _ACTION_FROM_WIRE.get(str(raw.get("type") or "")) if isinstance(raw, Mapping) else None
    if build is None:
        raise WorkRefused(Reason.SCHEDULE_INVALID, "an action is start_batch, persona_prompt, run_assignment or run_task")
    try:
        return build(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"action: {exc}") from exc


def ends_from_wire(raw: Any) -> tuple[int | None, datetime | None]:
    """``ends: {after_fires: <int >= 1> | null, until: <aware ISO time> | null}`` as ``(after_fires, until)``.

    Absent or null is "never ends"; anything else malformed refuses ``schedule_invalid``.
    """

    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        raise WorkRefused(Reason.SCHEDULE_INVALID, "ends is {after_fires, until}")
    after, until = raw.get("after_fires"), raw.get("until")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int) or after < 1):
        raise WorkRefused(Reason.SCHEDULE_INVALID, "ends.after_fires is a whole number >= 1")
    try:
        when = _when(until)
    except (TypeError, ValueError) as exc:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"ends.until: {exc}") from exc
    if when is not None and when.utcoffset() is None:
        raise WorkRefused(Reason.SCHEDULE_INVALID, "ends.until needs an aware time")
    return after, when


@dataclass(frozen=True)
class ScheduleRecord:
    """One armed schedule, as stored: the contract's ``Armed`` plus the tick's bookkeeping."""

    key: str
    trigger: Trigger
    action: Action
    next_fire: datetime | None
    armed_at: datetime
    last_fire: datetime | None = None
    enabled: bool = True
    owner_machine: str = ""
    armed_by: str = ""
    idle_ticks: int = 0
    held_since: datetime | None = None
    #: The schedule is removed (``schedule.ended``) once this many fires started a run, or past this time.
    ends_after_fires: int | None = None
    ends_until: datetime | None = None
    #: Fires that started a run (a refused or skipped fire counts nothing).
    fires: int = 0
    #: A ``RunTask`` fire that finds the task's last run still live advances and records ``skipped``.
    skip_while_running: bool = False

    def armed(self) -> Armed:
        return Armed(self.key, self.trigger, self.action, self.next_fire, self.last_fire, self.enabled,
                     self.owner_machine)

    def evolve(self, **changes: Any) -> ScheduleRecord:
        return replace(self, **changes)

    def wire(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "key": self.key, "trigger": trigger_wire(self.trigger),
                "action": action_wire(self.action), "next_fire": _stamp(self.next_fire),
                "last_fire": _stamp(self.last_fire), "enabled": self.enabled, "owner_machine": self.owner_machine,
                "armed_at": _stamp(self.armed_at), "armed_by": self.armed_by, "idle_ticks": self.idle_ticks,
                "held_since": _stamp(self.held_since),
                "ends": {"after_fires": self.ends_after_fires, "until": _stamp(self.ends_until)},
                "fires": self.fires, "skip_while_running": self.skip_while_running}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ScheduleRecord:
        return cls(key=str(raw["key"]), trigger=trigger_from_wire(raw["trigger"]),
                   action=action_from_wire(raw["action"]), next_fire=_when(raw.get("next_fire")),
                   armed_at=_when(raw["armed_at"]), last_fire=_when(raw.get("last_fire")),
                   enabled=bool(raw.get("enabled", True)), owner_machine=str(raw.get("owner_machine") or ""),
                   armed_by=str(raw.get("armed_by") or ""), idle_ticks=int(raw.get("idle_ticks") or 0),
                   held_since=_when(raw.get("held_since")),
                   **dict(zip(("ends_after_fires", "ends_until"), ends_from_wire(raw.get("ends")), strict=True)),
                   fires=int(raw.get("fires") or 0), skip_while_running=bool(raw.get("skip_while_running", False)))


def _path(key: str) -> Path:
    """The key's file; ``:`` and friends are not filename-safe on Windows, so the name is the path token."""

    if not KEY.match(str(key or "")):
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r}")
    return paths.schedules_dir() / f"{paths.safe_path_token(key)}.json"


def save(record: ScheduleRecord) -> None:
    path = _path(record.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, record.wire())


def _read_record(path: Path) -> ScheduleRecord | None:
    try:
        return ScheduleRecord.from_wire(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, KeyError, TypeError, ValueError):
        logger.warning("schedule %s is unreadable; it never fires until re-armed", path.name, exc_info=True)
        return None


def load_one(key: str) -> ScheduleRecord | None:
    """The record armed under ``key``; a different key on the same file name refuses ``schedule_invalid``."""

    record = _read_record(_path(key))
    if record is not None and record.key != key:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r} collides with {record.key!r}")
    return record


def load_all() -> list[ScheduleRecord]:
    """Every readable record, by key."""

    base = paths.schedules_dir()
    if not base.is_dir():
        return []
    records = [record for record in map(_read_record, sorted(base.glob("*.json"))) if record is not None]
    return sorted(records, key=lambda record: record.key)


def remove(key: str) -> bool:
    """Drop the schedule and its ``last_result``; False when nothing was armed under ``key``."""

    try:
        _result_path(key).unlink()
    except FileNotFoundError:
        pass
    try:
        _path(key).unlink()
    except FileNotFoundError:
        return False
    return True


# ── last_result: its own file per key ──────────────────────────────────────


def _result_path(key: str) -> Path:
    return _path(key).parent / "results" / _path(key).name


def write_result(key: str, verdict: str, *, at: datetime, detail: str = "", run_id: str | None = None) -> bool:
    """Record how ``key``'s last fire ended; False (nothing written) when no schedule is armed under it.

    ``verdict`` is one of :data:`RESULT_VERDICTS`. The whole value is replaced — the last writer is the
    last result.
    """

    if verdict not in RESULT_VERDICTS:
        raise ValueError(f"last_result verdict {verdict!r}")
    if not _path(key).is_file():
        return False
    path = _result_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"verdict": verdict, "at": _stamp(at),
                             "detail": " ".join(str(detail or "").split())[:_RESULT_DETAIL], "run_id": run_id or None})
    return True


def last_result(key: str) -> dict[str, Any] | None:
    """``{verdict, at, detail, run_id}`` of ``key``'s last fire, or None (never fired, or unreadable)."""

    try:
        raw = json.loads(_result_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("verdict") not in RESULT_VERDICTS:
        return None
    return {name: raw.get(name) for name in ("verdict", "at", "detail", "run_id")}


def record_wire(record: ScheduleRecord) -> dict[str, Any]:
    """The record as the verbs answer it: its stored wire plus ``last_result``."""

    return {**record.wire(), "last_result": last_result(record.key)}
