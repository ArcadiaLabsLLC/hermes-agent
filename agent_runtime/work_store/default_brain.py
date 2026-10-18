"""The default brain — a workspace whose repos carry no brain still has a todo board (plan §4).

``ensure_default_brain`` writes a two-note skeleton under ``paths.default_brain_dir(ws)``, makes
it a git repository with one commit under hermes's own per-machine identity (``-c`` pairs, never
``git config``) and records a MACHINE-LOCAL binding, ``board.binding_path(ws)``
(``{slot, path, brain_dir, default_branch, created_at, machine, remote_url, retired_into}``). It is
not a declared slot in the realm-synced slot document, so it works the same in every realm and
never needs the realm publish right (owner ruling 2026-10-18 on ``RT-WORK-DEFAULT-BRAIN-REALM``).
It is local-only: no remote, nothing pushed.

When a repo slot with a brain is bound, ``agent_runtime/work/store.py::normalize_default_brain``
moves the open rows into that brain and retires the binding (``retire_binding``). Promoting the
default brain to a declared slot with a remote is the later lane ``RT-WORK-DEFAULT-BRAIN-REMOTE``
(``promote_default_brain`` is its door, not built).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, NoReturn

from .. import paths
from ..workspace_slots import REASON_MACHINE_UNIDENTIFIED, SlotRefused, machine_id
from .board import (
    DEFAULT_BRAIN_QUEUE_DIR,
    DEFAULT_BRAIN_SLOT,
    Board,
    binding_path,
    declared_boards,
    default_board,
    has_brain_here,
    needs_default_brain,
    read_binding,
)
from .reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = [
    "IDENTITY_PAIRS",
    "QUEUE_TEMPLATE",
    "TODO_TEMPLATE",
    "ensure_default_brain",
    "promote_default_brain",
    "retire_binding",
    "skeleton",
]

BRAIN_FOLDER = "Work_Brain"
QUEUE_DIR = DEFAULT_BRAIN_QUEUE_DIR
QUEUE_NOTE = "work-queue.md"

TODO_TEMPLATE = """---
type: moc
tags: [moc, work]
---

# TODO

The master pointer list; it holds no rows. This workspace's tasks are the rows of
[[work-queue]] (`20 — Active Initiatives/work-queue.md`).

```dataview
TABLE program, status FROM "Work_Brain/20 — Active Initiatives" WHERE type = "queue"
```
"""

QUEUE_TEMPLATE = """---
type: queue
program: work
status: open
tags: [queue, program/work]
---

# Work queue

Row grammar (Harness_Brain ADR 0011, the launcher's ADR 0025): `- **`<ID>` — <title>** · … · <status>`,
one line, a unique ID, EXACTLY ONE of `READY <date>` / `BLOCKED <date>: <reason> — …` /
`DEFERRED <date>: …` / `NEEDS PLAN <date>: …`; a claim is `**TAKEN <date> <who>**`.
"""

def IDENTITY_PAIRS(machine: str) -> tuple[str, str]:
    """Hermes's own commit identity on this machine, as ``git -c`` pairs (never written to a config)."""

    return ("user.name=Eternia Harness", f"user.email=harness+{machine}@eternia.local")


def skeleton(root: Path) -> list[Path]:
    """Write the two notes under ``root`` (an existing note is left as it is); the paths, TODO first."""

    notes = [(root / BRAIN_FOLDER / "TODO.md", TODO_TEMPLATE), (root / QUEUE_DIR / QUEUE_NOTE, QUEUE_TEMPLATE)]
    for path, text in notes:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8", newline="\n")
    return [path for path, _ in notes]


def _brain_git(args: list[str], *, root: Path, machine: str, reason: Reason) -> str:
    from ..git_cmd import run_git

    done = run_git(args, repo=root, config=IDENTITY_PAIRS(machine), timeout=60, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise WorkRefused(reason, f"git {args[0]}: {str(done.stderr or '').strip()[-200:]}")
    return str(done.stdout or "")


def _commit_skeleton(root: Path, workspace_id: str, machine: str) -> None:
    """``init`` (once) → ``add -A`` → ``commit`` when anything is staged; no remote, ever."""

    if not (root / ".git").exists():
        _brain_git(["init", "-q", "-b", "main"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    _brain_git(["add", "-A"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    if _brain_git(["status", "--porcelain"], root=root, machine=machine, reason=Reason.COMMIT_FAILED).strip():
        _brain_git(["commit", "-q", "-m", f"work: default brain for {workspace_id}"], root=root, machine=machine,
             reason=Reason.COMMIT_FAILED)


def this_machine() -> str:
    """This machine's id (the commit identity), refused ``machine_identity_unavailable`` as a Work refusal;
    the one owner of that wrapper (the batch dispatcher and the serve scheduler read it). Whether git is
    shipped is the lanes caller's check."""

    try:
        return machine_id()
    except SlotRefused as exc:
        raise WorkRefused(Reason.MACHINE_UNIDENTIFIED, exc.detail or REASON_MACHINE_UNIDENTIFIED) from exc


def _write_binding(workspace_id: str, record: dict[str, Any]) -> None:
    path = binding_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def retire_binding(workspace_id: str, *, into: str, at: str, moved: list[str]) -> None:
    """The default brain's rows now live in slot ``into``; the board stops listing it."""

    record = read_binding(workspace_id) or {}
    _write_binding(workspace_id, {**record, "retired_into": into, "retired_at": at, "moved": moved})


def promote_default_brain(workspace_id: str, *, remote_url: str) -> NoReturn:
    """Turn the default brain into a declared slot with a git remote — ``RT-WORK-DEFAULT-BRAIN-REMOTE``.

    NOT BUILT (NEEDS PLAN): the later lane creates the remote through a connected git account,
    writes ``remote_url`` into the binding and declares the slot. Until then it refuses ``not_built``.
    """

    raise WorkRefused(Reason.NOT_BUILT, "RT-WORK-DEFAULT-BRAIN-REMOTE: promoting the default brain is not built")


def ensure_default_brain(workspace_id: str, *, issued_at: str) -> Board:
    """The board a workspace's work lands on, creating the default brain only when it has none.

    A workspace whose declared slots carry a brain bound here gets no default brain; that board is
    returned instead. Idempotent: a live binding returns its board; a retired one (its rows moved
    into a repo brain that is no longer bound here) comes back live and empty.
    """

    found = declared_boards(workspace_id)
    if not needs_default_brain(found):
        return next(board for board in found if has_brain_here(board))
    root = paths.default_brain_dir(workspace_id)
    record = read_binding(workspace_id)
    if record is not None and (root / ".git").exists():
        if record.get("retired_into"):
            _write_binding(workspace_id, {**record, "retired_into": None, "retired_at": None})
        return _default(workspace_id)
    machine = this_machine()
    root.mkdir(parents=True, exist_ok=True)
    skeleton(root)
    _commit_skeleton(root, workspace_id, machine)
    _write_binding(workspace_id, {"slot": DEFAULT_BRAIN_SLOT, "path": str(root), "brain_dir": QUEUE_DIR,
                                  "default_branch": "main", "created_at": issued_at, "machine": machine,
                                  "remote_url": None, "retired_into": None})
    return _default(workspace_id)


def _default(workspace_id: str) -> Board:
    board = default_board(workspace_id)
    if board is None:
        raise WorkRefused(Reason.NO_BRAIN, "the default brain's binding did not read back")
    return board
