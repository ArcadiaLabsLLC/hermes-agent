"""The SCHEDULER contract — when something fires (dispatcher plan §2.3, stage B1).

A schedule is ``(key, Trigger, Action)``. The trigger vocabulary ``AT | EVERY | CRON`` is upstream's
``cron/jobs.py::parse_schedule`` kinds ``once | interval | cron`` one-to-one; ``WHEN_IDLE`` is the
Launcher's ``AfterReplyScheduler`` rule; ``MANUAL`` is the default. An ``Action`` is one of three
typed records and never a script (RT-D1 by construction).

:class:`ManualScheduler` is the one production implementation until B4's ``ServeTickScheduler``:
"manual by default" — it arms only ``MANUAL`` triggers, ``due`` and ``tick`` never fire, and the only
fire is the operator's ``runtime.batch.start``. Every method returns a value or raises
``WorkRefused(reason)``; ``arm`` and ``disarm`` log one ``schedule.arm | schedule.disarm`` receipt.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import receipts
from .executor import Assignment
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = [
    "REFUSALS",
    "Action",
    "Armed",
    "Fire",
    "ManualScheduler",
    "PersonaPrompt",
    "RunAssignment",
    "Scheduler",
    "StartBatch",
    "Trigger",
    "TriggerKind",
]

#: Every refusal a SCHEDULER may raise (plan §2.3); ``not_built`` is the manual scheduler's timed-trigger answer.
REFUSALS: frozenset[Reason] = frozenset({
    Reason.SCHEDULE_INVALID, Reason.AUTOMATION_OFF, Reason.CAP_REACHED, Reason.DRAIN_BEGUN,
    Reason.NOT_OWNER_MACHINE, Reason.NOT_BUILT,
})

KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_CRON_FIELDS = (5, 6)


class TriggerKind(StrEnum):
    MANUAL = "manual"
    AT = "at"
    EVERY = "every"
    CRON = "cron"
    WHEN_IDLE = "when_idle"


def _zone_defect(tz: str) -> str | None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return f"unknown time zone {tz!r}"
    return None


def _at_defect(t: Trigger) -> str | None:
    return None if t.at is not None and t.at.utcoffset() is not None else "AT needs an aware datetime"


def _every_defect(t: Trigger) -> str | None:
    return None if isinstance(t.minutes, int) and t.minutes >= 1 else "EVERY needs minutes >= 1"


def _cron_defect(t: Trigger) -> str | None:
    if len(t.expr.split()) not in _CRON_FIELDS:
        return f"CRON needs a 5- or 6-field expression, got {t.expr!r}"
    return _zone_defect(t.tz)


def _idle_defect(t: Trigger) -> str | None:
    return None if t.root.strip() and t.settle_ticks >= 1 else "WHEN_IDLE needs a root and settle_ticks >= 1"


#: What each trigger kind requires of its fields; None when the trigger is well formed.
_DEFECTS: dict[TriggerKind, Callable[[Trigger], str | None]] = {
    TriggerKind.MANUAL: lambda _t: None,
    TriggerKind.AT: _at_defect,
    TriggerKind.EVERY: _every_defect,
    TriggerKind.CRON: _cron_defect,
    TriggerKind.WHEN_IDLE: _idle_defect,
}


@dataclass(frozen=True)
class Trigger:
    """When a schedule fires; a malformed trigger cannot be built (``schedule_invalid``)."""

    kind: TriggerKind = TriggerKind.MANUAL
    at: datetime | None = None
    minutes: int | None = None
    expr: str = ""
    tz: str = "UTC"
    root: str = ""
    settle_ticks: int = 2

    def __post_init__(self) -> None:
        defect = _DEFECTS[TriggerKind(self.kind)](self)
        if defect is not None:
            raise WorkRefused(Reason.SCHEDULE_INVALID, defect)

    @classmethod
    def manual(cls) -> Trigger:
        return cls(TriggerKind.MANUAL)

    @classmethod
    def at_utc(cls, when: datetime) -> Trigger:
        return cls(TriggerKind.AT, at=when)

    @classmethod
    def every(cls, minutes: int) -> Trigger:
        return cls(TriggerKind.EVERY, minutes=minutes)

    @classmethod
    def cron(cls, expr: str, tz: str = "UTC") -> Trigger:
        return cls(TriggerKind.CRON, expr=" ".join(expr.split()), tz=tz)

    @classmethod
    def when_idle(cls, root: str, settle_ticks: int = 2) -> Trigger:
        return cls(TriggerKind.WHEN_IDLE, root=root, settle_ticks=settle_ticks)


@dataclass(frozen=True)
class StartBatch:
    workspace_id: str
    plan_id: str


@dataclass(frozen=True)
class RunAssignment:
    assignment: Assignment


@dataclass(frozen=True)
class PersonaPrompt:
    persona_instance_id: str
    prompt: str


Action = StartBatch | RunAssignment | PersonaPrompt


@dataclass(frozen=True)
class Armed:
    key: str
    trigger: Trigger
    action: Action
    next_fire: datetime | None
    last_fire: datetime | None = None
    enabled: bool = True
    owner_machine: str = ""


@dataclass(frozen=True)
class Fire:
    key: str
    action: Action
    at: datetime


class Scheduler(Protocol):
    def arm(self, key: str, trigger: Trigger, action: Action) -> Armed:
        """Idempotent by ``key``: a second arm of a key JOINS the first and returns it unchanged."""

    def disarm(self, key: str) -> bool:
        """Remove ``key``; False when nothing was armed under it."""

    def due(self, now: datetime) -> list[Fire]:
        """Pure: what would fire at ``now``."""

    def tick(self, now: datetime) -> list[dict[str, Any]]:
        """Fire what is due, advance ``next_fire``, persist; one receipt per fire."""

    def armed(self) -> list[Armed]:
        """Every armed schedule, by key."""


def _action_word(action: Action) -> str:
    return type(action).__name__


class ManualScheduler:
    """Manual by default: nothing fires on a clock; the operator's ``runtime.batch.start`` is the fire."""

    def __init__(self, *, owner_machine: str = "") -> None:
        self._owner_machine = owner_machine
        self._armed: dict[str, Armed] = {}

    def arm(self, key: str, trigger: Trigger, action: Action) -> Armed:
        if not KEY.match(str(key or "")):
            raise WorkRefused(Reason.SCHEDULE_INVALID, f"schedule key {key!r}")
        if trigger.kind is not TriggerKind.MANUAL:
            raise WorkRefused(Reason.NOT_BUILT, f"a {trigger.kind.value} trigger fires only on the serve tick (B4)")
        joined = key in self._armed
        armed = self._armed.setdefault(key, Armed(key, trigger, action, None, owner_machine=self._owner_machine))
        receipts.emit("schedule.arm", key=key, trigger=trigger.kind.value, next_fire=None,
                      action=_action_word(armed.action), joined=joined)
        return armed

    def disarm(self, key: str) -> bool:
        gone = self._armed.pop(key, None) is not None
        receipts.emit("schedule.disarm", key=key, disarmed=gone)
        return gone

    def due(self, now: datetime) -> list[Fire]:
        return []

    def tick(self, now: datetime) -> list[dict[str, Any]]:
        return []

    def armed(self) -> list[Armed]:
        return [self._armed[key] for key in sorted(self._armed)]
