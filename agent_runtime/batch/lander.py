"""``GitLander`` — ``runtime.batch.approve``'s push (dispatcher plan §3.2 ``LANDED``, §3.3).

The landing lane merged the batch into ``land/<batch>`` per slot and its gate came back green; the
operator approves; this pushes each landing worktree's HEAD onto its repo's default branch,
FAST-FORWARD only. Every slot is checked first (clean tree, the fetched tip an ancestor of HEAD), so a
refusal pushes nothing; a tip that moved since the merge refuses ``push_contended`` (land again). The
caller (``BatchDispatcher.approve``) holds ``locks.batch_landing_lock`` around it: one landing per machine.
"""

from __future__ import annotations

from collections.abc import Callable

from ..work_store.reasons import Reason, WorkRefused
from .lane_git import Clone, LaneGit, board_clone, landing_site, slots_of
from .machine import Batch

__layer__ = "lanes"
__all__ = ["GitLander"]


class GitLander:
    def __init__(self, *, clone_of: Callable[[str, str], Clone] = board_clone, git: LaneGit | None = None) -> None:
        self._clone_of = clone_of
        self._git = git or LaneGit()

    def push(self, batch: Batch) -> str:
        """Push every slot's landing HEAD fast-forward; the landing SHA (``slot=sha`` pairs for several slots)."""

        sites = [landing_site(self._clone_of(batch.workspace_id, slot), slot, batch.id) for slot in slots_of(batch)]
        missing = [site.slot for site in sites if not (site.worktree / ".git").exists()]
        if not sites or missing:
            raise WorkRefused(Reason.WORKTREE_FAILED, f"{batch.id}: no landing worktree for {missing or 'any slot'}")
        heads = [(site, self._git.check_ff(site)) for site in sites]
        for site, head in heads:
            self._git.push_ff(site, head)
        return heads[0][1] if len(heads) == 1 else " ".join(f"{site.slot}={head}" for site, head in heads)
