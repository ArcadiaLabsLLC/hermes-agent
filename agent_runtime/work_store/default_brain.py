"""The default brain — a workspace whose repos carry no brain still has a todo board (plan §4).

``ensure_default_brain`` writes a two-note skeleton under ``paths.default_brain_dir(ws)``, makes
it a git repository with one commit under hermes's own per-machine identity (``-c`` pairs, never
``git config``), declares it as ONE local slot ``brain`` (``workspace_slots.declare_local_slot``,
the other slots untouched) and binds it here. It is local-only: no remote, nothing pushed.

**Server-bound realms refuse.** The publish right is checked first
(``workspace_slots.require_publish_right(ws, None)``): a workspace in no realm and a server-less
realm pass; a server-bound realm refuses ``needs_publish_right`` because the auto-create never
holds the realm credential. Whether hermes may ever auto-declare there is the open owner decision
``RT-WORK-DEFAULT-BRAIN-REALM`` (``Harness_Brain/20 — Active Initiatives/runtime-queue.md``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import paths
from ..workspace_slots import (
    REASON_MACHINE_UNIDENTIFIED,
    REASON_REALM_PUBLISH_DENIED,
    SlotRefused,
    declare_local_slot,
    live_slots,
    load_document,
    machine_id,
    require_publish_right,
)
from .board import DEFAULT_BRAIN_SLOT, Board, boards, has_brain_here, needs_default_brain
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["IDENTITY_PAIRS", "QUEUE_TEMPLATE", "TODO_TEMPLATE", "ensure_default_brain", "skeleton"]

BRAIN_FOLDER = "Work_Brain"
QUEUE_DIR = f"{BRAIN_FOLDER}/20 — Active Initiatives"
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


def _git(args: list[str], *, root: Path, machine: str, reason: Reason) -> str:
    from ..git_cmd import run_git

    done = run_git(args, repo=root, config=IDENTITY_PAIRS(machine), timeout=60, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise WorkRefused(reason, f"git {args[0]}: {str(done.stderr or '').strip()[-200:]}")
    return str(done.stdout or "")


def _commit_skeleton(root: Path, workspace_id: str, machine: str) -> None:
    """``init`` (once) → ``add -A`` → ``commit`` when anything is staged; no remote, ever."""

    if not (root / ".git").exists():
        _git(["init", "-q", "-b", "main"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    _git(["add", "-A"], root=root, machine=machine, reason=Reason.COMMIT_FAILED)
    if _git(["status", "--porcelain"], root=root, machine=machine, reason=Reason.COMMIT_FAILED).strip():
        _git(["commit", "-q", "-m", f"work: default brain for {workspace_id}"], root=root, machine=machine,
             reason=Reason.COMMIT_FAILED)


def _preconditions(workspace_id: str) -> str:
    """This machine's id, after the git door and the publish right; typed refusals otherwise."""

    from ..loop_tool_lifecycles import shipped

    if not shipped("agent_runtime.git_cmd"):
        raise WorkRefused(Reason.GIT_UNAVAILABLE, "git is switched off in this bundle")
    try:
        require_publish_right(workspace_id, None)
    except SlotRefused as exc:
        if exc.reason != REASON_REALM_PUBLISH_DENIED:
            raise
        raise WorkRefused(Reason.NEEDS_PUBLISH_RIGHT, exc.detail) from exc
    try:
        return machine_id()
    except SlotRefused as exc:
        raise WorkRefused(Reason.MACHINE_UNIDENTIFIED, exc.detail or REASON_MACHINE_UNIDENTIFIED) from exc


def _brain_board(workspace_id: str) -> Board:
    return next(board for board in boards(workspace_id) if board.slot == DEFAULT_BRAIN_SLOT)


def ensure_default_brain(workspace_id: str, *, issued_at: str) -> Board:
    """The board a workspace's work lands on, creating the default brain only when it has none.

    Idempotent: a live ``brain`` slot returns its board. A workspace with a slot whose bound
    checkout carries a brain gets no default brain; that board is returned instead.
    """

    if DEFAULT_BRAIN_SLOT in live_slots(load_document(workspace_id)):
        return _brain_board(workspace_id)
    found = boards(workspace_id)
    if not needs_default_brain(found):
        return next(board for board in found if has_brain_here(board))
    machine = _preconditions(workspace_id)
    root = paths.default_brain_dir(workspace_id)
    root.mkdir(parents=True, exist_ok=True)
    skeleton(root)
    _commit_skeleton(root, workspace_id, machine)
    declare_local_slot(workspace_id, DEFAULT_BRAIN_SLOT, path=str(root), issued_at=issued_at, machine=machine)
    return _brain_board(workspace_id)
