"""This machine's record of the setup runs it started: Clone and owner ``command`` steps (row H11).

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.5. A run is a
background ``terminal`` row in the process registry (its tail, its notification, its Stop);
THIS file is what the checklist needs on top of that row and the registry does not keep: which
workspace, slot and step the run serves, and its typed ending (``clone_auth_required``,
``clone_repository_not_found``, ``clone_failed``, ``command_failed``, ``stopped``, ``lost``)
with the REDACTED tail as evidence.

``machine_slot_runs.json`` v1 lives beside ``machine_slot_env.json`` in the hermes root and
is hard-excluded from realm sync like it: a run names local paths and happens on one
machine. **It never holds an environment value or a credential** — no env, no argv; the clone
URL is refused upstream when it carries userinfo, and stderr is redacted before it lands.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from hermes_constants import get_default_hermes_root
from utils import atomic_json_write

from .json_document import read_versioned_document
from .workspace_slots import stamp_epoch

__layer__ = "stores"

MACHINE_SLOT_RUNS_FILENAME = "machine_slot_runs.json"
RUNS_SCHEMA_VERSION = 1

RUN_KIND_CLONE = "clone"
RUN_KIND_COMMAND = "command"

RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_STOPPED = "stopped"
RUN_LOST = "lost"
RUN_ENDED = frozenset({RUN_SUCCEEDED, RUN_FAILED, RUN_STOPPED, RUN_LOST})

#: One lock for every read-modify-write: a watcher thread and a ``recipe.show`` settle may race.
LOCK = threading.RLock()


def runs_path() -> Path:
    return Path(get_default_hermes_root()) / MACHINE_SLOT_RUNS_FILENAME


def _read_runs() -> dict[str, Any]:
    return read_versioned_document(runs_path(), schema_version=RUNS_SCHEMA_VERSION, collection="runs")


def _write(payload: dict[str, Any]) -> None:
    target = runs_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, payload, indent=2, sort_keys=True, mode=0o600)


def record_run(run: dict[str, Any]) -> dict[str, Any]:
    with LOCK:
        payload = _read_runs()
        payload["schema_version"] = RUNS_SCHEMA_VERSION
        payload["runs"][str(run["run_id"])] = dict(run)
        _write(payload)
    return run


def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    with LOCK:
        payload = _read_runs()
        run = payload["runs"].get(run_id)
        if run is None:
            return None
        run.update(fields)
        _write(payload)
        return dict(run)


def all_runs() -> list[dict[str, Any]]:
    return [dict(run) for run in _read_runs()["runs"].values() if isinstance(run, dict)]


def latest_runs(workspace_id: str, slot: str) -> dict[str, dict[str, Any]]:
    """``step_id -> the newest run of that step`` for one slot on this machine."""

    newest: dict[str, dict[str, Any]] = {}
    for run in all_runs():
        if run.get("workspace_id") != workspace_id or run.get("slot") != slot:
            continue
        held = newest.get(str(run.get("step_id")))
        if held is None or (stamp_epoch(run.get("issued_at")) or 0.0) >= (stamp_epoch(held.get("issued_at")) or 0.0):
            newest[str(run.get("step_id"))] = run
    return newest


__all__ = [
    "MACHINE_SLOT_RUNS_FILENAME",
    "all_runs",
    "latest_runs",
    "record_run",
    "runs_path",
    "update_run",
]
