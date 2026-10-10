"""``runtime.settles.list`` / ``runtime.settles.rearm`` — the settle outbox's operator verbs (D2.05).

The serve PUSHES every chat-turn settle and re-sends it until the launcher acks it
(``agent_runtime.chat_turn_settles``); a record whose budget ran out ends
``undelivered`` with a typed reason and, before this, nothing could read or revive
it. These two methods are that operator surface; ``harness serve settles`` is the
argv fallback over the SAME store functions.

Tier ``console`` for both: a settle names a chat session and a turn, and
``read`` is a paired viewer device (plan
``docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md`` § D2.05).
The list's ``counts`` is the "connections-adjacent" number the row asked for; it
rides this result, never ``runtime.health`` (whose contract is ``harness health
--json`` verbatim) and never a frame envelope.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_settles_list", "_runtime_settles_rearm"]


@method("runtime.settles.list", tier=TIER_CONSOLE)
def _runtime_settles_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Params: ``{state?}`` (``pending`` | ``undelivered`` | ``acked``). Result:
    ``{counts: {pending, undelivered, acked}, settles: [record…]}``, each record
    the stored settle row (``state``, ``attempts``, ``undelivered_reason``,
    ``rearm_count``, ``next_attempt_at`` and the frame's own fields)."""

    from agent_runtime.chat_turn_settles import SettleRefusal, settles_listing

    params = params or {}
    state = params.get("state")
    try:
        listing = settles_listing(state=state)
    except ValueError:
        return err(rid, ERR_INVALID_PARAMS, "state must be pending, undelivered or acked.",
                   {"reason": SettleRefusal.STATE_INVALID})
    return ok(rid, listing)


@method("runtime.settles.rearm", tier=TIER_CONSOLE)
def _runtime_settles_rearm(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Params: ``{settle_id}`` or ``{client_message_id, session_id?}`` — the two
    addressings ``settle_ack`` accepts. Result: ``{rearmed, settle}``; ``rearmed``
    is False for a record already ``pending`` (a no-op). An ``acked`` record is
    refused: the launcher already took it."""

    from agent_runtime.chat_turn_settles import (
        RearmResult,
        SettleRefusal,
        rearm_settle,
        resolve_settle_id,
    )

    params = params or {}
    settle_id = resolve_settle_id(
        settle_id=params.get("settle_id"),
        client_message_id=params.get("client_message_id"),
        session_id=params.get("session_id"),
    )
    if settle_id is None:
        return err(rid, ERR_INVALID_PARAMS,
                   "Name a settle_id, or a client_message_id (+ session_id).",
                   {"reason": SettleRefusal.SETTLE_REF_REQUIRED})
    result, record = rearm_settle(settle_id)
    if result is RearmResult.NOT_FOUND:
        return err(rid, ERR_NOT_FOUND, "No settle with that id.",
                   {"reason": SettleRefusal.SETTLE_NOT_FOUND, "settle_id": settle_id})
    if result is RearmResult.ACKED:
        return err(rid, ERR_CONFLICT, "That settle was already acked; there is nothing to re-send.",
                   {"reason": SettleRefusal.SETTLE_ACKED, "settle_id": settle_id})
    return ok(rid, {"rearmed": result is RearmResult.REARMED, "settle": record.as_row()})
