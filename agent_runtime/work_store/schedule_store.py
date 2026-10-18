"""Armed schedules on disk — ``store/schedules/<key>.json``, one file per key (dispatcher plan §2.3, §3.4).

The files ARE the scheduler's state: ``ServeTickScheduler`` re-reads them on every tick and every
verb, so the RPC, the ``schedule_manage`` tool and the serve's ticker share no memory and a restart
loses nothing. A record carries the contract's ``Armed`` fields plus the tick's own bookkeeping
(``armed_at`` for the ``WHEN_IDLE`` give-up, ``idle_ticks``, ``held_since`` for an over-cap fire's
``waited_s``). Its JSON is the wire ``runtime.schedule.list`` answers and the Launcher mirrors.

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
from .scheduler import KEY, Action, Armed, PersonaPrompt, RunAssignment, StartBatch, Trigger, TriggerKind

__layer__ = "lanes"
__all__ = ["SCHEMA_VERSION", "ScheduleRecord", "action_from_wire", "action_wire", "load_all", "load_one",
           "remove", "save", "trigger_from_wire", "trigger_wire"]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


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
    wire["rows"] = [[ref.slot, ref.note, ref.id] for ref in action.assignment.rows]
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


#: Action type -> (wire word, to wire); the wire word -> from wire. An Action is never a script (RT-D1).
_ACTION_TO_WIRE: dict[type, Callable[[Any], dict[str, Any]]] = {
    StartBatch: lambda a: {"type": "start_batch", "workspace_id": a.workspace_id, "plan_id": a.plan_id},
    PersonaPrompt: lambda a: {"type": "persona_prompt", "persona_instance_id": a.persona_instance_id,
                              "prompt": a.prompt},
    RunAssignment: _assignment_wire,
}
_ACTION_FROM_WIRE: dict[str, Callable[[Mapping[str, Any]], Action]] = {
    "start_batch": lambda raw: StartBatch(str(raw["workspace_id"]), str(raw["plan_id"])),
    "persona_prompt": _prompt_from_wire,
    "run_assignment": _assignment_from_wire,
}


def action_wire(action: Action) -> dict[str, Any]:
    return _ACTION_TO_WIRE[type(action)](action)


def action_from_wire(raw: Mapping[str, Any]) -> Action:
    build = _ACTION_FROM_WIRE.get(str(raw.get("type") or "")) if isinstance(raw, Mapping) else None
    if build is None:
        raise WorkRefused(Reason.SCHEDULE_INVALID, "an action is start_batch, persona_prompt or run_assignment")
    try:
        return build(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"action: {exc}") from exc


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
                "held_since": _stamp(self.held_since)}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ScheduleRecord:
        return cls(key=str(raw["key"]), trigger=trigger_from_wire(raw["trigger"]),
                   action=action_from_wire(raw["action"]), next_fire=_when(raw.get("next_fire")),
                   armed_at=_when(raw["armed_at"]), last_fire=_when(raw.get("last_fire")),
                   enabled=bool(raw.get("enabled", True)), owner_machine=str(raw.get("owner_machine") or ""),
                   armed_by=str(raw.get("armed_by") or ""), idle_ticks=int(raw.get("idle_ticks") or 0),
                   held_since=_when(raw.get("held_since")))


def _path(key: str) -> Path:
    """The key's file; ``:`` and friends are not filename-safe on Windows, so the name is the path token."""

    if not KEY.match(str(key or "")):
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r}")
    return paths.schedules_dir() / f"{paths.safe_path_token(key)}.json"


def save(record: ScheduleRecord) -> None:
    path = _path(record.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, record.wire())


def _read(path: Path) -> ScheduleRecord | None:
    try:
        return ScheduleRecord.from_wire(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, KeyError, TypeError, ValueError):
        logger.warning("schedule %s is unreadable; it never fires until re-armed", path.name, exc_info=True)
        return None


def load_one(key: str) -> ScheduleRecord | None:
    """The record armed under ``key``; a different key on the same file name refuses ``schedule_invalid``."""

    record = _read(_path(key))
    if record is not None and record.key != key:
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r} collides with {record.key!r}")
    return record


def load_all() -> list[ScheduleRecord]:
    """Every readable record, by key."""

    base = paths.schedules_dir()
    if not base.is_dir():
        return []
    records = [record for record in map(_read, sorted(base.glob("*.json"))) if record is not None]
    return sorted(records, key=lambda record: record.key)


def remove(key: str) -> bool:
    try:
        _path(key).unlink()
    except FileNotFoundError:
        return False
    return True
