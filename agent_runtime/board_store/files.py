"""The board on disk: the JSON reader, the two writers (``_write_board``,
``_write_card``), the conflict-sidecar archive step and the revision guard.
"""

from __future__ import annotations

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..errors import StaleRevision
from ..models import Board, BoardCard
from ..serde import to_jsonable

__layer__ = "stores"


def _read_json(path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _write_board(board: Board) -> None:
    atomic_json_write(paths.board_def_path(board.board_id), to_jsonable(board), indent=2, sort_keys=True)


def _write_card(card: BoardCard) -> None:
    atomic_json_write(paths.board_card_path(card.board_id, card.card_id), to_jsonable(card), indent=2, sort_keys=True)


def _archive_conflict_sidecar(board_id: str, card_id: str) -> None:
    sidecar_path = paths.board_conflict_path(board_id, card_id)
    if not sidecar_path.exists():
        return
    try:
        payload = _read_json(sidecar_path)
    except Exception:
        payload = {"card_id": card_id}
    payload["resolved_at"] = to_jsonable(now())
    dest = paths.board_conflicts_dir(board_id) / f"{paths.safe_path_token(card_id)}.resolved.json"
    atomic_json_write(dest, payload, indent=2, sort_keys=True)
    sidecar_path.unlink(missing_ok=True)


def _check_revision(current: int, expected: int | None) -> None:
    if expected is None:
        return
    if int(current) != int(expected):
        raise StaleRevision(f"stale_revision: expected {expected}, have {current}")
