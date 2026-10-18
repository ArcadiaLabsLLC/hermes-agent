"""The schedule verbs — ``arm | disarm | list`` — shared by ``runtime.schedule.*`` and the ``schedule_manage`` tool.

Dispatcher plan §2.3, §4 (B4). Each verb builds a :class:`ServeTickScheduler` view over the files
(``schedule_store``) and answers a JSON-able dict; the serve's ticker reads the same files on its next
tick, so a verb needs no handle on the running ticker. Refusals raise ``WorkRefused``.

``arm`` params: ``key``; ``trigger`` (the wire: ``{kind, at, minutes, expr, tz, root, settle_ticks}``)
or ``cron_job`` (an upstream job record, read through ``Trigger.from_cron_job`` with ``tz``); ``action``
(``{type: persona_prompt | run_assignment | start_batch, …}``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import schedule_store
from .reasons import Reason, WorkRefused
from .scheduler import Trigger
from .serve_scheduler import ServeTickScheduler

__layer__ = "lanes"
__all__ = ["OPS", "execute"]


def _key(params: Mapping[str, Any]) -> str:
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
    key = _key(params)
    raw_action = params.get("action")
    if not isinstance(raw_action, Mapping):
        raise WorkRefused(Reason.INVALID, "action is required")
    scheduler.arm(key, _trigger(params), schedule_store.action_from_wire(raw_action), armed_by=armed_by)
    record = schedule_store.load_one(key)
    return {"schedule": None if record is None else record.wire()}


def _disarm(scheduler: ServeTickScheduler, params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    key = _key(params)
    return {"key": key, "disarmed": scheduler.disarm(key)}


def _list(scheduler: ServeTickScheduler, _params: Mapping[str, Any], _armed_by: str) -> dict[str, Any]:
    return {"schedules": [record.wire() for record in scheduler.records()]}


OPS: dict[str, Callable[[ServeTickScheduler, Mapping[str, Any], str], dict[str, Any]]] = {
    "arm": _arm,
    "disarm": _disarm,
    "list": _list,
}


def execute(op: str, params: Mapping[str, Any] | None, *, armed_by: str,
            scheduler: ServeTickScheduler | None = None) -> dict[str, Any]:
    verb = OPS.get(op)
    if verb is None:
        raise WorkRefused(Reason.INVALID, f"unknown schedule verb {op!r}")
    return verb(scheduler or ServeTickScheduler(), dict(params or {}), armed_by)
