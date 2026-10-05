"""Stop and Restart for every build row (plan ``build-running-work-2026-10-04.md`` §7; OWNER calls 2, 3).

**Stop** is ``running_work.cancel_work`` with the ``build`` canceller, decided per source:

=========  ==========================================================  ======================
source     seam                                                        refusal
=========  ==========================================================  ======================
agent      ``process_registry.kill_process`` (identity-guarded tree     ``owner_not_here`` from
           kill, ``consume_output=False``) in the owning process        any other process
announced  ``request`` ⇒ ``<job_id>.stop`` (answer ``cancel_requested``);  ``none`` ⇒
           ``kill_tree`` ⇒ the identity-guarded ``terminate_host_pid``  ``writer_declines``
detected   ``terminate_host_pid(pid, host_start_time)``                 slot no longer bound ⇒
                                                                         ``slot_unbound``
=========  ==========================================================  ======================

**Restart** = stop if running, then spawn ``restart.argv`` in ``restart.cwd`` through
``process_registry.spawn_local`` as a background process (``persist_on_release``: an
operator's restart outlives an agent's turn). **A detected build restarts through the SAME
path, with no confirm step** (owner call 2): the row already shows the argv and cwd it will run
and lists, as typed unknowns, what hermes could not observe. Under a bound slot the restart
runs with that SLOT's environment (``workspace_slot_overlay.env_overlay``: ``path_prepend``,
``env``, ``.env``, ``venv``) and ``argv[0]`` resolved through the slot's ``tool_paths``; the new
row carries ``restart_of``, ``started_by: operator`` and ``env_source: slot:<name>`` (else
``process``) — recorded in ``<registry>/restart_marks.jsonl``, the one place the build lane
reads them back from.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from agent_runtime.builds.vocabulary import (
    BUILD_REGISTRY_DIRNAME,
    CONTROL_ALLOWED,
    CONTROL_REASON_ARGV_UNKNOWN,
    CONTROL_REASON_OWNER_NOT_HERE,
    CONTROL_REASON_SLOT_UNBOUND,
    CONTROL_REASON_WRITER_DECLINES,
    ENV_SOURCE_PROCESS,
    RECORD_STOP_KILL_TREE,
    RECORD_STOP_REQUEST,
    SOURCE_AGENT,
    SOURCE_ANNOUNCED,
    SOURCE_DETECTED,
)

__layer__ = "lanes"

RESTART_MARKS_FILENAME = "restart_marks.jsonl"
#: Statuses a Restart stops first.
_RUNNING = frozenset({"running", "stalling", "stalled", "unknown"})


def _error(work_id: str, code: str, detail: str = "") -> dict[str, Any]:
    return {"status": "error", "code": code, "work_id": work_id, "detail": detail}


def _registry_dir() -> Path | None:
    from agent_runtime.running_work.ownership import _head_home

    head, _provenance = _head_home()
    return None if head is None else head / BUILD_REGISTRY_DIRNAME


def _stable(row: dict[str, Any]) -> str:
    return str(row.get("work_id") or "").split(":", 2)[-1]


def _registry() -> Any:
    module = sys.modules.get("tools.process_registry")
    return None if module is None else module.process_registry


def _slot_still_bound(row: dict[str, Any]) -> bool:
    from agent_runtime.workspace_slots import authorized_roots_bound_here

    return any(slot.workspace_id == row.get("workspace_id") and slot.slot == row.get("slot_id")
               for slot in authorized_roots_bound_here())


def announced_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """The registry record an ``announced`` row names (``announcement.record``), or None."""

    from agent_runtime.builds.registry import read_records

    directory, name = _registry_dir(), (row.get("announcement") or {}).get("record")
    if directory is None or not name:
        return None
    return next((item.record for item in read_records(directory)[0] if item.path.name == name), None)


# ── stop ─────────────────────────────────────────────────────────────────────


def _stop_agent(row: dict[str, Any], reason: str) -> dict[str, Any]:
    registry, session_id = _registry(), _stable(row)
    if registry is None or registry.get(session_id) is None:
        return _error(row["work_id"], "cancel_unavailable", CONTROL_REASON_OWNER_NOT_HERE)
    result = registry.kill_process(session_id, source="harness.work_cancel", consume_output=False)
    killed = str(result.get("status")) != "not_found"
    return {"status": "cancelled" if killed else "error", "code": "" if killed else "not_found", "work_id": row["work_id"]}


def _stop_announced(row: dict[str, Any], reason: str) -> dict[str, Any]:
    from agent_runtime._upstream_doors import terminate_host_pid
    from agent_runtime.builds.registry import stop_request_path

    record = announced_record(row) or {}
    mode = (record.get("controls") or {}).get("stop")
    directory = _registry_dir()
    if mode == RECORD_STOP_REQUEST and directory is not None:
        stop_request_path(directory, str(record.get("job_id") or _stable(row))).write_text(reason + "\n", encoding="utf-8")
        return {"status": "cancel_requested", "code": "", "work_id": row["work_id"]}
    if mode == RECORD_STOP_KILL_TREE and record.get("build_pid"):
        return _terminate(row, record.get("build_pid"), record.get("build_host_start_time"), terminate_host_pid)
    return _error(row["work_id"], "cancel_refused", CONTROL_REASON_WRITER_DECLINES)


def _stop_detected(row: dict[str, Any], reason: str) -> dict[str, Any]:
    from agent_runtime._upstream_doors import terminate_host_pid

    if not _slot_still_bound(row):
        return _error(row["work_id"], "cancel_refused", CONTROL_REASON_SLOT_UNBOUND)
    pid, _sep, start = _stable(row).partition("-")
    return _terminate(row, pid, int(start) if start.lstrip("-").isdigit() else None, terminate_host_pid)


def _terminate(row: dict[str, Any], pid: Any, start: Any, terminate: Any) -> dict[str, Any]:
    from agent_runtime.running_work.ownership import _pid_identity

    _alive, verified, _verdict = _pid_identity(pid, start)
    if not verified:
        return _error(row["work_id"], "not_found", "process identity does not match")
    terminate(int(pid), start)
    return {"status": "cancelled", "code": "", "work_id": row["work_id"]}


_STOPS = {SOURCE_AGENT: _stop_agent, SOURCE_ANNOUNCED: _stop_announced, SOURCE_DETECTED: _stop_detected}


def stop_build(row: dict[str, Any], *, reason: str = "operator_cancel") -> dict[str, Any]:
    """Stop one build row through its source's seam; every refusal is typed."""

    stop = _STOPS.get(str(row.get("source") or ""))
    if stop is None:
        return _error(str(row.get("work_id") or ""), "cancel_unsupported", "unknown build source")
    try:
        return stop(row, reason)
    except Exception as exc:  # noqa: BLE001 — a failed kill is a typed answer, never a crash
        return _error(row["work_id"], "cancel_failed", type(exc).__name__)


# ── restart ──────────────────────────────────────────────────────────────────


def _resolved_argv(argv: list[str], overlay: Any) -> list[str]:
    """``argv[0]`` resolved through the slot's ``tool_paths`` (by tool stem), else as observed."""

    if overlay is None or not argv:
        return list(argv)
    stem = Path(argv[0]).stem.lower()
    tool = overlay.tool_paths.get(stem) or overlay.tool_paths.get(Path(argv[0]).name.lower())
    return [tool, *argv[1:]] if tool else list(argv)


def _restart_refusal(row: dict[str, Any]) -> str:
    restart = row.get("restart") or {}
    if not restart.get("argv"):
        return CONTROL_REASON_ARGV_UNKNOWN
    if row.get("source") == SOURCE_DETECTED and not _slot_still_bound(row):
        return CONTROL_REASON_SLOT_UNBOUND
    controls = row.get("controls") or {}
    if controls.get("restart") != CONTROL_ALLOWED:
        return str(controls.get("restart_reason") or CONTROL_REASON_WRITER_DECLINES)
    return ""


def restart_build(row: dict[str, Any], *, registry: Any = None) -> dict[str, Any]:
    """Stop the build if it is running, then spawn its restart spec with the slot's environment."""

    from agent_runtime.workspace_slot_overlay import env_overlay

    work_id = str(row.get("work_id") or "")
    refusal = _restart_refusal(row)
    if refusal:
        return _error(work_id, "restart_refused", refusal)
    if row.get("status") in _RUNNING and row.get("outcome") is None:
        stopped = stop_build(row, reason="operator_restart")
        if stopped.get("status") == "error":
            return {**stopped, "code": "restart_refused", "detail": stopped.get("detail") or stopped.get("code")}
    spec = row["restart"]
    overlay = env_overlay(spec.get("cwd") or "")
    argv = _resolved_argv([str(a) for a in spec["argv"]], overlay)
    env_vars = overlay.apply({"PATH": os.environ.get("PATH", "")}) if overlay is not None else {}
    process_registry = registry or _spawning_registry()
    session = process_registry.spawn_local(shlex.join(argv), cwd=spec.get("cwd") or None, env_vars=env_vars,
                                           persist_on_release=True)
    env_source = overlay.env_source if overlay is not None else ENV_SOURCE_PROCESS
    _mark(session.id, restart_of=work_id, env_source=env_source)
    return {"status": "restarted", "code": "", "work_id": work_id, "new_work_id": f"build:{SOURCE_AGENT}:{session.id}",
            "argv": argv, "cwd": spec.get("cwd") or "", "env_source": env_source}


def _spawning_registry() -> Any:
    from tools.process_registry import process_registry

    return process_registry


def _mark(session_id: str, *, restart_of: str, env_source: str) -> None:
    directory = _registry_dir()
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    line = {"session_id": session_id, "restart_of": restart_of, "env_source": env_source, "at": time.time()}
    with (directory / RESTART_MARKS_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def restart_marks(directory: Path) -> dict[str, dict[str, Any]]:
    """``session_id -> {restart_of, env_source}`` — what the build lane stamps on a restarted row."""

    try:
        lines = (directory / RESTART_MARKS_FILENAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    marks: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("session_id"):
            marks[str(item["session_id"])] = item
    return marks
