"""The synthetic rows a transcript carries for a turn that ended without a reply, and their order.

Separate because the markers are projected from the turn journal, not from
SessionDB rows, and ordered into the transcript afterwards.
"""

from __future__ import annotations

from typing import Any

from ..clock import iso_timestamp
from ..mission_chat_turns import mission_chat_turn_records
from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..run_budget import ACCOUNTING_KEY as RUN_BUDGET_ACCOUNTING_KEY
from ..transcript_order import TURN_SEQ_TERMINAL, order_transcript_rows
from ..turn_visibility import TURN_VISIBILITY_KEY, classify_persisted_turn_row
from .vocabulary import (
    PERSONA_TURN_SILENT_KIND,
    SILENT_TURN_MARKER_TEXTS,
    TERMINAL_TURN_MARKERS,
    canonical_persona_chat_turn_id,
)

__layer__ = "policy"
__all__ = [
    "_carry_run_budget",
    "_silent_turn_marker_row",
    "_terminal_turn_marker_rows",
    "_ordered_message_rows",
]


def _carry_run_budget(row: dict[str, Any], record: dict[str, Any] | None) -> None:
    """Ride the turn record's accounting block onto a projected row, or nothing.

    Absence-preserving in both directions: a record with no block (an older
    turn, or one that declared no budget) leaves the row untouched, so a reader
    can still tell "nothing bounded this turn" from "nobody accounted it". The
    block is copied verbatim — the store already bounded it through the one
    ``run_budget.safe_accounting_block`` reader.
    """

    block = (record or {}).get(RUN_BUDGET_ACCOUNTING_KEY)
    if isinstance(block, dict) and block:
        row[RUN_BUDGET_ACCOUNTING_KEY] = block


def _silent_turn_marker_row(
    *,
    session_id: str,
    index: int,
    raw: dict[str, Any],
    role: str,
    raw_content: Any,
    client_message_id: str | None,
    turn_id: str | None,
) -> dict[str, Any] | None:
    """The typed marker for an agent row that ended a turn saying nothing.

    Returns ``None`` for every row that is not exactly that — an operator row,
    a tool-call round, a row with content the curator merely found
    unpresentable. The classification itself is not made here: this reads
    ``turn_visibility.classify_persisted_turn_row`` and renders its verdict, so
    the projection cannot form a second opinion about what silence is.

    The row takes the identity of the assistant row it stands in for, including
    its ``turn_seq``: a turn has a reply or a marker, never both, and this
    marker IS that turn's terminal row.
    """

    if role != "agent":
        return None
    visibility = classify_persisted_turn_row(
        content=raw_content,
        finish_reason=raw.get("finish_reason"),
        tool_calls=raw.get("tool_calls"),
    )
    if visibility is None or not visibility.is_silent:
        return None
    marker_row: dict[str, Any] = {
        "id": safe_assignment_text(raw.get("id"), limit=120) or f"{session_id}:{index}",
        # Not the agent speaking — the projection reporting that it did not.
        # Same role/kind shape as the terminal markers, which the Launcher
        # already renders as system-level turn status rather than as a message.
        "role": "system",
        "kind": PERSONA_TURN_SILENT_KIND,
        "text": SILENT_TURN_MARKER_TEXTS[visibility.reason],
        "timestamp": iso_timestamp(
            raw.get("created_at")
            or raw.get("timestamp")
            or raw.get("time")
            or raw.get("updated_at")
        ),
        # The body is this module's own prose about an EMPTY row. No transcript
        # content passed through it, so there is nothing a redactor could have
        # caught and nothing to claim it verified.
        "redaction_status": "safe",
        # The typed verdict rides along so a consumer can key on the cause
        # (truncated / filtered / empty) instead of matching the prose above —
        # the same discipline as every other typed kind in this projection.
        TURN_VISIBILITY_KEY: visibility.as_dict(),
    }
    if client_message_id:
        marker_row["client_message_id"] = client_message_id
        marker_row["turn_seq"] = TURN_SEQ_TERMINAL
    if turn_id:
        marker_row["turn_id"] = turn_id
    return marker_row


def _terminal_turn_marker_rows(
    *,
    session_id: str,
    assistant_client_message_ids: set[str],
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Synthesize the typed marker row for every terminally-settled, reply-less turn.

    Driven by ``TERMINAL_TURN_MARKERS`` — one table, one row shape, one code
    path per terminal state. This used to test ``state != "interrupted"``, which
    made ``budget_exhausted`` (the wall-budget terminal state, 2026-07-26) a
    turn that ended and never said so: no marker, so
    ``operator_channels._settle_terminal_tool_calls`` never fired and a
    ``tool_started`` row with no finish spun in the cockpit forever.

    ``settled_state`` rides along so downstream projections carry the REASON the
    turn is over without re-deriving it from the marker kind or the prose.

    ``records`` lets the caller hand in the journal read it already did; left
    None (direct callers, tests) this reads the journal itself. The marker row
    is the ONLY row a reply-less budget-exhausted turn gets, so the accounting
    block has to ride here too — otherwise the exact turns whose bound is worth
    reading are the ones that carry no bound.
    """

    rows: list[dict[str, Any]] = []
    if records is None:
        records = mission_chat_turn_records(session_id=session_id)
    for record in records:
        state = safe_assignment_token(record.get("state"))
        marker = TERMINAL_TURN_MARKERS.get(state or "")
        if marker is None:
            continue
        client_message_id = safe_assignment_text(record.get("client_message_id"), limit=240)
        if not client_message_id or client_message_id in assistant_client_message_ids:
            continue
        turn_id = safe_assignment_token(record.get("turn_id")) or safe_assignment_token(client_message_id)
        if not turn_id:
            continue
        marker_row: dict[str, Any] = {
            "id": f"{session_id}:{marker.id_slug}:{client_message_id}",
            "role": "system",
            # Typed marker: downstream projections (operator conversation,
            # Mission Control tiles) key on this instead of matching text.
            "kind": marker.kind,
            "text": marker.text,
            "timestamp": iso_timestamp(record.get("updated_at")),
            "redaction_status": "safe",
            "client_message_id": client_message_id,
            "turn_id": turn_id,
            # The canonical turn-store state, not a second vocabulary.
            "settled_state": state,
            # C8 ordering key: the terminal marker IS the turn's terminal
            # row (a turn has a reply or a marker, never both).
            "turn_seq": TURN_SEQ_TERMINAL,
        }
        _carry_run_budget(marker_row, record)
        rows.append(marker_row)
    return rows


def _ordered_message_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # C8: ONE ordering authority. Rows carrying the turn key (anchor =
    # canonical turn_id, position = turn_seq) sort by that key inside their
    # turn — the operator row first, elements by emitter seq, the terminal
    # reply/interrupt last — regardless of clock skew between SessionDB stamps
    # and turn-store settle times (the F17 reorder seam). Rows that predate the
    # key keep the pre-C8 fallback: timestamp order with the original index as
    # tie-breaker, a row without a parseable timestamp inheriting the preceding
    # row's so it holds its transcript position instead of front-loading.
    fallback: list[tuple[str, int]] = []
    last_timestamp = ""
    for index, row in enumerate(rows):
        timestamp = str(row.get("timestamp") or "") or last_timestamp
        last_timestamp = timestamp
        fallback.append((timestamp, index))
    return order_transcript_rows(
        rows,
        # Token-normalized so the anchor is byte-equal to the `turn_id` the
        # emitter/turn store mint from the same client_message_id.
        anchor=lambda row: (
            safe_assignment_token(row.get("turn_id"))
            or canonical_persona_chat_turn_id(row.get("client_message_id"))
        ),
        turn_seq=lambda row: row.get("turn_seq")
        if isinstance(row.get("turn_seq"), int)
        else None,
        fallback_key=lambda _row, index: fallback[index],
    )
