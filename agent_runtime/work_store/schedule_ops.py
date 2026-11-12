"""The schedule verbs — ``arm | disarm | list | pause | resume`` — shared by ``runtime.schedule.*`` and the ``schedule_manage`` tool.

Dispatcher plan §2.3, §4 (B4). Each verb builds a :class:`ServeTickScheduler` view over the files
(``schedule_store``) and answers a JSON-able dict; the serve's ticker reads the same files on its next
tick, so a verb needs no handle on the running ticker. Refusals raise ``WorkRefused``.

``arm`` params: ``key``; ``trigger`` (the wire: ``{kind, at, minutes, expr, tz, root, settle_ticks}``)
or ``cron_job`` (an upstream job record, read through ``Trigger.from_cron_job`` with ``tz``); ``action``
(``{type: persona_prompt | run_assignment | run_task | start_batch, …}``); ``replace: true`` overwrites the
record already under the key (an edit) where a plain second arm joins it.

``arm`` also takes ``ends`` (``{after_fires: <int >= 1> | null, until: <aware ISO time> | null}``) and
``skip_while_running`` (default true for a ``run_task``). ``pause`` / ``resume`` take ``key`` and answer
``{schedule}``; a key nothing is armed under refuses ``schedule_not_found``. Every answered record is
``schedule_store.record_wire``: the stored record plus ``last_result``
(``RT-SCHEDULE-PAUSE-END-AND-LAST-RESULT``).

``list`` answers ``supports`` beside ``schedules``: the words (:data:`SUPPORTS`) a client waits for before it
shows a control (``RT-SCHEDULE-RUN-TASK-REPEATS``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import schedule_store
from .reasons import Reason, WorkRefused
from .scheduler import Trigger
from .serve_scheduler import ServeTickScheduler

__layer__ = "lanes"
__all__ = ["OPS", "SUPPORTS", "execute"]

#: What this scheduler serves, as ``runtime.schedule.list`` says it: ``run_task`` (the action), ``replace``
#: (``arm``'s overwrite), ``pause`` (the pause and resume verbs), ``ends`` and ``skip_while_running`` (``arm``'s
#: fields), ``last_result`` (on every record).
SUPPORTS: tuple[str, ...] = ("run_task", "replace", "pause", "ends", "skip_while_running", "last_result")


def _schedule_key(params: Mapping[str, Any]) -> str:
    key = str(params.get("key") or "").strip()
    if not key:
        raise WorkRefused(Reason.INVALID, "key is required")
    return key


def _trigger(params: Mapping[str, Any]) -> Trigger:
    job = params.get("cron_job")
    if isinstance(job, Mapping):
        return Trigger.from_cron_job(job, str(params.get("tz") or "UTC"))
    raw = params.get("trigger")
    if not isinstance(raw, Mapping):
        raise WorkRefused(Reason.INVALID, "trigger (or cron_job) is required")
    return schedule_store.trigger_from_wire(raw)


def _arm(scheduler: ServeTickScheduler, params: Mapping[str, Any], armed_by: str) -> dict[str, Any]:
    key = _schedule_key(params)
    raw_action = params.get("action")
    if not isinstance(raw_action, Mapping):
        raise WorkRefused(Reason.INVALID, "action is required")
    scheduler.arm(key, _trigger(params), schedule_store.action_from_wire(raw_action), armed_by=armed_by,
                  replace=params.get("replace") is True, ends=schedule_store.ends_from_wire(params.get("ends")),
                  skip_while_running=_flag(params, "skip_while_running"))
    record = schedule_store.load_one(key)
    return {"schedule": None if record is None else schedule_store.record_wire(record)}


def _flag(params: Mapping[str, Any], name: str) -> bool | None:
    value = params.get(name)
    if value is not None and not isinstance(value, bool):
        raise WorkRefused(Reason.SCHEDULE_INVALID, f"{name} is true or false")
    return value


def _pause(scheduler: ServeTickScheduler, params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    return {"schedule": schedule_store.record_wire(scheduler.set_enabled(_schedule_key(params), False))}


def _resume(scheduler: ServeTickScheduler, params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    return {"schedule": schedule_store.record_wire(scheduler.set_enabled(_schedule_key(params), True))}


def _disarm(scheduler: ServeTickScheduler, params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    key = _schedule_key(params)
    return {"key": key, "disarmed": scheduler.disarm(key)}


def _list(scheduler: ServeTickScheduler, _params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    return {"schedules": [schedule_store.record_wire(record) for record in scheduler.records()],
            "supports": list(SUPPORTS)}


OPS: dict[str, Callable[[ServeTickScheduler, Mapping[str, Any], str], dict[str, Any]]] = {
    "arm": _arm,
    "disarm": _disarm,
    "list": _list,
    "pause": _pause,
    "resume": _resume,
}


def execute(op: str, params: Mapping[str, Any] | None, *, armed_by: str,
            scheduler: ServeTickScheduler | None = None) -> dict[str, Any]:
    verb = OPS.get(op)
    if verb is None:
        raise WorkRefused(Reason.INVALID, f"unknown schedule verb {op!r}")
    return verb(scheduler or ServeTickScheduler(), dict(params or {}), armed_by)
