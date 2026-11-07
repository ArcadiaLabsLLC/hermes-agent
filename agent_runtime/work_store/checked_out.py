"""A local board's branch moves through the worktree that has it checked out, never under it.

``RT-CREATE-BRAIN-MOVES-CHECKED-OUT-BRANCH`` (found live 2026-11-06): a local slot's write committed in
hermes's worktree and then ran ``update-ref refs/heads/main`` while the user's own checkout had ``main``
checked out. The ref moved; that checkout's index and files did not, so its ``git status`` showed the new
brain as staged deletions. git's porcelain never moves a branch another worktree holds (``branch -f``
refuses "used by worktree"); ``update-ref`` is plumbing and does.

:func:`advance` is the one door a local write uses to move its branch:

- held by NO worktree (a bare-like default) → the compare-and-swap ``update-ref`` as before;
- checked out in a worktree → ``merge --ff-only`` IN that worktree, so its HEAD, index and files move
  together; git's two-way merge keeps every unrelated local change (staged, unstaged, untracked) and
  refuses when one is in the way, which is refused ``worktree_dirty`` naming the checkout;
- being rebased in a worktree (HEAD detached, the branch named by ``rebase-*/head-name``) → refused
  ``worktree_dirty``: moving it would break the user's rebase.

The compare-and-swap holds on the checkout arm too: the holder's HEAD must still be ``expected`` (else
``False`` and the writer replays), and ``--ff-only`` can never drop a commit.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from .reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = ["advance", "holder_of"]

Git = Callable[..., subprocess.CompletedProcess[str]]
_REBASE_HEADS = ("rebase-merge/head-name", "rebase-apply/head-name")
#: The fast-forward runs no hook of the user's repository (``post-merge`` would fire on it).
_NO_HOOKS = (f"core.hooksPath={os.devnull}",)


def _tail(text: str | None) -> str:
    return " ".join(str(text or "").split())[-200:]


def holder_of(git: Git, repo: Path, ref: str) -> tuple[Path, bool] | None:
    """``(worktree, rebasing)`` of the worktree of ``repo``'s clone holding ``ref``, or None.

    ``rebasing`` is True when that worktree is mid-rebase of ``ref`` (its HEAD is detached then).
    """

    done = git(["worktree", "list", "--porcelain"], repo=repo)
    if done.returncode != 0:
        raise WorkRefused(Reason.WORKTREE_FAILED, f"git worktree list: {_tail(done.stderr)}")
    for block in str(done.stdout or "").replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        if "worktree" not in fields or "bare" in fields:
            continue
        where = Path(fields["worktree"])
        if fields.get("branch") == ref:
            return where, False
        if "detached" in fields and _rebasing(git, where) == ref:
            return where, True
    return None


def _rebasing(git: Git, worktree: Path) -> str | None:
    for name in _REBASE_HEADS:
        done = git(["rev-parse", "--path-format=absolute", "--git-path", name], repo=worktree)
        path = Path(str(done.stdout or "").strip()) if done.returncode == 0 else None
        if path is not None and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    return None


def advance(git: Git, repo: Path, branch: str, commit: str, expected: str) -> bool:
    """Move ``refs/heads/<branch>`` of ``repo``'s clone from ``expected`` to ``commit`` (a child of it).

    True when ``commit`` is the branch's tip now; False when the branch moved meanwhile (the caller
    replays); :class:`WorkRefused` ``worktree_dirty`` when the checkout holding it cannot fast-forward.
    """

    ref = f"refs/heads/{branch}"
    held = holder_of(git, repo, ref)
    if held is None:
        return git(["update-ref", ref, commit, expected], repo=repo).returncode == 0
    checkout, rebasing = held
    if rebasing:
        raise WorkRefused(Reason.WORKTREE_DIRTY, f"{branch} is being rebased in {checkout}")
    head = git(["rev-parse", "-q", "--verify", "HEAD"], repo=checkout)
    if head.returncode != 0 or str(head.stdout).strip() != expected:
        return False
    merged = git(["merge", "--ff-only", "-q", commit], repo=checkout, config=_NO_HOOKS)
    if merged.returncode == 0:
        return True
    now = git(["rev-parse", "-q", "--verify", "HEAD"], repo=checkout)
    if now.returncode == 0 and str(now.stdout).strip() != expected:
        return False
    raise WorkRefused(Reason.WORKTREE_DIRTY,
                      f"{checkout} has {branch} checked out and cannot fast-forward: {_tail(merged.stderr)}")
