"""The board on disk: the two writers (``_write_board``, ``_write_card``), where a
card is (active / archived / conflict), the per-directory scans, the conflict
guard, and the locked archive step (``archive_card_locked``, which takes the
store's ``emit`` — or ``None`` for the silent edit-vs-remove arm).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..errors import NotFound
from ..models import Board, BoardCard
from ..serde import from_jsonable, read_json, to_jsonable
from ..store_conflicts import guard_no_conflict
from .models import ARCHIVED_LEDGER_CAP, CardScan, _safe_actor

__layer__ = "stores"




def _write_board(board: Board) -> None:
    atomic_json_write(paths.board_def_path(board.board_id), to_jsonable(board), indent=2, sort_keys=True)


def _write_card(card: BoardCard) -> None:
    atomic_json_write(paths.board_card_path(card.board_id, card.card_id), to_jsonable(card), indent=2, sort_keys=True)


def scan_card_dir(directory) -> CardScan:
    cards: list[BoardCard] = []
    unreadable = 0
    if not directory.exists():
        return CardScan([], 0)
    for path in directory.glob("*.json"):
        try:
            cards.append(from_jsonable(BoardCard, read_json(path)))
        except Exception:
            unreadable += 1
            continue
    return CardScan(cards, unreadable)


def scan_active_cards(board_id: str) -> CardScan:
    return scan_card_dir(paths.board_cards_dir(board_id))


def scan_archived_cards(board_id: str) -> CardScan:
    return scan_card_dir(paths.board_archive_dir(board_id))


def locate_card(card_id: str, *, board_id: str | None = None, allow_missing: bool = False) -> tuple[str | None, Any]:
    if board_id:
        path = paths.board_card_path(board_id, card_id)
        if path.exists():
            return board_id, path
        if allow_missing:
            return board_id, None
        raise NotFound(f"card:{card_id}")
    root = paths.boards_root()
    if root.exists():
        for child in root.iterdir():
            candidate = child / "cards" / f"{paths.safe_path_token(card_id)}.json"
            if candidate.exists():
                return child.name, candidate
    if allow_missing:
        return None, None
    raise NotFound(f"card:{card_id}")


def board_id_of_archived_card(card_id: str) -> str | None:
    root = paths.boards_root()
    if not root.exists():
        return None
    token = paths.safe_path_token(card_id)
    for child in root.iterdir():
        if (child / "archive" / f"{token}.json").exists():
            return child.name
    return None


def board_id_of_conflict(card_id: str) -> str | None:
    root = paths.boards_root()
    if not root.exists():
        return None
    token = paths.safe_path_token(card_id)
    for child in root.iterdir():
        if (child / "conflicts" / f"{token}.json").exists():
            return child.name
    return None


def card_path_active(board_id: str, card_id: str) -> bool:
    return paths.board_card_path(board_id, card_id).exists()


def guard_card_conflict(card: BoardCard) -> None:
    """Refuse a card write while the card has an unresolved conflict sidecar."""

    guard_no_conflict(
        paths.board_conflict_path(card.board_id, card.card_id), f"card_conflict:{card.card_id}"
    )


def archive_card_locked(
    board: Board,
    card: BoardCard,
    *,
    reason: str,
    updated_by: str,
    emit: Callable[..., None] | None,
    record_tombstone: bool = True,
) -> None:
    card.state = "archived"
    card.revision += 1
    card.updated_at = now()
    card.updated_by = _safe_actor(updated_by)
    atomic_json_write(paths.board_archived_card_path(board.board_id, card.card_id), to_jsonable(card), indent=2, sort_keys=True)
    active_path = paths.board_card_path(board.board_id, card.card_id)
    active_path.unlink(missing_ok=True)
    # The ONE line the diagnostic mode skips — see ``archive_card``'s
    # ``record_tombstone``. The archive copy above is written
    # unconditionally; only the realm-visible ledger entry is withheld,
    # because only that entry rides the published board def and is therefore
    # an assertion about the REALM rather than about this projection.
    if record_tombstone and card.card_id not in board.archived_card_ids:
        board.archived_card_ids = [*board.archived_card_ids, card.card_id][-ARCHIVED_LEDGER_CAP:]
        board.updated_at = now()
        _write_board(board)
    if emit is not None:
        emit(
            "board.card.archived",
            board_id=board.board_id,
            card_id=card.card_id,
            reason=reason,
            column_id=card.column_id,
        )
