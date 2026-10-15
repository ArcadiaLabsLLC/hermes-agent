"""The serve tick for builds: stall-fail, ``build.ended``, history, registry gc, and the boot hook.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §2, §6, §7 (owner
call 1).

* **Stall-fail** — every 30 s, beside the delegation stale monitor. An agent-started or
  announced build quiet for ``stall_fail_seconds`` (default 900) is ENDED with
  ``outcome: stalled``: agent-started through ``process_registry.kill_process`` in the owning
  process (``consume_output=False`` and ``notify_on_complete`` set, so the registry's
  completion queue wakes the owning agent WITH the tail); announced through the writer's
  declared stop mode (``request`` → ``<job_id>.stop``; ``kill_tree`` → the identity-guarded
  tree-kill). **A detected build is MARKED only — never ended here** (owner call 1): its row
  stays ``stalled`` with ``seconds_since_progress`` climbing, and the operator ends it with Stop.
* **Every ending** (stall, lost, failed, succeeded, stopped, a process that simply exited)
  emits ONE ``build.ended`` EventLog event — on the transition, never per tick — and a build
  whose outcome is known appends a ``history.jsonl`` line (``builds.history``).
* **Boot** (:func:`boot_builds`): this process owns detection, exports
  ``HERMES_BUILD_REGISTRY_DIR`` into its own environment so every child it spawns can
  announce, sweeps record files past ``expires_at`` + 24 h, and starts the tick thread.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_runtime.builds import history
from agent_runtime.builds.vocabulary import (
    DEFAULT_STALL_FAIL_SECONDS,
    OUTCOME_FAILED,
    OUTCOME_LOST,
    OUTCOME_STALLED,
    OUTCOME_STOPPED,
    OUTCOME_SUCCEEDED,
    RECORD_GC_GRACE_SECONDS,
    RECORD_STOP_KILL_TREE,
    RECORD_STOP_REQUEST,
    REGISTRY_DIR_ENV,
    SOURCE_AGENT,
    SOURCE_ANNOUNCED,
    SOURCE_DETECTED,
)

__layer__ = "lanes"

logger = logging.getLogger(__name__)

EVENT_BUILD_ENDED = "build.ended"
SWEEP_INTERVAL_SECONDS = 30.0
#: Statuses a build is still "in flight" in (the sweep's transition baseline).
_IN_FLIGHT = frozenset({"running", "stalling", "stalled", "unknown"})


def build_rows(now: float) -> list[dict[str, Any]]:
    """The build rows of one projection pass: the terminal lane, then the build lane over it."""

    from agent_runtime.running_work.lanes_build import BuildLane
    from agent_runtime.running_work.lanes_process import TerminalLane

    frame, _source = TerminalLane(now=now, accountant=None).collect()
    own, _build_source = BuildLane(now=now, accountant=None, frame_rows=frame).collect()
    return [row for row in frame if row.get("kind") == "build"] + own


def registry_home() -> Path | None:
    from agent_runtime.builds.vocabulary import BUILD_REGISTRY_DIRNAME
    from agent_runtime.running_work.ownership import _head_home

    head, _provenance = _head_home()
    return None if head is None else head / BUILD_REGISTRY_DIRNAME


def _end_agent(row: dict[str, Any]) -> bool:
    import sys

    registry = sys.modules.get("tools.process_registry")
    session_id = str(row.get("work_id") or "").split(":", 2)[-1]
    session = None if registry is None else registry.process_registry.get(session_id)
    if session is None:
        return False
    session.notify_on_complete = True  # the owning agent is woken WITH the tail
    registry.process_registry.kill_process(session_id, source="harness.build_stall", consume_output=False)
    return True


def _end_announced(row: dict[str, Any], record: dict[str, Any] | None) -> bool:
    from agent_runtime._upstream_doors import terminate_host_pid
    from agent_runtime.builds.registry import stop_request_path

    controls = (record or {}).get("controls") or {}
    directory = registry_home()
    job_id = str(row.get("work_id") or "").split(":", 2)[-1]
    if controls.get("stop") == RECORD_STOP_REQUEST and directory is not None:
        stop_request_path(directory, job_id).write_text("stalled\n", encoding="utf-8")
        return True
    if controls.get("stop") == RECORD_STOP_KILL_TREE and record and record.get("build_pid"):
        terminate_host_pid(int(record["build_pid"]), record.get("build_host_start_time"))
        return True
    return False


def _record_for(row: dict[str, Any]) -> dict[str, Any] | None:
    from agent_runtime.builds.registry import read_records

    directory = registry_home()
    name = ((row.get("announcement") or {}).get("record")) or ""
    if directory is None or not name:
        return None
    return next((item.record for item in read_records(directory)[0] if item.path.name == name), None)


def _default_ender(row: dict[str, Any]) -> bool:
    """End a stalled agent/announced build through its owner's seam; True when a stop was issued."""

    if row.get("source") == SOURCE_AGENT:
        return _end_agent(row)
    if row.get("source") == SOURCE_ANNOUNCED:
        return _end_announced(row, _record_for(row))
    return False


def _vanished_outcome(row: dict[str, Any]) -> str | None:
    """What a build that left the projection ended as: an agent build's exit code, else unobserved."""

    import sys

    if row.get("source") != SOURCE_AGENT:
        return None
    registry = sys.modules.get("tools.process_registry")
    session_id = str(row.get("work_id") or "").split(":", 2)[-1]
    session = None if registry is None else registry.process_registry.get(session_id)
    if session is None or session.exit_code is None:
        return OUTCOME_LOST
    if getattr(session, "completion_reason", "") == "killed":
        return OUTCOME_STOPPED
    return OUTCOME_SUCCEEDED if session.exit_code == 0 else OUTCOME_FAILED


@dataclass
class SweepResult:
    stall_failed: list[str] = field(default_factory=list)
    marked: list[str] = field(default_factory=list)
    ended: list[tuple[str, str | None]] = field(default_factory=list)


class BuildSweep:
    """The tick. Holds the in-flight baseline so an ending is emitted exactly once."""

    def __init__(self, *, rows: Callable[[float], list[dict[str, Any]]] = build_rows,
                 ender: Callable[[dict[str, Any]], bool] = _default_ender, event_log: Any = None,
                 history_dir: Callable[[], Path | None] = registry_home,
                 stall_fail_seconds: float = DEFAULT_STALL_FAIL_SECONDS) -> None:
        self.rows, self.ender, self.event_log = rows, ender, event_log
        self.history_dir, self.stall_fail_seconds = history_dir, stall_fail_seconds
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.stall_ended: set[str] = set()

    def tick(self, now: float | None = None) -> SweepResult:
        now = time.time() if now is None else now
        result = SweepResult()
        current = {row["work_id"]: row for row in self.rows(now)}
        for work_id, row in current.items():
            self._consider(work_id, row, now, result)
        for work_id, last in self.in_flight.items():
            if work_id not in current and work_id not in self.stall_ended:
                self._ended(last, _vanished_outcome(last), now, result)
        self.in_flight = {wid: row for wid, row in current.items()
                          if row.get("outcome") is None and row.get("status") in _IN_FLIGHT}
        return result

    def _consider(self, work_id: str, row: dict[str, Any], now: float, result: SweepResult) -> None:
        quiet = row.get("seconds_since_progress")
        stalled_out = (row.get("status") == "stalled" and row.get("outcome") is None
                       and isinstance(quiet, (int, float)) and quiet >= self.stall_fail_seconds)
        if stalled_out and row.get("source") == SOURCE_DETECTED:
            result.marked.append(work_id)  # owner call 1: MARK only; the operator ends it with Stop
        elif stalled_out and work_id not in self.stall_ended and self.ender(row):
            self.stall_ended.add(work_id)
            result.stall_failed.append(work_id)
            self._ended(row, OUTCOME_STALLED, now, result)
        elif row.get("outcome") is not None and work_id in self.in_flight and work_id not in self.stall_ended:
            self._ended(row, row["outcome"], now, result)

    def _ended(self, row: dict[str, Any], outcome: str | None, now: float, result: SweepResult) -> None:
        result.ended.append((row["work_id"], outcome))
        duration_ms = int(row.get("elapsed_seconds") or 0) * 1000
        self._emit(row, outcome, duration_ms, now)
        directory = self.history_dir()
        if outcome is not None and directory is not None:
            history.append(directory, project_root=(row.get("project") or {}).get("root") or "",
                           toolchain=row.get("toolchain") or "", target=row.get("target") or "",
                           mode=row.get("mode") or "", duration_ms=duration_ms, outcome=outcome, ended_at=now)

    def _emit(self, row: dict[str, Any], outcome: str | None, duration_ms: int, now: float) -> None:
        from datetime import datetime, timezone

        from agent_runtime.events import EventLog
        from agent_runtime.models import Event

        owner = row.get("owner") or {}
        payload = {"work_id": row["work_id"], "source": row.get("source"), "outcome": outcome,
                   "ended_reason": "outcome" if outcome is not None else "process_exited",
                   "label": row.get("label"), "workspace_id": row.get("workspace_id"), "slot_id": row.get("slot_id"),
                   "started_by_instance": row.get("started_by_instance"), "duration_ms": duration_ms,
                   "tail_preview": row.get("tail_preview") or ""}
        (self.event_log or EventLog()).append(Event(
            ts=datetime.fromtimestamp(now, timezone.utc), type=EVENT_BUILD_ENDED, task_id=None, run_id=None,
            persona_id=owner.get("persona_id"), payload=payload))


_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def boot_builds() -> dict[str, Any]:
    """Serve boot: own detection, export the registry dir, gc old records, start the tick."""

    from agent_runtime.builds.detect import enable_detection
    from agent_runtime.builds.registry import gc_expired

    global _THREAD
    enable_detection()
    directory = registry_home()
    removed: list[str] = []
    if directory is not None:
        os.environ[REGISTRY_DIR_ENV] = str(directory)
        removed = gc_expired(directory, grace_seconds=RECORD_GC_GRACE_SECONDS)
    if _THREAD is None or not _THREAD.is_alive():
        sweep = BuildSweep()
        _THREAD = threading.Thread(target=_loop, args=(sweep,), name="build-sweep", daemon=True)
        _THREAD.start()
    return {"registry_dir": str(directory) if directory else None, "gc_removed": len(removed)}


def _loop(sweep: BuildSweep) -> None:
    while not _STOP.wait(SWEEP_INTERVAL_SECONDS):
        try:
            sweep.tick()
        except Exception:  # noqa: BLE001 — one bad tick must never take the serve process down
            logger.warning("build_sweep_tick_failed", exc_info=True)
