"""What a batch lane's run cost: its turn record's ``provider_usage`` totals, priced at read time.

RT-BATCH-LANE-WORKTREES-AND-USAGE. A lane's ``run_id`` is ``<root session>/<client message id>``
(``work_store.persona_turn._run_id``); the turn record that run settled carries the token totals
(``turn_usage``). Cost is never stored: the price comes from ``chat_verbs.turn_audit``'s pricer, the
one price list, when ``runtime.batch.status`` is asked — ``priced`` is false when it could not price.
A run with no turn record (or a record with no usage) answers ``None``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

__layer__ = "policy"
__all__ = ["USAGE_TOTALS", "lane_usage", "usage_index"]

#: The totals the lane wire carries, in the turn record's own names.
USAGE_TOTALS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens")


def usage_index(records: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """``{run_id: provider_usage}`` over turn records — one pass, so a status call reads the records once."""

    from agent_runtime.turn_usage import TURN_USAGE_KEY

    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        usage = record.get(TURN_USAGE_KEY)
        root, cmid = record.get("root_chat_session_id"), record.get("client_message_id")
        if isinstance(usage, Mapping) and root and cmid:
            out[f"{root}/{cmid}"] = usage
    return out


def lane_usage(run_id: str | None, index: Mapping[str, Mapping[str, Any]],
               price: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any] | None:
    """The lane wire's ``usage``: the totals plus ``cost_usd`` and ``priced``; None with no record."""

    usage = index.get(run_id or "")
    if usage is None:
        return None
    totals = {key: int(usage.get(key) or 0) for key in USAGE_TOTALS}
    try:
        cost = price(dict(usage))
    except Exception:  # a price is a lookup; its failure is a stated unknown, never a refusal
        cost = None
    usd = cost.get("usd") if isinstance(cost, Mapping) else None
    return {**totals, "cost_usd": usd, "priced": usd is not None}
