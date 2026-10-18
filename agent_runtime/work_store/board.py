"""A workspace's todo boards: one per live repo slot, read from the slot's checkout (plan §2, §6.1).

A board is a slot plus where its brain's queue notes live. The rows are read straight from the
``type: queue`` notes under ``<read root>/<brain dir>/``; nothing is copied. Tasks are keyed by
``(slot, ID)``, so two repos may each carry an ``RT-A``. ``read_roots`` lets W2 point a board at
hermes's own worktree of the slot (§5 steps 1–3) instead of the operator's checkout.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workspace_slots import bound_path, live_slots, load_document
from .grammar import Row, Status, is_queue, parse_note

__layer__ = "stores"
__all__ = [
    "DEFAULT_BRAIN_SLOT",
    "Board",
    "boards",
    "brain_dir_of",
    "has_brain_here",
    "ids_in_brain",
    "needs_default_brain",
    "notes",
    "ready",
    "rows",
]

#: The slot name the auto-created default brain is declared under (§4).
DEFAULT_BRAIN_SLOT = "brain"
_BRAIN_GLOBS = ("*_Brain/20 — Active Initiatives", "*_brain/20 — Active Initiatives")


@dataclass(frozen=True)
class Board:
    workspace_id: str
    slot: str
    read_root: Path | None
    brain_dir: str | None
    default_branch: str
    clone_url: str | None
    local: bool
    bound_here: bool
    is_default: bool


def brain_dir_of(root: Path | None, slot: dict[str, Any]) -> str | None:
    """The slot's queue directory, relative and posix: the pinned ``context.brain_dir`` first, else discovered."""

    pinned = (slot.get("context") or {}).get("brain_dir")
    if isinstance(pinned, str) and pinned:
        return pinned
    if root is None or not root.is_dir():
        return None
    found = [match for pattern in _BRAIN_GLOBS for match in sorted(root.glob(pattern)) if match.is_dir()]
    return found[0].relative_to(root).as_posix() if found else None


def _board(workspace_id: str, name: str, slot: dict[str, Any], read_roots: Mapping[str, Path]) -> Board:
    repo = slot.get("repo") or {}
    path = bound_path(name)
    bound_here = bool(path and path.is_dir())
    read_root = read_roots.get(name) or (path if bound_here else None)
    local = repo.get("local") is True
    return Board(
        workspace_id=workspace_id,
        slot=name,
        read_root=read_root,
        brain_dir=brain_dir_of(read_root, slot),
        default_branch=str(repo.get("default_branch") or "main"),
        clone_url=repo.get("clone_url") or None,
        local=local,
        bound_here=bound_here,
        is_default=local and name == DEFAULT_BRAIN_SLOT,
    )


def boards(workspace_id: str, *, read_roots: Mapping[str, Path] | None = None) -> list[Board]:
    """One board per live slot of the workspace, bound here or not (an unbound one is listed, never read)."""

    slots = live_slots(load_document(workspace_id))
    return [_board(workspace_id, name, slots[name], read_roots or {}) for name in sorted(slots)]


def notes(board: Board) -> list[Path]:
    """The board's ``type: queue`` notes, sorted; none when it has no read root or no brain."""

    if board.read_root is None or board.brain_dir is None:
        return []
    directory = board.read_root / board.brain_dir
    if not directory.is_dir():
        return []
    return [path for path in sorted(directory.glob("*.md")) if is_queue(path.read_text(encoding="utf-8"))]


def _board_rows(board: Board) -> list[Row]:
    root = board.read_root or Path()
    return [
        row
        for path in notes(board)
        for row in parse_note(path.read_text(encoding="utf-8"), slot=board.slot, note=path.relative_to(root).as_posix())
    ]


def rows(
    workspace_id: str,
    *,
    status: Status | None = None,
    slot: str | None = None,
    assignee: str | None = None,
    read_roots: Mapping[str, Path] | None = None,
) -> list[Row]:
    """Every row on the workspace's boards, filtered by status, slot and assignee token."""

    found = [row for board in boards(workspace_id, read_roots=read_roots)
             if slot is None or board.slot == slot for row in _board_rows(board)]
    return [
        row for row in found
        if (status is None or row.status is status)
        and (assignee is None or (row.assignee is not None and row.assignee.token == assignee))
    ]


def ready(workspace_id: str, *, read_roots: Mapping[str, Path] | None = None) -> list[Row]:
    """The rows a claim may take: ``READY`` and not ``TAKEN``."""

    return [row for row in rows(workspace_id, status=Status.READY, read_roots=read_roots) if row.taken is None]


def ids_in_brain(board: Board) -> set[str]:
    """Every row ID across the board's queue notes (an ID is unique within a brain)."""

    return {row.ref.id for row in _board_rows(board) if row.ref.id}


def has_brain_here(board: Board) -> bool:
    """The board is bound here and its brain directory exists in what it reads."""

    return bool(board.bound_here and board.read_root and board.brain_dir and (board.read_root / board.brain_dir).is_dir())


def needs_default_brain(found: list[Board]) -> bool:
    """True when no live slot's bound checkout has a brain directory — the §4 trigger."""

    return not any(has_brain_here(board) for board in found)
