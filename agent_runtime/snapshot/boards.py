"""The boards projection: card rows, the board summary, and board parity
warnings.
"""

from __future__ import annotations

from typing import NamedTuple

from agent_runtime import paths
from agent_runtime.serde import section_rows, to_jsonable

from agent_runtime.snapshot.receipts import _ARCHIVED_CONVERSATION_SECRET_RE

__all__ = [
    "BOARD_CARD_DESC_LIMIT",
    "BoardsProjection",
    "MAX_BOARD_CARDS_PROJECTED",
    "_board_card_row",
    "_board_conflict_card_ids",
    "_board_parity_warnings",
    "_boards_summary",
    "_mask_board_secrets",
    "board_summary_row",
]


# Mission Board projection bounds — honest accounting, never a silent cap
# (the 8.6MB-snapshot lesson): oversized boards report the remainder count and
# card bodies truncate with a flag rather than growing the snapshot unbounded.
MAX_BOARD_CARDS_PROJECTED = 500


BOARD_CARD_DESC_LIMIT = 2048


def _mask_board_secrets(text) -> str:
    """Hard-on secret mask for card prose in the projection (observe mode never
    disables it). Card text rides the same projection boundary as goal text; the
    HARD gate is the realm-publish fail-closed scan in ``realm_sync``."""

    if not text:
        return "" if text is None else text
    return _ARCHIVED_CONVERSATION_SECRET_RE.sub(lambda m: f"{m.group(1)}: [redacted]", str(text))


def _board_card_row(card, *, unpublished: bool | None = None) -> dict:
    description = card.description or ""
    truncated = len(description) > BOARD_CARD_DESC_LIMIT
    if truncated:
        description = description[:BOARD_CARD_DESC_LIMIT]
    row = {
        "card_id": card.card_id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "title": _mask_board_secrets(card.title),
        "description": _mask_board_secrets(description),
        "description_truncated": truncated,
        "priority": card.priority,
        "labels": list(card.labels),
        "assignee": card.assignee,
        "checklist": [
            {"text": _mask_board_secrets(str(item.get("text", ""))), "done": bool(item.get("done"))}
            for item in card.checklist
            if isinstance(item, dict)
        ],
        "order_key": card.order_key,
        "state": card.state,
        "created_by": card.created_by,
        "updated_at": to_jsonable(card.updated_at),
        "updated_by": card.updated_by,
        "revision": card.revision,
    }
    # Publication honesty is only meaningful for realm-bound boards; omit the
    # flag entirely otherwise (mirrors the office ``unpublished=None`` posture).
    if unpublished is not None:
        row["unpublished"] = unpublished
    return row


def _board_conflict_card_ids(board_id: str) -> list[str]:
    """Card ids with an OPEN conflict sidecar. Local file reads only — no git."""

    conflicts_dir = paths.board_conflicts_dir(board_id)
    if not conflicts_dir.exists():
        return []
    ids = [path.stem for path in conflicts_dir.glob("*.json") if not path.name.endswith(".resolved.json")]
    return sorted(ids)


def board_summary_row(
    board,
    cards,
    *,
    cards_unreadable: int,
    card_unpublished=None,
    board_unpublished: bool | None = None,
    orphaned: bool = False,
) -> dict:
    """ONE board projection row — the single authority for the board card
    projection bound, the card-body masking and the truncation accounting.

    Extracted from ``_boards_summary``'s loop body verbatim (S48, ledger item
    4) so the ``hermes harness board`` CLI tier renders the SAME row instead of
    hand-rolling a second, unmasked, uncapped one. ``cards`` is the caller's
    already-fetched active card list (the CLI needs it for its own non-done
    count, and a second store read would be a second answer).

    ``card_unpublished`` is the caller-owned per-card baseline probe; a caller
    with no realm baseline passes ``None`` and the per-card flag is omitted
    entirely, exactly as the un-extracted loop did.

    ``cards_unreadable`` is REQUIRED, and required by keyword, for the reason
    ``office_summary_row``'s twin is: ``_scan_card_dir`` skips a file it cannot
    decode, so ``cards`` arrives already SHORTENED and ``cards_truncated``
    computed from that shortened length answers 0. A caller that genuinely holds
    a bare list has to say ``cards_unreadable=0`` out loud rather than get it by
    default — the same "never silently zero" rule ``CardScan.unreadable`` is
    declared under.
    """

    projected = cards[:MAX_BOARD_CARDS_PROJECTED]
    row = {
        "board_id": board.board_id,
        "workspace_id": board.workspace_id,
        "title": board.title,
        "revision": board.revision,
        "updated_at": to_jsonable(board.updated_at),
        "columns": [
            {"column_id": c.column_id, "title": c.title, "kind": c.kind, "wip_limit": c.wip_limit}
            for c in board.columns
        ],
        "cards": [
            _board_card_row(c, unpublished=(card_unpublished(c) if card_unpublished is not None else None))
            for c in projected
        ],
        "active_card_count": len(cards),
        "cards_truncated": max(0, len(cards) - len(projected)),
        # The OTHER way this list can be short, and the one it used to hide
        # completely: files that exist and would not decode. Its sibling above
        # counts a cut WE chose; this one counts rows the platform took.
        # Additive — an old launcher ignores the key.
        "cards_unreadable": int(cards_unreadable),
        "conflict_card_ids": _board_conflict_card_ids(board.board_id),
        "archived_card_ids": list(board.archived_card_ids),
        # A board whose workspace no longer resolves is accounted, never
        # silently hidden (repair via archive) — parity warning below.
        "orphaned": orphaned,
    }
    # Publication honesty is only meaningful for realm-bound boards; omit the
    # flag entirely otherwise (mirrors the office ``unpublished=None`` posture).
    if board_unpublished is not None:
        row["unpublished"] = board_unpublished
    return row


class BoardsProjection(NamedTuple):
    """The board rows this snapshot BUILT, beside how many whole boards it
    could not build a row for. ``OfficesProjection``'s twin, same law."""

    boards: list[dict]
    #: Board directories whose ``board.json`` would not decode. Additive on the
    #: wire as ``boards_unreadable`` — an old launcher ignores the key.
    unreadable: int


def _boards_summary(board_store, workspaces) -> BoardsProjection:
    """Mission Board projection rows, keyed by board_id. Local reads only:
    conflict card ids from local sidecar files, ``unpublished`` (per board and
    per card) from the local realm-sync baseline sidecar — a pure file read, the
    same Decision-7 posture and baseline machinery ``_offices_summary`` uses."""

    from ..board_models import board_content_hash
    from ..board_sync import read_board_baseline

    workspace_ids = {getattr(w, "id", None) for w in workspaces}
    realm_by_workspace = {getattr(w, "id", None): getattr(w, "realm_id", None) for w in workspaces}
    baselines: dict[str, dict[str, str]] = {}
    boards: list[dict] = []
    board_scan = board_store.scan_all()
    for board in board_scan.boards:
        # ``scan_cards``, not ``list_cards``: the thin list view drops the files
        # it could not decode and the row below must not describe itself as
        # complete when it is not.
        card_scan = board_store.scan_cards(board.board_id)
        cards = card_scan.cards  # active, (order_key, card_id) sorted
        realm_id = realm_by_workspace.get(board.workspace_id)
        baseline: dict[str, str] | None = None
        if realm_id:
            if realm_id not in baselines:
                try:
                    baselines[realm_id] = read_board_baseline(realm_id)
                except Exception:
                    baselines[realm_id] = {}
            baseline = baselines[realm_id]

        def _card_unpublished(card) -> bool | None:
            # Publication honesty is only meaningful for realm-bound boards.
            if baseline is None:
                return None
            return baseline.get(f"{board.board_id}:card:{card.card_id}") != board_content_hash(card)

        board_unpublished: bool | None = None
        if baseline is not None:
            board_unpublished = baseline.get(f"{board.board_id}:board") != board_content_hash(board)

        boards.append(
            board_summary_row(
                board,
                cards,
                cards_unreadable=card_scan.unreadable,
                card_unpublished=_card_unpublished,
                board_unpublished=board_unpublished,
                orphaned=board.workspace_id not in workspace_ids,
            )
        )
    return BoardsProjection(boards=boards, unreadable=board_scan.unreadable)


def _board_parity_warnings(data) -> list[dict]:
    warnings: list[dict] = []
    for board in section_rows(data.get("boards")):
        if board.get("orphaned"):
            warnings.append(
                {
                    "code": "orphaned_board",
                    "entity_id": board.get("board_id"),
                    "detail": (
                        f"board '{board.get('board_id')}' points at workspace "
                        f"'{board.get('workspace_id')}' which no longer resolves; archive to repair"
                    ),
                }
            )
        for card_id in board.get("conflict_card_ids") or []:
            warnings.append(
                {
                    "code": "board_card_conflict",
                    "entity_id": card_id,
                    "board_id": board.get("board_id"),
                    "detail": (
                        f"board card '{card_id}' has an unresolved realm-sync conflict; "
                        "resolve with `harness board resolve-conflict <card_id> --take local|remote`"
                    ),
                }
            )
    return warnings
