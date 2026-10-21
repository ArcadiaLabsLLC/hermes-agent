"""``runtime.schedule.arm | disarm | list`` — the desktop runtime's scheduler (``ServeTickScheduler``).

Dispatcher plan ``docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md`` §2.3, §4
(B4, ``RT-DISPATCH-B4-SCHEDULER``). Each verb is one row of ``work_store.schedule_ops.OPS`` and runs off
the reader lane (``spawn_reply``), as every Work verb does. ``console`` tier: an armed schedule starts
agent turns on a clock. The Launcher arms a hermes schedule only through ``arm`` (plan §4). Refusals:
``invalid_request`` / ``schedule_invalid`` (-32602), the rest (``automation_off``, ``machine_identity_unavailable``)
4090, each with ``data.reason``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, defer_or_refuse, err, ok
from agent_runtime.serve_rpc.registry import method
from agent_runtime.work_store.reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["REFUSAL_CODES", "SCHEDULE_METHOD_PREFIX", "SCHEDULE_OPS"]

SCHEDULE_METHOD_PREFIX = "runtime.schedule."
SCHEDULE_OPS = ("arm", "disarm", "list")
REFUSAL_CODES: dict[Reason, int] = {Reason.INVALID: ERR_INVALID_PARAMS, Reason.SCHEDULE_INVALID: ERR_INVALID_PARAMS}


def _schedule_reply(rid: Any, op: str, params: dict) -> dict:
    from agent_runtime.work_store.schedule_ops import execute

    try:
        return ok(rid, execute(op, params, armed_by="operator"))
    except WorkRefused as refusal:
        return err(rid, REFUSAL_CODES.get(refusal.reason, ERR_CONFLICT), "This schedule request could not be accepted.",
                   {"reason": refusal.reason.value, "detail": refusal.detail})
    except Exception:
        return err(rid, ERR_HANDLER_FAILED, "The schedules could not be read or written.",
                   {"reason": "schedule_unavailable"})


def _schedule_method(op: str):
    def handle(rid, params, context):
        return defer_or_refuse(rid, SCHEDULE_METHOD_PREFIX + op, context,
                               lambda: _schedule_reply(rid, op, dict(params or {})))
    return handle


def _register() -> None:
    for op in SCHEDULE_OPS:
        method(SCHEDULE_METHOD_PREFIX + op, tier=TIER_CONSOLE)(_schedule_method(op))


_register()
