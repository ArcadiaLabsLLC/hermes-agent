"""``runtime.chat.goal.set | status | pause | resume | clear`` — upstream's goal engine on a chat root.

Dispatcher plan ``docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md`` §5 (B3,
``RT-GOAL-ENGINE-DOOR``). Each verb is one row of ``agent_runtime.chat_goal.OPS`` over
``GoalManager(params["session_id"])`` and answers ``{"goal": <state>}``. ``console`` tier: a goal
drives an agent with tools turn after turn. The SessionDB read runs off the reader lane
(``spawn_reply``), as every Work verb does. Refusals: ``invalid_request`` (-32602), ``no_goal`` (4001).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.chat_goal import GoalOp
from agent_runtime.serve_rpc.protocol import DEFERRED, ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, \
    ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method
from agent_runtime.work_store.reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["GOAL_METHOD_PREFIX", "REFUSAL_CODES"]

GOAL_METHOD_PREFIX = "runtime.chat.goal."
REFUSAL_CODES: dict[Reason, int] = {Reason.INVALID: ERR_INVALID_PARAMS, Reason.NO_GOAL: ERR_NOT_FOUND}


def _goal_reply(rid: Any, op: str, params: dict) -> dict:
    from agent_runtime.chat_goal import execute

    try:
        return ok(rid, execute(op, params))
    except WorkRefused as refusal:
        return err(rid, REFUSAL_CODES.get(refusal.reason, ERR_CONFLICT), "This goal request could not be accepted.",
                   {"reason": refusal.reason.value, "detail": refusal.detail})
    except Exception:
        return err(rid, ERR_HANDLER_FAILED, "The goal could not be read or written.", {"reason": "goal_unavailable"})


def _handler(op: str):
    def handle(rid, params, context):
        reply = lambda: _goal_reply(rid, op, dict(params or {}))
        if context.spawn_reply is None or not context.spawn_reply(reply):
            return err(rid, ERR_CONFLICT, "The runtime is unavailable.", {"reason": "runtime_stopping"})
        return DEFERRED
    return handle


def _register() -> None:
    for op in GoalOp:
        method(GOAL_METHOD_PREFIX + op.value, tier=TIER_CONSOLE)(_handler(op.value))


_register()
