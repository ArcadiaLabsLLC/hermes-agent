"""``harness serve settles`` / ``harness serve settles rearm`` — the argv fallback (D2.05).

The method lane is first (``runtime.settles.list`` / ``runtime.settles.rearm``,
``agent_runtime/serve_rpc/settles.py``); these verbs are thin over the SAME store
functions so a shell without a launcher can read the outbox and revive an
``undelivered`` settle. The live serve's pusher sends a re-armed record on its
next tick; with no launcher attached it is undelivered again after
``NO_LISTENER_SECONDS``.
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "lanes"

__all__ = ["_cmd_serve_settles", "_cmd_serve_settles_rearm"]

#: Exit code for a refusal (unknown id, already acked, a bad ``--state``).
_REFUSED = 2


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


def _cmd_serve_settles(args) -> int:
    """List the settle outbox: counts per state, then each record."""

    from agent_runtime.chat_turn_settles import SettleRefusal, settles_listing

    try:
        listing = settles_listing(state=getattr(args, "state", None))
    except ValueError:
        _emit({"ok": False, "reason": SettleRefusal.STATE_INVALID,
               "detail": "--state must be pending, undelivered or acked"})
        return _REFUSED
    if getattr(args, "json", False):
        _emit({"ok": True, **listing})
        return 0
    counts = listing["counts"]
    print(" ".join(f"{state}={counts[state]}" for state in sorted(counts)))
    for row in listing["settles"]:
        reason = f" ({row['undelivered_reason']})" if row.get("undelivered_reason") else ""
        print(f"{row['settle_id'][:12]}  {row['state']}{reason}  attempts={row['attempts']}"
              f"  rearms={row['rearm_count']}  {row['client_message_id']}")
    return 0


def _cmd_serve_settles_rearm(args) -> int:
    """Re-arm one settle by settle id or client message id (+ ``--session-id``)."""

    from agent_runtime.chat_turn_settles import (
        RearmResult,
        SettleRefusal,
        rearm_settle,
        resolve_settle_ref,
    )

    settle_id = resolve_settle_ref(getattr(args, "ref", None), session_id=getattr(args, "session_id", None))
    if settle_id is None:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_REF_REQUIRED})
        return _REFUSED
    result, record = rearm_settle(settle_id)
    if result is RearmResult.NOT_FOUND:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_NOT_FOUND, "settle_id": settle_id})
        return _REFUSED
    if result is RearmResult.ACKED:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_ACKED, "settle_id": settle_id})
        return _REFUSED
    _emit({"ok": True, "rearmed": result is RearmResult.REARMED, "settle": record.as_row()})
    return 0
