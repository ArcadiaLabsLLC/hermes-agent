"""The two lanes whose liveness is a PROCESS this runtime owns: terminal
background processes (durable checkpoint + live registry) and cron jobs
(live-only, with positive proof the scheduler runs here)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._upstream_doors import cron_pools_present
from ..parity import ProjectionAccountant

from .ownership import _head_home, _owner_of, _pid_identity
from .rows import (
    LanePass,
    _iso,
    _iso_from_naive_local,
    _module,
    _preview,
    _progress,
    _source,
    bounded_operator_text,
    elapsed_seconds,
    work_row,
)
from .vocabulary import (
    KIND_CRON_JOB,
    KIND_TERMINAL,
    LANE_DURABLE,
    LANE_LIVE,
    PID_DEAD,
    PID_RECYCLED,
    REASON_NOT_IN_PROCESS,
    REGISTRY_EXITED,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    _CHECKPOINT_FILENAME,
)

__layer__ = "lanes"


class TerminalLane(LanePass):
    """Durable ``processes.json`` checkpoint, enriched from the live registry.

    The checkpoint is written atomically on every start/exit and holds
    running-only entries with the ``host_start_time`` identity baseline, so it
    is the one lane that answers honestly from a cold CLI process.

    Phases: :meth:`read_durable` → :meth:`durable_row` per entry →
    :meth:`enrich_live` (:meth:`live_row` per registry session) →
    :meth:`LanePass.finish`.
    """

    kind = KIND_TERMINAL

    def __init__(self, *, now: float, accountant: ProjectionAccountant | None) -> None:
        super().__init__(now=now, accountant=accountant)
        self.rows: dict[str, dict[str, Any]] = {}
        self.lane = LANE_DURABLE
        self.live_error = ""

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        head, _provenance = _head_home()
        if head is None:
            return [], _source(
                SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="home_unresolved"
            )
        # Which home this resolved to rides `_ambient_context()`, once, for the whole
        # projection — it is machine-local context, not this lane's health.
        entries, refusal = self.read_durable(head)
        if refusal is not None:
            return [], refusal
        for entry in entries:
            self.durable_row(entry)
        self.enrich_live()
        return (
            self.finish(list(self.rows.values())),
            _source(SOURCE_OK, lane=self.lane, live_enrichment_error=self.live_error),
        )

    def read_durable(self, head: Path) -> tuple[list[Any], dict[str, Any] | None]:
        """The checkpoint's entries, or a typed ``unavailable`` source entry."""

        path = head / _CHECKPOINT_FILENAME
        try:
            if path.exists():
                entries = json.loads(path.read_text(encoding="utf-8"))
            else:
                # An absent checkpoint and a checkpoint listing nothing are the SAME
                # runtime fact — zero background processes, proven — so the lane says
                # `ok` with zero rows either way. Which of the two it was is storage
                # layout, and reporting it here is what used to put a filesystem
                # observation on a contract field.
                entries = []
        except Exception as exc:
            return [], _source(
                SOURCE_UNAVAILABLE,
                lane=LANE_DURABLE,
                reason="checkpoint_unreadable",
                detail=f"{type(exc).__name__}",
            )
        if not isinstance(entries, list):
            return [], _source(
                SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="checkpoint_malformed"
            )
        return entries, None

    def durable_row(self, entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        session_id = bounded_operator_text(entry.get("session_id"), limit=200)
        if not session_id:
            return
        self.consider()
        pid = entry.get("pid")
        _alive, verified, verdict = _pid_identity(pid, entry.get("host_start_time"))
        if verdict == PID_DEAD:
            # The checkpoint says running; the kernel says the PID is gone.
            # A process that exited is not running work, and reporting it would
            # be exactly the liveness lie this projection exists to prevent.
            # Checkpoint lag between an exit and the next atomic write is the
            # normal steady state, so this is a bound, not lost data.
            self.drop(
                "process_exited",
                entity_id=session_id,
                detail="checkpoint row's PID no longer exists",
                by_design=True,
            )
            return
        if verdict == PID_RECYCLED:
            # Alive, but a DIFFERENT process now holds the number. Our work is
            # gone and the live process is a stranger we must never signal.
            # Reached ONLY on a real start-time mismatch — an unreadable probe
            # falls through below as unverified instead of being deleted here.
            self.drop(
                "pid_recycled",
                entity_id=session_id,
                detail="host_start_time mismatch; PID was recycled",
                by_design=True,
            )
            return
        started = entry.get("started_at")
        owning_session = bounded_operator_text(entry.get("session_key"), limit=200)
        # Same resolver, same rule as the delegation lane. A terminal spawned
        # outside a persona turn carries a gateway session key that no chat root
        # owns; it resolves to nothing and ships an empty owner, which is the
        # truthful answer rather than a lane-specific guess.
        owner_persona, owner_instance = _owner_of(owning_session, memo=self.owners)
        row = work_row(
            kind=KIND_TERMINAL,
            stable_id=session_id,
            label=bounded_operator_text(entry.get("command"), limit=120) or session_id,
            command=bounded_operator_text(entry.get("command"), limit=400),
            status=STATUS_RUNNING if verified else STATUS_UNKNOWN,
            source_lane=LANE_DURABLE,
            pid=pid,
            pid_verified=verified,
            persona_id=owner_persona,
            persona_instance_id=owner_instance,
            session_id=owning_session,
            started_at=_iso(started),
            elapsed_seconds=elapsed_seconds(
                float(started) if isinstance(started, (int, float)) else None, now=self.now
            ),
            progress=_progress(available=False),
            cancellable=True,
        )
        self.rows[row["work_id"]] = row

    def enrich_live(self) -> None:
        registry = _module("tools.process_registry")
        if registry is None:
            return
        try:
            sessions = registry.process_registry.list_sessions()
            # The lane is only "live" once the registry actually produced rows.
            # A resident-but-non-owning registry returns [], and labelling that
            # ``live`` would claim first-hand knowledge this process does not
            # have.
            if sessions:
                self.lane = LANE_LIVE
            for item in sessions:
                self.live_row(item)
        except Exception as exc:
            self.live_error = type(exc).__name__

    def live_row(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        session_id = bounded_operator_text(item.get("session_id"), limit=200)
        if not session_id:
            return
        work_id = f"{KIND_TERMINAL}:{session_id}"
        if str(item.get("status") or "") == REGISTRY_EXITED:
            # The live registry is authoritative about its own children:
            # an exited one is not running work, and it must also not
            # survive as a stale durable row from a checkpoint written
            # before the exit.
            if self.rows.pop(work_id, None) is not None:
                self.drop(
                    "process_exited",
                    entity_id=session_id,
                    detail="live registry reports exited",
                    by_design=True,
                )
            return
        existing = self.rows.get(work_id)
        if existing is None:
            self.consider()
            existing = self.rows[work_id] = work_row(
                kind=KIND_TERMINAL,
                stable_id=session_id,
                label=bounded_operator_text(item.get("command"), limit=120) or session_id,
                command=bounded_operator_text(item.get("command"), limit=400),
                status=STATUS_RUNNING,
                source_lane=LANE_LIVE,
                pid=item.get("pid"),
                # In-process ownership IS the identity proof: this
                # registry holds the handle it spawned, so no
                # start-time comparison is needed or possible.
                pid_verified=True,
                # The registry formats this with `time.localtime` and no
                # offset; every `started_at` on this wire is UTC.
                started_at=_iso_from_naive_local(item.get("started_at")),
                elapsed_seconds=int(item.get("uptime_seconds") or 0),
                cancellable=True,
            )
        else:
            existing["source_lane"] = LANE_LIVE
            existing["pid_verified"] = True
            existing["status"] = STATUS_RUNNING
            if item.get("uptime_seconds"):
                existing["elapsed_seconds"] = int(item["uptime_seconds"])
        existing["tail_preview"] = _preview(item.get("output_preview"), self.accountant)


def _collect_terminal(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The terminal lane's collector: one :class:`TerminalLane` pass."""

    return TerminalLane(now=now, accountant=accountant).collect()


def _cron_owned_here(scheduler: Any, running_ids: set) -> bool:
    """True when the cron scheduler's dispatch machinery lives in THIS process.

    Takes the already-read running ids rather than re-reading them, so a failure
    to read the scheduler is reported by the CALLER as ``scheduler_unreadable``
    instead of being swallowed here and rendered as ``not_in_process`` — those
    are different facts ("the scheduler broke" vs "I am not the scheduler") and
    only the first is actionable.

    The pools are created lazily by ``_submit_with_guard`` on the first tick and
    then persist, so their existence is durable proof of ownership for the life
    of the process — stronger than the running-id set alone, which empties
    between jobs and would make the lane flicker to ``unavailable`` in the gaps.
    """

    if running_ids:
        return True
    return cron_pools_present(scheduler)


def _collect_cron(
    *, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Currently-executing cron jobs — live-only, for a structural reason.

    ``scheduler.get_running_job_ids()`` reads a PROCESS-GLOBAL set owned by the
    scheduler's own thread pool. From any other process it returns an empty
    frozenset, which would render as "no cron jobs running" — a silent lie
    about a lane we simply cannot see. Module residency does not rescue this
    (``mission_chat_turns`` imports the scheduler transitively), so the lane
    demands positive proof that the scheduler runs HERE: a live running-id, or
    one of the dispatch pools the ticker creates on its first tick.
    """

    scheduler = _module("cron.scheduler")
    if scheduler is None:
        return [], _source(
            SOURCE_UNAVAILABLE, lane=LANE_LIVE, reason=REASON_NOT_IN_PROCESS
        )
    try:
        running_ids = set(scheduler.get_running_job_ids())
    except Exception as exc:
        return [], _source(
            SOURCE_UNAVAILABLE,
            lane=LANE_LIVE,
            reason="scheduler_unreadable",
            detail=type(exc).__name__,
        )
    if not _cron_owned_here(scheduler, running_ids):
        return [], _source(
            SOURCE_UNAVAILABLE, lane=LANE_LIVE, reason=REASON_NOT_IN_PROCESS
        )

    labels: dict[str, str] = {}
    jobs_mod = _module("cron.jobs")
    if jobs_mod is not None and running_ids:
        try:
            for job in jobs_mod.list_jobs(include_disabled=True) or []:
                if isinstance(job, dict) and job.get("id") in running_ids:
                    labels[str(job["id"])] = bounded_operator_text(
                        job.get("name") or job.get("prompt") or job.get("id"), limit=160
                    )
        except Exception:
            # Label enrichment is cosmetic; the running set is the fact.
            labels = {}

    rows: list[dict[str, Any]] = []
    for job_id in sorted(running_ids):
        job_id = bounded_operator_text(job_id, limit=200)
        if not job_id:
            continue
        if accountant is not None:
            accountant.consider()
        rows.append(
            work_row(
                kind=KIND_CRON_JOB,
                stable_id=job_id,
                label=labels.get(job_id) or job_id,
                status=STATUS_RUNNING,
                source_lane=LANE_LIVE,
                progress=_progress(available=False),
                cancellable=False,
            )
        )

    # Already in running-id order; the cap and the count are every lane's.
    capped = LanePass(now=0.0, accountant=accountant, kind=KIND_CRON_JOB).finish(rows, ordered=False)
    return capped, _source(SOURCE_OK, lane=LANE_LIVE)
