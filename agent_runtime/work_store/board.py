"""A workspace's todo boards: one per live repo slot, read from the slot's checkout (plan §2, §6.1).

A board is a slot plus where its brain's queue notes live. The rows are read straight from the
``type: queue`` notes under ``<read root>/<brain dir>/``; nothing is copied. Tasks are keyed by
``(slot, ID)``, so two repos may each carry an ``RT-A``. ``read_roots`` lets W2 point a board at
hermes's own worktree of the slot (§5 steps 1–3) instead of the operator's checkout.

The default brain is NOT a declared slot (owner ruling 2026-10-18, ``RT-WORK-DEFAULT-BRAIN-REALM``):
it is a machine-local binding, ``<work_workspace_dir(ws)>/default_brain.json``, listed as slot
``brain`` until the move into a repo brain retires it (``agent_runtime/work/store.py::
normalize_default_brain``). Promotion (``default_brain.promote_default_brain``, p10-work §2.5) writes
``remote_url`` and a ``declaration``: while it is ``pending`` (a server-bound realm; the Launcher's next
credentialed ``slots.declare`` carries the entry) the default board is listed with its remote
(``local=False``: the writer fetches and pushes); once ``declared`` the declared slot ``brain`` lists it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..workspace_slots import bound_path, live_slots, load_document
from .grammar import Row, Status, is_queue, parse_note

__layer__ = "stores"
__all__ = [
    "BINDING_FILE",
    "DEFAULT_BRAIN_QUEUE_DIR",
    "DEFAULT_BRAIN_SLOT",
    "Board",
    "binding_path",
    "board_rows",
    "boards",
    "brain_dir_of",
    "declaration_state",
    "declared_boards",
    "default_board",
    "first_repo_brain",
    "has_brain_here",
    "ids_in_brain",
    "needs_default_brain",
    "notes",
    "read_binding",
    "ready",
    "rows",
]

#: The slot name the machine-local default brain is listed under (§4, ruling 2026-10-18).
DEFAULT_BRAIN_SLOT = "brain"
DEFAULT_BRAIN_QUEUE_DIR = "Work_Brain/20 — Active Initiatives"
BINDING_FILE = "default_brain.json"
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
    #: The checkout git runs against: the slot's bound path, or the default brain's directory.
    checkout: Path | None = None


def brain_dir_of(root: Path | None, slot: dict[str, Any]) -> str | None:
    """The slot's queue directory, relative and posix: the pinned ``context.brain_dir`` first, else discovered."""

    pinned = (slot.get("context") or {}).get("brain_dir")
    if isinstance(pinned, str) and pinned:
        return pinned
    if root is None or not root.is_dir():
        return None
    found = [match for pattern in _BRAIN_GLOBS for match in sorted(root.glob(pattern)) if match.is_dir()]
    return found[0].relative_to(root).as_posix() if found else None


def _slot_board(workspace_id: str, name: str, slot: dict[str, Any], read_roots: Mapping[str, Path]) -> Board:
    repo = slot.get("repo") or {}
    path = bound_path(name, workspace_id=workspace_id)
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
        is_default=False,
        checkout=path if bound_here else None,
    )


def declared_boards(workspace_id: str, *, read_roots: Mapping[str, Path] | None = None) -> list[Board]:
    """One board per live DECLARED slot, sorted by name, bound here or not (an unbound one is never read)."""

    slots = live_slots(load_document(workspace_id))
    return [_slot_board(workspace_id, name, slots[name], read_roots or {}) for name in sorted(slots)]


def first_repo_brain(workspace_id: str) -> Board | None:
    """The first declared slot BY NAME whose bound checkout carries a brain.

    The owner's rule is "the first bound slot in declaration order", but the slot document is keyed by
    name and stored sorted, and every ``declare`` stamps one ``declared_at`` on the whole set, so the
    name order is the only order the store records.
    """

    return next((board for board in declared_boards(workspace_id) if has_brain_here(board)), None)


def binding_path(workspace_id: str) -> Path:
    return paths.work_workspace_dir(workspace_id) / BINDING_FILE


def read_binding(workspace_id: str) -> dict[str, Any] | None:
    """The machine-local default-brain record, or None when there is none (or it is unreadable)."""

    try:
        record = json.loads(binding_path(workspace_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("path") else None


def default_board(workspace_id: str, *, read_roots: Mapping[str, Path] | None = None) -> Board | None:
    """The default brain's board while its binding is live (not retired into a repo brain, not declared)."""

    record = read_binding(workspace_id)
    if record is None or record.get("retired_into") or declaration_state(record) == "declared":
        return None
    root = Path(str(record["path"]))
    if not (root / ".git").exists():
        return None
    return Board(
        workspace_id=workspace_id,
        slot=DEFAULT_BRAIN_SLOT,
        read_root=(read_roots or {}).get(DEFAULT_BRAIN_SLOT) or root,
        brain_dir=str(record.get("brain_dir") or DEFAULT_BRAIN_QUEUE_DIR),
        default_branch=str(record.get("default_branch") or "main"),
        clone_url=record.get("remote_url") or None,
        local=not record.get("remote_url"),
        bound_here=True,
        is_default=True,
        checkout=root,
    )


def declaration_state(record: Mapping[str, Any] | None) -> str | None:
    """The promoted default brain's slot declaration: ``declared`` / ``pending``, or None before promotion."""

    declaration = (record or {}).get("declaration")
    return str(declaration.get("state")) if isinstance(declaration, Mapping) and declaration.get("state") else None


def boards(workspace_id: str, *, read_roots: Mapping[str, Path] | None = None) -> list[Board]:
    """The declared boards, then the default brain's while its binding is live."""

    found = declared_boards(workspace_id, read_roots=read_roots)
    default = default_board(workspace_id, read_roots=read_roots)
    return [*found, default] if default is not None else found


def notes(board: Board) -> list[Path]:
    """The board's ``type: queue`` notes, sorted; none when it has no read root or no brain."""

    if board.read_root is None or board.brain_dir is None:
        return []
    directory = board.read_root / board.brain_dir
    if not directory.is_dir():
        return []
    return [path for path in sorted(directory.glob("*.md")) if is_queue(path.read_text(encoding="utf-8"))]


def board_rows(board: Board) -> list[Row]:
    """Every row of the board's queue notes, keyed by its slot and the note's path under the read root."""

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
             if slot is None or board.slot == slot for row in board_rows(board)]
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

    return {row.ref.id for row in board_rows(board) if row.ref.id}


def has_brain_here(board: Board) -> bool:
    """The board is bound here and its brain directory exists in what it reads."""

    return bool(board.bound_here and board.read_root and board.brain_dir and (board.read_root / board.brain_dir).is_dir())


def needs_default_brain(found: list[Board]) -> bool:
    """True when no board bound here has a brain directory — the §4 trigger (pass ``declared_boards``)."""

    return not any(has_brain_here(board) for board in found)
