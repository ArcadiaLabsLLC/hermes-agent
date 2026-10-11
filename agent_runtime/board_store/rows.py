"""The board's CLI row projections — re-keys of the snapshot's own builders.

``_card_row`` / ``_board_row`` (and the CLI-only ``active_cards`` column's
``_column_kind`` / ``_board_active_card_count``) used to live in
``hermes_cli/harness_parts/board.py``; they live here so the argv verbs and the
``runtime.board.*`` method twins project a card from ONE owner (``agent_runtime``
never imports ``hermes_cli``). Both builders they re-key are
``agent_runtime.snapshot.boards``'s; masking and truncation stay theirs.
"""

from __future__ import annotations

__layer__ = "stores"

__all__ = [
    "_board_active_card_count",
    "_board_row",
    "_card_row",
    "_column_kind",
]


def _board_active_card_count(board, cards) -> int:
    """Cards NOT parked in a ``done`` column.

    Deliberately NOT the snapshot row's ``active_card_count`` — that one counts
    every non-archived card. Two different questions with confusingly similar
    names; the CLI column keeps its own meaning rather than silently changing
    the number an operator reads. Recorded as a residual on ledger item 4.
    """

    return len([c for c in cards if _column_kind(board, c.column_id) != "done"])


def _column_kind(board, column_id: str) -> str:
    for column in board.columns:
        if column.column_id == column_id:
            return column.kind
    return "custom"


def _board_row(store, board, *, full: bool = False) -> dict:
    """`board list|show|create|update` row — a RE-KEY of the snapshot's own
    ``board_summary_row`` (S48, ledger item 4).

    Before this, ``--full`` printed EVERY active card through an unmasked,
    uncapped ``_card_row``; the wire had been capping at
    ``MAX_BOARD_CARDS_PROJECTED`` and masking card prose the whole time. The
    cap is now the builder's and is ACCOUNTED, never silent: ``cards_truncated``
    rides the full row whenever cards were cut.

    Imported inside the function (a convention from before lane H1, when this
    module was exec'd into ``harness.py``'s globals). ``store``/``board`` stay in the
    signature because the CLI's own ``active_cards`` column (a different
    question — see ``_board_active_card_count``) is not on the builder's row.
    """

    from agent_runtime.snapshot.boards import board_summary_row

    # ``scan_cards``, not ``list_cards``: the CLI row states the same
    # completeness the wire row does, so the two cannot disagree about how much
    # of the board they just rendered.
    scan = store.scan_cards(board.board_id)
    cards = scan.cards
    summary = board_summary_row(board, cards, cards_unreadable=scan.unreadable)
    row = {
        "id": summary["board_id"],
        "workspace_id": summary["workspace_id"],
        "title": summary["title"],
        "columns": len(summary["columns"]),
        "active_cards": _board_active_card_count(board, cards),
        "revision": summary["revision"],
        "updated_at": board.updated_at,
    }
    if full:
        row["column_defs"] = summary["columns"]
        by_id = {card.card_id: card for card in cards}
        row["cards"] = [_card_row(by_id[projected["card_id"]], summary=projected) for projected in summary["cards"]]
        row["cards_truncated"] = summary["cards_truncated"]
        row["archived_card_ids"] = summary["archived_card_ids"]
    return row


def _card_row(card, *, full: bool = False, summary: dict | None = None) -> dict:
    """One card row — a RE-KEY of the snapshot's own ``board_card_row``.

    Card prose is the one genuinely SENSITIVE payload in this tier, and the CLI
    used to print ``card.title`` / ``card.description`` / ``card.checklist``
    raw while the wire masked all three. Masking is now inherited, so it is
    value-level and IN PLACE — ``"Rotate api_key: sk-live-…"`` renders
    ``"Rotate api_key: [redacted]"``, never a blanked field. Description
    truncation likewise carries ``description_truncated`` on the full row: the
    store accepts 4,000 characters and the projection bound is 2,048, so the
    cut is real and is named.

    ``summary`` lets ``_board_row`` pass the row the board builder ALREADY
    projected for this card (it owns the per-board cap), instead of projecting
    it a second time.
    """

    if summary is None:
        from agent_runtime.snapshot.boards import board_card_row

        summary = board_card_row(card)
    row = {
        "id": summary["card_id"],
        "column_id": summary["column_id"],
        "title": summary["title"],
        "priority": summary["priority"],
        "state": summary["state"],
        "updated_at": card.updated_at,
    }
    if full:
        row.update(
            {
                key: summary[key]
                for key in (
                    "board_id",
                    "description",
                    "description_truncated",
                    "labels",
                    "assignee",
                    "checklist",
                    "order_key",
                    "created_by",
                    "revision",
                )
            }
        )
        row["created_at"] = card.created_at
    return row
