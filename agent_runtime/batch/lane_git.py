"""Where a batch lane works, in git (dispatcher plan §2.2 B5, §3.4): worktrees beside the clone, merges, the push.

A lane of batch ``B`` on slot ``S`` works in ``<clone's parent>/.worktrees/<clone name>-<B>-<lane>`` on branch
``q/<B>/<lane>``, cut from the tip of the slot's default branch, or from the branch of the last lane it is
sequenced after (``Lane.after``) on the same slot. The landing lane works in ``…-<B>-land`` on ``land/<B>``,
one per slot the batch touched, and merges each REPORTED lane's branch ``--no-ff`` in lane order. Every
place is derived from the batch alone, so a serve that restarted finds the same worktree; a worktree is
reused, never removed (a lane could resume in it). ``push_ff`` is the only write to a default branch:
fast-forward from the landing worktree's HEAD, after ``check_ff`` proved the tip is its ancestor.

Every git call goes through ``git_cmd.run_git``; a failure is a ``WorkRefused`` with a typed reason.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..work_store.reasons import Reason, WorkRefused
from .machine import Batch, LaneRecord, LaneState
from .planner import LaneKind

__layer__ = "stores"
__all__ = [
    "WORKTREES_DIR",
    "Clone",
    "LaneGit",
    "Site",
    "board_clone",
    "landing_branch",
    "landing_site",
    "lane_branch",
    "lane_site",
    "lane_slot",
    "slots_of",
    "worktree_beside",
]

#: The parent beside every clone that holds lane worktrees (``Dispatching a lane.md`` § 3).
WORKTREES_DIR = ".worktrees"
_TAIL = 400


@dataclass(frozen=True)
class Clone:
    """A slot's checkout on this machine and the branch a landing pushes."""

    path: Path
    default_branch: str = "main"
    #: No remote: the tip is the local branch and the push is an ``update-ref``.
    local: bool = False

    @property
    def tip(self) -> str:
        return self.default_branch if self.local else f"origin/{self.default_branch}"


@dataclass(frozen=True)
class Site:
    """One lane's place: the worktree it works in, its branch, and the ref it was cut from."""

    slot: str
    clone: Clone
    worktree: Path
    branch: str
    base: str

    @property
    def scratch(self) -> Path:
        return self.worktree.with_name(self.worktree.name + "-scratch")


def lane_branch(batch_id: str, lane_id: str) -> str:
    return f"q/{batch_id}/{lane_id}"


def landing_branch(batch_id: str) -> str:
    return f"land/{batch_id}"


def worktree_beside(clone: Path, batch_id: str, lane_id: str) -> Path:
    """``<clone's parent>/.worktrees/<clone name>-<batch>-<lane>``: beside the clone, never inside it."""

    root = clone.resolve()
    return root.parent / WORKTREES_DIR / f"{root.name}-{batch_id}-{lane_id}".lower()


def lane_slot(record: LaneRecord) -> str | None:
    """The slot a work lane's rows live in (its domain's), or None for the landing lane."""

    if record.lane.domain is not None:
        return record.lane.domain.slot
    rows = record.rows or record.lane.rows
    return rows[0].slot if rows else None


def slots_of(batch: Batch) -> list[str]:
    """Every slot the batch's work lanes touch, in lane order: the landing lands each."""

    return list(dict.fromkeys(slot for record in batch.lanes if (slot := lane_slot(record))))


def board_clone(workspace_id: str, slot: str) -> Clone:
    """The slot's checkout on this machine, from the workspace's boards; ``slot_unbound`` when it has none."""

    from ..work_store import board as boards_store

    found = next((b for b in boards_store.boards(workspace_id) if b.slot == slot), None)
    if found is None or found.checkout is None or not (found.checkout / ".git").exists():
        raise WorkRefused(Reason.SLOT_UNBOUND, slot)
    return Clone(found.checkout, found.default_branch, found.local)


def landing_site(clone: Clone, slot: str, batch_id: str) -> Site:
    return Site(slot, clone, worktree_beside(clone.path, batch_id, "land"), landing_branch(batch_id), clone.tip)


class LaneGit:
    """The git a lane's place needs, over one ``run`` (``git_cmd.run_git`` in production)."""

    def __init__(self, run: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> None:
        if run is None:
            from ..git_cmd import run_git as run
        self._run = run

    def _git(self, args: Sequence[str], repo: Path) -> subprocess.CompletedProcess[str]:
        return self._run(list(args), repo=repo, encoding="utf-8", errors="replace", timeout=300,
                         stdin=subprocess.DEVNULL)

    def _must(self, args: Sequence[str], reason: Reason, repo: Path) -> str:
        done = self._git(args, repo)
        if done.returncode != 0:
            raise WorkRefused(reason, f"git {args[0]}: {str(done.stderr or '').strip()[-_TAIL:]}")
        return str(done.stdout or "")

    def has_ref(self, repo: Path, ref: str) -> bool:
        return self._git(["rev-parse", "-q", "--verify", f"{ref}^{{commit}}"], repo).returncode == 0

    def fetch(self, clone: Clone) -> None:
        if not clone.local:
            self._must(["fetch", "-q", "origin", clone.default_branch], Reason.FETCH_FAILED, clone.path)

    def ensure(self, site: Site) -> bool:
        """The site's worktree on its branch; True when this call cut it, False when it already stood."""

        self._git(["worktree", "prune"], site.clone.path)
        if (site.worktree / ".git").exists():
            return False
        if site.worktree.exists() and any(site.worktree.iterdir()):
            raise WorkRefused(Reason.WORKTREE_FAILED, f"{site.worktree} exists and is not a worktree")
        site.worktree.parent.mkdir(parents=True, exist_ok=True)
        if self.has_ref(site.clone.path, f"refs/heads/{site.branch}"):
            args = ["worktree", "add", "-q", str(site.worktree), site.branch]
        else:
            args = ["worktree", "add", "-q", "-b", site.branch, str(site.worktree), site.base]
        self._must(args, Reason.WORKTREE_FAILED, site.clone.path)
        site.scratch.mkdir(parents=True, exist_ok=True)
        return True

    def commits(self, site: Site) -> tuple[str, ...]:
        """The lane's own commits, oldest first: ``base..branch`` (empty when the branch is gone)."""

        if not self.has_ref(site.clone.path, f"refs/heads/{site.branch}"):
            return ()
        done = self._git(["rev-list", "--reverse", f"{site.base}..{site.branch}"], site.clone.path)
        return tuple(line.strip() for line in str(done.stdout or "").splitlines() if line.strip()) \
            if done.returncode == 0 else ()

    def dirty(self, worktree: Path) -> bool:
        return bool(self._must(["status", "--porcelain"], Reason.WORKTREE_DIRTY, worktree).strip())

    def head(self, worktree: Path) -> str:
        return self._must(["rev-parse", "HEAD"], Reason.BRANCH_MISSING, worktree).strip()

    def merge(self, worktree: Path, branch: str) -> bool:
        """``merge --no-ff`` of ``branch``; a conflict is aborted and answered False (the lane resolves it)."""

        if self._git(["merge", "--no-ff", "--no-edit", "-q", branch], worktree).returncode == 0:
            return True
        self._git(["merge", "--abort"], worktree)
        return False

    def check_ff(self, site: Site) -> str:
        """The landing HEAD, once the tree is clean and the fetched tip is its ancestor; else a refusal."""

        self.fetch(site.clone)
        if self.dirty(site.worktree):
            raise WorkRefused(Reason.WORKTREE_DIRTY, str(site.worktree))
        head = self.head(site.worktree)
        if self._git(["merge-base", "--is-ancestor", site.clone.tip, head], site.worktree).returncode != 0:
            raise WorkRefused(Reason.PUSH_CONTENDED, f"{site.clone.tip} moved since {site.branch} merged; land again")
        return head

    def push_ff(self, site: Site, head: str) -> None:
        """``head`` onto the default branch, fast-forward only (never ``--force``)."""

        target = f"refs/heads/{site.clone.default_branch}"
        if site.clone.local:
            old = self._must(["rev-parse", target], Reason.BRANCH_MISSING, site.clone.path).strip()
            self._must(["update-ref", target, head, old], Reason.PUSH_REFUSED, site.clone.path)
            return
        self._must(["push", "-q", "origin", f"{head}:{target}"], Reason.PUSH_REFUSED, site.worktree)


def lane_site(git: LaneGit, clone: Clone, slot: str, batch: Batch, record: LaneRecord) -> Site:
    """A work lane's site: cut from the last same-slot lane it follows whose branch exists, else the tip."""

    before = [lane_branch(batch.id, other.id) for other in batch.lanes
              if other.id in record.lane.after and lane_slot(other) == slot and other.state is not LaneState.STOPPED]
    base = next((b for b in reversed(before) if git.has_ref(clone.path, f"refs/heads/{b}")), clone.tip)
    if record.lane.kind is LaneKind.LANDING:
        raise WorkRefused(Reason.STATE_TRANSITION_INVALID, "the landing lane's sites are landing_site's")
    return Site(slot, clone, worktree_beside(clone.path, batch.id, record.id), lane_branch(batch.id, record.id), base)
