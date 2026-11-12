"""The cron lane's DURABLE answer, for a process that is not the scheduler (RT-RUNNING-WORK-CRON-LANE-ALWAYS-UNAVAILABLE).

The scheduler runs in the gateway, never in ``harness serve``, so the live running-id set is
unreadable from the serve and the lane read ``unavailable / not_in_process`` on every frame — the
Tasks card's "Status incomplete" forever. The scheduler keeps its own durable record, though:
``<home>/cron/executions.db`` (``cron/executions.py``) persists every attempt as ``claimed``
BEFORE dispatch and moves it to a terminal state when it ends, with the owning ``pid`` and its
``process_started_at`` fingerprint. A ``claimed``/``running`` row whose owner is provably the same
live process IS a running cron job; one whose owner is gone or recycled is not (the scheduler's
own dead-owner sweep settles it). So absence in a readable ledger is evidence, unlike absence in
another process's memory.

Read-only by construction: the file is opened ``mode=ro`` and a home with no ledger is skipped —
never ``cron.executions._connect``, which creates the directory and the schema. Every profile
home is read (the multiplexing gateway ticks each profile's store): the head home, the default
home and each ``profiles/<name>``. The SELECT names only the columns this lane reads; a ledger
the query cannot read (locked past the timeout, a schema without them) is ``ledger_unreadable``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..projection_accountant import ProjectionAccountant
from .ownership import _head_home, _pid_identity
from .rows import LanePass, _progress, _source, bounded_operator_text, work_row
from .vocabulary import (
    KIND_CRON_JOB,
    LANE_DURABLE,
    PID_DEAD,
    PID_RECYCLED,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
)

__layer__ = "lanes"

LEDGER_RELATIVE = Path("cron") / "executions.db"
JOBS_RELATIVE = Path("cron") / "jobs.json"
_SELECT = ("SELECT id, job_id, pid, process_started_at, status, claimed_at, started_at FROM executions "
           "WHERE status IN ('claimed', 'running')")


def cron_homes() -> list[Path]:
    """Every home whose cron store the gateway may tick, each once (head, default, ``profiles/*``)."""

    from agent_runtime._upstream_doors import default_hermes_home, profiles_root

    candidates: list[Path] = []
    head, _provenance = _head_home()
    if head is not None:
        candidates.append(Path(head))
    try:
        default = default_hermes_home()
        candidates.append(default)
        root = profiles_root()
        if root.is_dir():
            candidates.extend(sorted(child for child in root.iterdir() if child.is_dir()))
    except OSError:
        pass
    seen: set[str] = set()
    homes = []
    for home in candidates:
        key = str(home.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            homes.append(home)
    return homes


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.5)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(_SELECT).fetchall()]
    finally:
        conn.close()


def _job_labels(home: Path) -> dict[str, str]:
    """``job id -> name`` from the store's ``jobs.json``; cosmetic, so any failure is no labels."""

    try:
        data = json.loads((home / JOBS_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jobs = data.get("jobs") if isinstance(data, dict) else data
    labels = {}
    for job in jobs if isinstance(jobs, list) else []:
        if isinstance(job, dict) and job.get("id"):
            labels[str(job["id"])] = bounded_operator_text(job.get("name") or job.get("prompt") or job["id"], limit=160)
    return labels


def _epoch(stamp: Any) -> float | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()  # the ledger writes aware stamps; a naive one is local time
    return moment.astimezone(UTC).timestamp()


class CronLedgerLane(LanePass):
    """``claimed``/``running`` attempts under a live owner, from every home's ledger."""

    kind = KIND_CRON_JOB

    def collect(self, homes: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for home in homes:
            ledger = home / LEDGER_RELATIVE
            if not ledger.is_file():
                continue  # this home never ran a cron job: nothing to report, nothing to create
            try:
                attempts = _read_ledger(ledger)
            except sqlite3.Error as exc:
                return [], _source(SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="ledger_unreadable",
                                   detail=type(exc).__name__)
            labels = _job_labels(home) if attempts else {}
            for attempt in attempts:
                row = self.row(attempt, labels)
                if row is not None:
                    rows.setdefault(row["work_id"], row)  # one row per job, as the live lane keys it
        return self.finish(list(rows.values())), _source(SOURCE_OK, lane=LANE_DURABLE)

    def row(self, attempt: dict[str, Any], labels: dict[str, str]) -> dict[str, Any] | None:
        execution_id = bounded_operator_text(attempt.get("id"), limit=200)
        job_id = bounded_operator_text(attempt.get("job_id"), limit=200)
        if not execution_id or not job_id:
            return None
        self.consider()
        _alive, verified, verdict = _pid_identity(attempt.get("pid"), attempt.get("process_started_at"))
        if verdict in (PID_DEAD, PID_RECYCLED):
            # The owner is gone: the attempt is over whatever the row still says; the
            # scheduler's dead-owner sweep books it ``unknown``. Never shown as running.
            self.drop("cron_owner_exited", entity_id=execution_id,
                      detail="the process that claimed this cron run is gone", by_design=True)
            return None
        started = _epoch(attempt.get("started_at") or attempt.get("claimed_at"))
        return work_row(
            kind=KIND_CRON_JOB, stable_id=job_id, label=labels.get(job_id) or job_id,
            status=STATUS_RUNNING if verified else STATUS_UNKNOWN, source_lane=LANE_DURABLE,
            pid=attempt.get("pid"), pid_verified=verified,
            started_at=datetime.fromtimestamp(started, UTC).isoformat() if started is not None else "",
            elapsed_seconds=int(max(0.0, self.now - started)) if started is not None else 0,
            progress=_progress(available=False), cancellable=False,
        )


def collect_cron_ledger(*, now: float, accountant: ProjectionAccountant | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return CronLedgerLane(now=now, accountant=accountant).collect(cron_homes())
