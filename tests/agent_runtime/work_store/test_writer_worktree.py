"""Hermes's worktree is keyed by the CHECKOUT it is cut from, not by the slot name.

Plan ``docs/agent-runtime-harness/planned/work-slot-roots-per-workspace-2026-10-21.md`` §4
(``RT-WORK-WORKTREE-KEYED-BY-SLOT``): the default brain and a declared slot ``brain`` over two
repositories used to share ``worktrees/brain``, so each alternating write recreated it. Real git, two
local brains, no remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runtime.git_cmd import run_git
from agent_runtime.work_store.board import DEFAULT_BRAIN_QUEUE_DIR, DEFAULT_BRAIN_SLOT, Board
from agent_runtime.work_store.default_brain import QUEUE_NOTE, skeleton
from agent_runtime.work_store.grammar import Op, RowRef
from agent_runtime.work_store.writer import OPERATOR, RowOp, Writer, checkout_token

NOTE = f"{DEFAULT_BRAIN_QUEUE_DIR}/{QUEUE_NOTE}"
ID = ("-c", "user.name=t", "-c", "user.email=t@t.invalid")


def brain_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    skeleton(root)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", *ID, "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", *ID, "-C", str(root), "commit", "-q", "-m", "seed"], check=True)
    return root


def local_board(workspace: str, root: Path, *, is_default: bool) -> Board:
    return Board(workspace_id=workspace, slot=DEFAULT_BRAIN_SLOT, read_root=root, brain_dir=DEFAULT_BRAIN_QUEUE_DIR,
                 default_branch="main", clone_url=None, local=True, bound_here=True, is_default=is_default,
                 checkout=root)


def counting(adds: list[list[str]]):
    def run(args, **kwargs):
        if list(args[:2]) == ["worktree", "add"]:
            adds.append(list(args))
        return run_git(args, **kwargs)
    return run


def append(n: int) -> RowOp:
    row_id = f"WT-{n:02d}"
    return RowOp(RowRef(DEFAULT_BRAIN_SLOT, NOTE, row_id), Op.APPEND, OPERATOR, f"wt-{n}",
                 {"row": f"- **`{row_id}` — write {n}** · READY 2026-10-21"})


def test_two_boards_over_one_checkout_share_one_worktree(workspace, tmp_path):
    root = brain_repo(tmp_path / "brain")
    default = Writer(local_board(workspace, root, is_default=True), machine_id="m1")
    declared = Writer(local_board(workspace, root, is_default=False), machine_id="m1")
    assert default.worktree == declared.worktree
    assert default.worktree.name == f"brain-{checkout_token(root)}" and len(checkout_token(root)) == 12


def test_alternating_writes_over_two_checkouts_cut_exactly_two_worktrees(workspace, tmp_path):
    """Killing mutation: keying the worktree by slot only — every alternation recreates it (10 adds)."""

    boards = [local_board(workspace, brain_repo(tmp_path / "default"), is_default=True),
              local_board(workspace, brain_repo(tmp_path / "declared"), is_default=False)]
    adds: list[list[str]] = []
    for n in range(10):
        receipt = Writer(boards[n % 2], machine_id="m1", run=counting(adds)).apply(append(n))
        assert receipt.commit
    assert len(adds) == 2
    for index, board in enumerate(boards):
        text = run_git(["show", f"main:{NOTE}"], repo=board.checkout).stdout
        assert all(f"`WT-{n:02d}`" in text for n in range(index, 10, 2))


def test_a_worktree_whose_checkout_was_recloned_is_recreated_once_with_a_receipt(workspace, tmp_path, caplog):
    """W2: the moved-checkout arm. Killing mutation: dropping the ``work.worktree_stale`` receipt."""

    import logging
    import os
    import shutil
    import stat

    caplog.set_level(logging.INFO, logger="agent_runtime.work_store.receipts")
    root = tmp_path / "brain"
    board = local_board(workspace, brain_repo(root), is_default=False)
    adds: list[list[str]] = []
    first = Writer(board, machine_id="m1", run=counting(adds))
    first.apply(append(1))
    shutil.rmtree(root, onerror=lambda func, path, _exc: (os.chmod(path, stat.S_IWRITE), func(path)))
    brain_repo(root)  # the same path, a new repository: the old worktree's admin dir is gone
    second = Writer(board, machine_id="m1", run=counting(adds))
    assert second.worktree == first.worktree
    second.apply(append(2))
    second.apply(append(3))
    assert len(adds) == 2
    stale = [r.getMessage() for r in caplog.records if '"kind": "work.worktree_stale"' in r.getMessage()]
    assert len(stale) == 1 and '"slot": "brain"' in stale[0]
