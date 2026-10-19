"""``BatchLaneExecutor`` — a batch lane run the way the owner's lanes run (dispatcher plan §2.2 B5).

Behind the EXECUTOR contract (``work_store/executor.py``), over a ``PersonaTurnExecutor``:

1. ``start`` finds the lane by the run's request id (``BATCH-<id>:<lane>``) in the batch manifest, fetches
   the slot's clone, and cuts the lane's worktree beside it (``lane_git``): branch ``q/<batch>/<lane>`` from
   the tip, or from the branch of the lane it is sequenced after. The landing lane instead cuts
   ``land/<batch>`` per slot the batch touched and merges each REPORTED lane's branch ``--no-ff`` in order;
   a conflict is aborted and named in its brief for the persona to resolve.
2. The brief is the playbook's skeleton (``Dispatching a lane.md`` § The brief skeleton), at most
   ``BRIEF_MAX_LINES`` lines including the ``work_report`` ask, written to the lane's scratch directory
   and sent as the turn's message.
3. The persona's turn runs with ``run_workdir`` = the worktree (``mission_chat_workdir.with_run_override``):
   it does the work, runs the lane's own tests, commits on the lane branch and pushes that branch.
4. On settle the outcome carries the lane's commits read from git (``base..branch``; the landing's HEAD per
   slot) and goes to this executor's listeners (the dispatcher).
5. The landing lane's settle first runs the landing gate OFF the settle's thread (``gate.GateRunner``, the
   landing brief's ``tests``: ``planner.LANDING_GATE``) in each slot's landing worktree; the outcome then
   carries one ``GateReceipt`` per slot, and that — not the persona's verdict — decides green
   (row RT-BATCH-GATE-RECEIPT, owner ruling 2026-10-18).

Pushing a default branch is NOT this module's: that is ``lander.GitLander`` behind ``runtime.batch.approve``.
Receipts: ``batch.lane_site`` (where the lane works), ``batch.gate_started`` / ``batch.gate`` (the code-run
gate: command, exit code, summary line, SHA) beside the inner executor's ``work.exec_*``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from typing import Any

from ..work_store import receipts
from ..work_store.executor import Assignment, ExecutorKind, Outcome, Run, RunStatus, StopReason
from ..work_store.persona_turn import BRIEF_MAX_LINES, REPORT_CLOSING
from ..work_store.reasons import Reason, WorkRefused
from .gate import GateRunner
from .lane_git import (
    Clone, LaneGit, Site, board_clone, landing_site, lane_branch, lane_site, lane_slot, slots_of,
)
from .machine import Batch, LaneRecord, LaneState
from .manifest import ManifestStore, find_batch
from .planner import LANDING_GATE, LaneKind

__layer__ = "lanes"
__all__ = ["BatchLaneExecutor", "render_lane_brief"]

logger = logging.getLogger(__name__)

_RUN = "Run: the tests importing what you touched, `scripts/run_tests.sh -j 4`; never `-n`, never bare pytest over a directory."
_LAND_RUN = ("Gate: when you settle, the executor runs the landing gate here and records its receipt; "
             "your verdict is advisory. Fix a caused red as its own commit.")


def _clip(lines: Sequence[str], budget: int) -> list[str]:
    return list(lines) if len(lines) <= budget else [*lines[:budget - 1], "…"]


def render_lane_brief(a: Assignment, sites: Sequence[Site], *, landing: bool, merged: Sequence[str] = (),
                      conflicts: Sequence[str] = ()) -> str:
    """The lane's brief: the skeleton's fixed lines first, then rows / objective / inputs, then the report ask.

    Never longer than ``BRIEF_MAX_LINES``; what does not fit is clipped from the variable middle.
    """

    brief = a.brief
    objective = [line for line in brief.objective.splitlines() if line.strip()] or [brief.title]
    head = [f"{brief.title}: {objective[0]} Never push main."]
    head += [f"Worktree: {s.worktree} on branch {s.branch} (cut from {s.base}); work only there. "
             "If it is missing, stop and report blocked." for s in sites]
    head.append(f"Scratch: {sites[0].scratch}; set UV_CACHE_DIR={sites[0].scratch / 'uv-cache'}.")
    if landing:
        head.append("Merged --no-ff: " + (", ".join(merged) or "nothing"))
        head += [f"Conflicted, merge it by hand first: {', '.join(conflicts)}"] if conflicts else []
        head += [_LAND_RUN, "Do NOT push main: the push is the owner's approve."]
    else:
        head += [_RUN, f"Commits: MOVE and CHANGE never share one; `git push -u origin {sites[0].branch}` after each; "
                       "never main; never amend, force or stash; leave the worktree."]
    if brief.acceptance:
        head.append(f"Done when: {' '.join(brief.acceptance.split())[:300]}")
    body = ["Rows (slot · note · ID):", *_clip([f"- {r.slot} · {r.note} · {r.id}" for r in a.rows], 6)] if a.rows else []
    body += ["Objective:", *_clip(objective[1:] or objective, 10)]
    body += ["Inputs:", *_clip([f"- {item}" for item in brief.inputs], 8)] if brief.inputs else []
    body += ["Constraints:", *_clip([f"- {item}" for item in brief.constraints], 3)] if brief.constraints else []
    room = BRIEF_MAX_LINES - len(REPORT_CLOSING) - len(head)
    return "\n".join([*head, *_clip(body, max(room, 1)), *REPORT_CLOSING])


class BatchLaneExecutor:
    """A batch lane: a worktree beside the clone, the brief, one persona turn there (plan §2.2)."""

    kind = ExecutorKind.BATCH_LANE

    def __init__(
        self,
        *,
        inner: Any,
        manifests: ManifestStore,
        workspaces: Callable[[], Iterable[str]],
        clone_of: Callable[[str, str], Clone] = board_clone,
        git: LaneGit | None = None,
        gate: GateRunner | None = None,
    ) -> None:
        self._inner = inner
        self._manifests = manifests
        self._workspaces = workspaces
        self._clone_of = clone_of
        self._git = git or LaneGit()
        self._gate = gate or GateRunner(git=self._git)
        self._gate_threads: list[threading.Thread] = []
        self._callbacks: list[Callable[[Run, Outcome], None]] = []
        inner.on_settle(self._inner_settled)

    # ── the contract ─────────────────────────────────────────────────────

    def can_start(self, a: Assignment) -> Reason | None:
        return self._inner.can_start(a)

    def start(self, a: Assignment) -> Run:
        refusal = self.can_start(a)
        if refusal is not None:
            raise WorkRefused(refusal, a.persona_instance_id)
        batch, record = self._lane(a.request_id)
        landing = record.lane.kind is LaneKind.LANDING
        sites, merged, conflicts = self._land(batch) if landing else self._cut(batch, record)
        message = render_lane_brief(a, sites, landing=landing, merged=merged, conflicts=conflicts)
        (sites[0].scratch / "brief.md").write_text(message + "\n", encoding="utf-8", newline="\n")
        receipts.emit("batch.lane_site", batch_id=batch.id, lane=record.id, request_id=a.request_id,
                      worktrees=[str(s.worktree) for s in sites], branches=[s.branch for s in sites],
                      bases=[s.base for s in sites], merged=list(merged), conflicts=list(conflicts))
        return self._inner.start_from(a, {"batch_lane": record.id}, message=message, workdir=str(sites[0].worktree))

    def status(self, run_id: str) -> RunStatus:
        return self._inner.status(run_id)

    def stop(self, run_id: str, reason: StopReason) -> dict[str, Any]:
        return self._inner.stop(run_id, reason)

    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None:
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    # ── where a lane works ───────────────────────────────────────────────

    def _lane(self, request_id: str) -> tuple[Batch, LaneRecord]:
        batch_id, _sep, request = request_id.partition(":")
        found = find_batch(self._manifests, self._workspaces(), batch_id) if request else None
        if found is None:
            raise WorkRefused(Reason.BATCH_MISSING, request_id)
        batch = found[1]
        return batch, batch.lane(request.split(":")[0])

    def _work_site(self, batch: Batch, record: LaneRecord) -> Site:
        slot = lane_slot(record)
        if slot is None:
            raise WorkRefused(Reason.WORKTREE_FAILED, f"{batch.id} lane {record.id} names no row")
        return lane_site(self._git, self._clone_of(batch.workspace_id, slot), slot, batch, record)

    def _cut(self, batch: Batch, record: LaneRecord) -> tuple[list[Site], tuple[str, ...], tuple[str, ...]]:
        slot = lane_slot(record)
        if slot is not None:
            self._git.fetch(self._clone_of(batch.workspace_id, slot))
        site = self._work_site(batch, record)
        self._git.ensure(site)
        return [site], (), ()

    def _landing_sites(self, batch: Batch) -> list[Site]:
        sites = [landing_site(self._clone_of(batch.workspace_id, slot), slot, batch.id) for slot in slots_of(batch)]
        if not sites:
            raise WorkRefused(Reason.WORKTREE_FAILED, f"{batch.id} has no lane to land")
        return sites

    def _land(self, batch: Batch) -> tuple[list[Site], tuple[str, ...], tuple[str, ...]]:
        """Cut ``land/<batch>`` per slot from the fresh tip and merge each REPORTED lane in order."""

        merged: list[str] = []
        conflicts: list[str] = []
        sites = self._landing_sites(batch)
        for site in sites:
            self._git.fetch(site.clone)
            self._git.ensure(site)
            for record in batch.lanes:
                branch = lane_branch(batch.id, record.id)
                if (record.state is not LaneState.REPORTED or lane_slot(record) != site.slot
                        or not self._git.has_ref(site.clone.path, f"refs/heads/{branch}")):
                    continue
                (merged if self._git.merge(site.worktree, branch) else conflicts).append(branch)
        return sites, tuple(merged), tuple(conflicts)

    # ── the settle ───────────────────────────────────────────────────────

    def _commits(self, request_id: str) -> tuple[str, ...]:
        batch, record = self._lane(request_id)
        if record.lane.kind is LaneKind.LANDING:
            return tuple(self._git.head(s.worktree) for s in self._landing_sites(batch) if (s.worktree / ".git").exists())
        return self._git.commits(self._work_site(batch, record))

    def _inner_settled(self, run: Run, outcome: Outcome) -> None:
        """The persona turn settled: a batch run's outcome gains its commits (and, for the landing, its gate
        receipts, run off this thread), then goes to the listeners."""

        if not run.request_id.startswith("BATCH-"):
            return
        try:
            commits = self._commits(run.request_id)
        except WorkRefused as refused:
            logger.warning("batch run %s: commits unread (%s)", run.request_id, refused.reason.value)
            commits = ()
        settled = replace(outcome, commits=commits or outcome.commits)
        if self._is_landing(run.request_id):
            thread = threading.Thread(target=self._gate_then_deliver, args=(run, settled),
                                      name=f"batch-gate-{run.request_id}", daemon=True)
            self._gate_threads = [t for t in self._gate_threads if t.is_alive()] + [thread]
            thread.start()
            return
        self._deliver(run, settled)

    def wait_for_gates(self, timeout: float | None = None) -> None:
        """Join every landing gate still running (tests; a serve never waits on one)."""

        for thread in list(self._gate_threads):
            thread.join(timeout)

    def _is_landing(self, request_id: str) -> bool:
        try:
            return self._lane(request_id)[1].lane.kind is LaneKind.LANDING
        except WorkRefused:
            return False

    def _gate_then_deliver(self, run: Run, outcome: Outcome) -> None:
        gates = []
        try:
            batch, record = self._lane(run.request_id)
            commands = tuple(record.lane.brief.tests) or (LANDING_GATE,)
            for site in self._landing_sites(batch):
                receipts.emit("batch.gate_started", batch_id=batch.id, slot=site.slot, command=" && ".join(commands),
                              worktree=str(site.worktree))
                gate = self._gate.run(site, commands)
                receipts.emit("batch.gate", batch_id=batch.id, **gate.wire())
                gates.append(gate)
        except Exception:
            logger.warning("batch landing %s: the gate could not run", run.request_id, exc_info=True)
        self._deliver(run, replace(outcome, gates=tuple(gates)))

    def _deliver(self, run: Run, outcome: Outcome) -> None:
        for callback in list(self._callbacks):
            try:
                callback(run, outcome)
            except Exception:
                logger.warning("a batch settle listener failed on %s", run.request_id, exc_info=True)
