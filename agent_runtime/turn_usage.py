"""What one persona turn cost in provider tokens: the ``provider_usage`` block of a turn record.

RT-TURN-RECORD-USAGE. ``run_budget`` counts wall seconds and MCP calls only, so a turn's input /
output / cache tokens could not be read once it ended: they reached the live result frame
(``AgentRunResult``) and evaporated. The settle writes this block beside ``phases`` on the
terminal record; ``mission_chat_turns.records`` re-admits it through :func:`safe_turn_usage`.

The per-call rows are ``agent_runtime.usage_ledger``'s (one per provider call, in call order); the
totals are the runner's turn-cumulative counters. Cost is NOT stored: a price is a lookup against a
table that changes, so the audit read (``chat_verbs.turn_audit``) prices the stored tokens when it
is asked, and says when it could not.

Absent stays absent: a turn whose runner reported no model and no tokens gets no block.
"""

from __future__ import annotations

from typing import Any

__layer__ = "policy"

__all__ = ["TURN_USAGE_KEY", "TURN_USAGE_SCHEMA", "safe_turn_usage", "turn_usage_block"]

TURN_USAGE_KEY = "provider_usage"
TURN_USAGE_SCHEMA = 1

TOTAL_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens", "total_tokens",
)
CALL_FIELDS = (
    "prompt_tokens", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "reasoning_tokens",
)
#: ``usage_ledger.USAGE_LEDGER_MAX_ROWS``; re-applied here, defence in depth.
MAX_CALLS = 256
#: A token count above this is a corrupt row, not a large turn.
_MAX_TOKENS = 10**10
_TEXT_LIMIT = 160


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= _MAX_TOKENS else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:_TEXT_LIMIT]
    return text or None


def _calls(rows: Any) -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    for index, row in enumerate(rows if isinstance(rows, list) else ()):
        if len(out) >= MAX_CALLS:
            break
        if not isinstance(row, dict):
            continue
        call = {"call_index": _count(row.get("call_index")) or index + 1}
        for field in CALL_FIELDS:
            count = _count(row.get(field))
            if count is not None:
                call[field] = count
        out.append(call)
    return out


def safe_turn_usage(value: Any) -> dict[str, Any] | None:
    """The bounded block, or ``None`` when nothing in it is readable. Drops, never defaults."""

    if not isinstance(value, dict) or value.get("schema") != TURN_USAGE_SCHEMA:
        return None
    block: dict[str, Any] = {"schema": TURN_USAGE_SCHEMA}
    for key in ("provider", "model"):
        text = _text(value.get(key))
        if text:
            block[key] = text
    for key in ("api_calls", *TOTAL_FIELDS):
        count = _count(value.get(key))
        if count is not None:
            block[key] = count
    calls = _calls(value.get("calls"))
    if calls:
        block["calls"] = calls
    return block if len(block) > 1 else None


def turn_usage_block(result: Any) -> dict[str, Any] | None:
    """The block for one ``AgentRunResult`` (read by attribute; anything else yields ``None``)."""

    if result is None:
        return None
    raw = {
        "schema": TURN_USAGE_SCHEMA,
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "api_calls": getattr(result, "api_calls", None),
        **{field: getattr(result, field, None) for field in TOTAL_FIELDS},
        "calls": list(getattr(result, "usage_ledger", None) or []),
    }
    return safe_turn_usage(raw)
