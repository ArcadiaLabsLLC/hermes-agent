"""Seat a turn's tool calls between the things it said, as its recorded elements ran.

The operator conversation builds a turn from two sources that carry no shared position: the trace
pairs each tool call into one ``tool_call`` row in the content band (``TURN_SEQ_CONTENT``), and the
stored history gives each thing the turn said a row placed by stored position
(``TURN_SEQ_TERMINAL - k``). So every step sorted before every word, and a reply that said, ran,
said again drew its words back to back (RT-OPERATOR-CHAT-TOOLS-SORT-BEFORE-ALL-WORDS). The turn's
recorded ``turn_elements`` (segment / tool, by emitter ``seq``) say how they interleave; this
re-stamps the turn's tail rows in that order. When the counts do not line up (a capped history,
a missing trace row) nothing moves — the old order is the honest fallback.
"""

from __future__ import annotations

from typing import Any, Callable

from ..transcript_order import TURN_SEQ_CONTENT, TURN_SEQ_TERMINAL

__layer__ = "policy"

_SAID = "reply"
_TOOL = "tool_call"


def _seq(row: dict[str, Any]) -> int | None:
    value = row.get("turn_seq")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _tool_ordinal(row: dict[str, Any]) -> int:
    tail = str(row.get("id") or "").rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def seat_tool_calls_by_elements(
    messages: list[dict[str, Any]],
    history_rows: list[Any],
    *,
    anchor: Callable[[dict[str, Any]], str | None],
) -> None:
    """Re-stamp ``turn_seq`` in place for each turn whose elements say where its tools ran."""

    elements_by_turn: dict[str, list[dict[str, Any]]] = {}
    for row in history_rows:
        if isinstance(row, dict) and isinstance(row.get("turn_elements"), list):
            if key := anchor(row):
                elements_by_turn[key] = [e for e in row["turn_elements"] if isinstance(e, dict)]
    for key, elements in elements_by_turn.items():
        kinds = [e.get("kind") for e in sorted(elements, key=lambda e: int(e.get("seq") or 0))]
        rows = [m for m in messages if anchor(m) == key and _seq(m) is not None]
        tail = sorted((m for m in rows if _seq(m) > TURN_SEQ_CONTENT), key=_seq)
        tools = sorted((m for m in rows if m.get("kind") == _TOOL and _seq(m) == TURN_SEQ_CONTENT),
                       key=_tool_ordinal)
        said = [m for m in tail if m.get("kind") == _SAID]
        if not tools or len(said) < 2 or kinds.count("segment") != len(said) or kinds.count("tool") != len(tools):
            continue
        # after[j]: the tools that ran after the j-th thing said and before the next one.
        after: list[list[dict[str, Any]]] = [[] for _ in said]
        spoken, pending = 0, iter(tools)
        for kind in kinds:
            if kind == "segment":
                spoken += 1
            elif 0 < spoken < len(said):
                after[spoken - 1].append(next(pending))
            else:
                next(pending)  # before the first word or after the last: stays in the content band
        if not any(after):
            continue
        ordered: list[dict[str, Any]] = []
        said_so_far = 0
        for row in tail:
            ordered.append(row)
            if row.get("kind") == _SAID:
                ordered.extend(after[said_so_far])
                said_so_far += 1
        for position, row in enumerate(ordered):
            # MUTATION: keep tools at TURN_SEQ_CONTENT and the interleave test reddens (steps before words).
            row["turn_seq"] = TURN_SEQ_TERMINAL - (len(ordered) - 1 - position)
