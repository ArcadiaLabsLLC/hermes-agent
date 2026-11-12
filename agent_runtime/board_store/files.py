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
from ..errors import CardAmbiguous, NotFound
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


#: Where one board folder can hold a copy of a card: live, archived, or as an
#: unresolved conflict sidecar.
_CARD_FOLDERS = ("cards", "archive", "conflicts")


def boards_holding_card(card_id: str) -> dict[str, tuple[str, ...]]:
    """``board_id -> the folders of it that hold this card id``, over every board."""

    root = paths.boards_root()
    if not root.exists():
        return {}
    name = f"{paths.safe_path_token(card_id)}.json"
    held: dict[str, tuple[str, ...]] = {}
    for child in sorted(root.iterdir()):
        folders = tuple(folder for folder in _CARD_FOLDERS if (child / folder / name).exists())
        if folders:
            held[child.name] = folders
    return held


def _board_of_unnamed_card(card_id: str, folder: str) -> str | None:
    """The ONE board a verb that named no board may act on, when that board
    holds the card in ``folder``; ``None`` when it does not.

    One card id on two boards is refused (:class:`CardAmbiguous`) whichever
    folders hold it: with a live copy on one board and an archived twin on the
    other, an unnamed edit would otherwise land on the live one and an unnamed
    restore on the archived one — each "the only possible" target, and each
    possibly the copy the caller is not looking at.
    """

    held = boards_holding_card(card_id)
    if len(held) > 1:
        raise CardAmbiguous(card_id, tuple(held))
    for board_id, folders in held.items():
        if folder in folders:
            return board_id
    return None


def locate_card(card_id: str, *, board_id: str | None = None, allow_missing: bool = False) -> tuple[str | None, Any]:
    """``(board_id, path)`` of a LIVE card. A caller that names the board gets
    that board or nothing; one that names none gets the card's only board, and
    :class:`CardAmbiguous` when two boards hold the id."""

    if not board_id:
        board_id = _board_of_unnamed_card(card_id, "cards")
        if board_id is None:
            if allow_missing:
                return None, None
            raise NotFound(f"card:{card_id}")
    path = paths.board_card_path(board_id, card_id)
    if path.exists():
        return board_id, path
    if allow_missing:
        return board_id, None
    raise NotFound(f"card:{card_id}")


def board_id_of_archived_card(card_id: str) -> str | None:
    return _board_of_unnamed_card(card_id, "archive")


def board_id_of_conflict(card_id: str) -> str | None:
    return _board_of_unnamed_card(card_id, "conflicts")


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
    patch: Callable[[BoardCard], None] | None = None,
) -> None:
    """Archive ``card`` under the caller's ``board_lock``.

    ``patch`` is the store's ``board_card`` producer
    (``patches.emit_card_remove``), called after every file write and BEFORE
    the paired ``board.card.archived`` — the lock is what orders the two.
    ``None`` for the silent realm-pull arm, which appends no event either.
    """

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
    if patch is not None:
        patch(card)
    if emit is not None:
        emit(
            "board.card.archived",
            board_id=board.board_id,
            card_id=card.card_id,
            reason=reason,
            column_id=card.column_id,
        )
