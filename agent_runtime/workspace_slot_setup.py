"""Clone a slot and run an owner's setup step — as VISIBLE background work (row H11).

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.5 (OWNER calls
8b, 8d). Both verbs spawn through ``process_registry.spawn_local`` as background processes, so
each is a ``terminal`` row with a tail, a completion and a Stop — never a foreground call that
holds the request open.

* **Clone** (``runtime.workspace.slot.clone``): ``git clone --branch <default_branch> --
  <clone_url> <dest_path>``. **Authentication is the machine's own git** (call 8b): hermes
  passes no credential, holds none and does not reuse the realm's ``RealmSyncCredential``
  seam — the child gets exactly one variable from hermes, ``GIT_TERMINAL_PROMPT=0``, so a
  missing sign-in FAILS (``clone_auth_required``, redacted stderr as evidence) instead of
  waiting forever on a prompt no one can see. On exit 0 the slot is bound (``slot.bind`` —
  which re-reports) and the run is ``succeeded``.
* **Run step** (``runtime.workspace.recipe.run_step``): one owner ``command`` step, ONLY on
  this explicit request (call 8d — nothing runs after a clone on its own), in its
  ``cwd_slot``'s bound checkout with that slot's environment overlay (call 8e) and ``argv[0]``
  resolved through the slot's ``tool_paths``. On exit the slot is re-reported.

Endings are settled by a watcher thread per run and, idempotently, by :func:`settle_runs`
(called before ``recipe.show`` answers), so a serve restart mid-run still settles from the
registry's persisted completion — or reads ``lost`` when the registry no longer knows it.
A replayed request (``issued_at`` not newer than the step's last run) is refused
``stale_request``; a step already running is refused ``step_running``.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .workspace_slot_recipe import (
    CLONE_STEP_ID,
    STEP_COMMAND,
    materialize,
    url_carries_credential,
)
from .workspace_slot_runs import (
    LOCK,
    RUN_ENDED,
    RUN_FAILED,
    RUN_KIND_CLONE,
    RUN_KIND_COMMAND,
    RUN_LOST,
    RUN_RUNNING,
    RUN_STOPPED,
    RUN_SUCCEEDED,
    all_runs,
    latest_runs,
    record_run,
    update_run,
)
from .workspace_slots import (
    REASON_CLONE_URL_CARRIES_CREDENTIAL,
    REASON_INVALID_DECLARATION,
    REASON_INVALID_PATH,
    REASON_SLOT_NOT_DECLARED,
    SlotRefused,
    bind,
    bound_path,
    live_slots,
    load_document,
    stamp_epoch,
)

__layer__ = "lanes"

logger = logging.getLogger(__name__)

REASON_SLOT_ALREADY_BOUND = "slot_already_bound"
REASON_DEST_NOT_EMPTY = "dest_not_empty"
REASON_UNKNOWN_STEP = "unknown_step"
REASON_STEP_NOT_RUNNABLE = "step_not_runnable"
REASON_SLOT_UNBOUND_HERE = "slot_unbound_here"
REASON_STEP_RUNNING = "step_running"
REASON_STALE_REQUEST = "stale_request"

END_CLONE_AUTH_REQUIRED = "clone_auth_required"
END_CLONE_REPOSITORY_NOT_FOUND = "clone_repository_not_found"
END_CLONE_FAILED = "clone_failed"
END_COMMAND_FAILED = "command_failed"
END_BIND_REFUSED = "bind_refused"
END_RUN_LOST = "run_lost"
END_STOPPED = "stopped"

#: The ONLY variable hermes hands a clone: fail a missing sign-in instead of prompting.
CLONE_ENV = {"GIT_TERMINAL_PROMPT": "0"}
#: How often a watcher looks at its run; the registry's own reader moves it to finished.
WATCH_INTERVAL_SECONDS = 0.5
#: Evidence bound: the last lines of the run's tail, redacted.
EVIDENCE_LINES = 8
EVIDENCE_CHARS = 800

_BRANCH_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
#: git's own words for "the server wants a credential you did not give it".
_AUTH_MARKERS = (
    "terminal prompts disabled", "could not read username", "could not read password", "authentication failed",
    "permission denied (publickey", "http basic: access denied", "invalid username or password",
    "returned error: 401", "returned error: 403",
)
_NOT_FOUND_MARKERS = ("repository not found", "does not appear to be a git repository", "returned error: 404")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def spawning_registry() -> Any:
    from tools.process_registry import process_registry

    return process_registry


def redacted_tail(text: Any) -> str:
    """The last lines of a run's output with every URL's userinfo, bearer and secret masked."""

    from .redaction import mask_secret_lines, redact_transport_text

    lines = [line for line in str(text or "").splitlines() if line.strip()][-EVIDENCE_LINES:]
    out = mask_secret_lines(redact_transport_text("\n".join(lines)))
    return out[-EVIDENCE_CHARS:]


def classify_clone_failure(output: str) -> str:
    """``clone_auth_required`` / ``clone_repository_not_found`` / ``clone_failed`` from git's own words."""

    lowered = str(output or "").lower()
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return END_CLONE_AUTH_REQUIRED
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return END_CLONE_REPOSITORY_NOT_FOUND
    return END_CLONE_FAILED


# ── guards shared by both verbs ──────────────────────────────────────────────


def _guard_replay(workspace_id: str, slot: str, step_id: str, issued_at: str) -> None:
    held = latest_runs(workspace_id, slot).get(step_id)
    if held is None:
        return
    if held.get("status") == RUN_RUNNING:
        raise SlotRefused(REASON_STEP_RUNNING, f"{slot}/{step_id} is already running ({held.get('work_id')})")
    if (stamp_epoch(issued_at) or 0.0) <= (stamp_epoch(held.get("issued_at")) or 0.0):
        raise SlotRefused(REASON_STALE_REQUEST, f"{slot}/{step_id} already ran for a request issued at {held.get('issued_at')}")


def _existing_ancestor(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path(os.getcwd())


def _start(run: dict[str, Any], session: Any, registry: Any, watch: bool) -> dict[str, Any]:
    run = record_run({**run, "run_id": session.id, "session_id": session.id, "work_id": f"terminal:{session.id}",
                      "status": RUN_RUNNING, "reason": None, "evidence": None, "exit_code": None, "ended_at": None})
    if watch:
        threading.Thread(target=watch_run, args=(session.id, registry), daemon=True,
                         name=f"slot-run-{session.id}").start()
    return run


# ── Clone ────────────────────────────────────────────────────────────────────


def clone_argv(slot: dict[str, Any], dest: Path) -> list[str]:
    repo = slot.get("repo") or {}
    url, branch = str(repo.get("clone_url") or ""), str(repo.get("default_branch") or "main")
    if url_carries_credential(url):
        raise SlotRefused(REASON_CLONE_URL_CARRIES_CREDENTIAL, "the declared clone URL carries userinfo; hermes passes none")
    if not _BRANCH_RE.match(branch):
        raise SlotRefused(REASON_INVALID_DECLARATION, f"{branch!r} is not a branch name")
    return ["git", "clone", "--branch", branch, "--", url, str(dest)]


def clone_slot(workspace_id: str, slot: str, dest_path: str, *, issued_at: str, registry: Any = None,
               watch: bool = True) -> dict[str, Any]:
    """Spawn the clone of ``slot`` into ``dest_path`` as a background terminal row."""

    declared = live_slots(load_document(workspace_id)).get(slot)
    if declared is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{workspace_id} declares no slot {slot!r}")
    held = bound_path(slot)
    if held is not None and held.is_dir():
        raise SlotRefused(REASON_SLOT_ALREADY_BOUND, f"{slot} is bound here at {held}; Locate rebinds it")
    dest = Path(str(dest_path or "")).expanduser()
    if not dest.is_absolute():
        raise SlotRefused(REASON_INVALID_PATH, "a clone lands at an ABSOLUTE local path")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise SlotRefused(REASON_DEST_NOT_EMPTY, f"{dest} exists and is not an empty directory")
    argv = clone_argv(declared, dest)
    with LOCK:
        _guard_replay(workspace_id, slot, CLONE_STEP_ID, issued_at)
        registry = registry or spawning_registry()
        session = registry.spawn_local(shlex.join(argv), cwd=str(_existing_ancestor(dest.parent)),
                                       env_vars=dict(CLONE_ENV), persist_on_release=True)
        run = _start({"workspace_id": workspace_id, "slot": slot, "step_id": CLONE_STEP_ID, "kind": RUN_KIND_CLONE,
                      "dest_path": str(dest), "issued_at": issued_at, "started_at": _now()}, session, registry, watch)
    return {"slot": slot, "run": run, "argv": argv}


# ── Run step ─────────────────────────────────────────────────────────────────


def run_step(workspace_id: str, slot: str, step_id: str, *, issued_at: str, registry: Any = None,
             watch: bool = True) -> dict[str, Any]:
    """Spawn one owner ``command`` step under its slot's environment, on THIS explicit request."""

    from .workspace_slot_overlay import SlotBinding, overlay_for

    live = live_slots(load_document(workspace_id))
    declared = live.get(slot)
    if declared is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{workspace_id} declares no slot {slot!r}")
    steps, _ = materialize(slot, declared)
    step = next((s for s in steps if s["id"] == step_id), None)
    if step is None:
        raise SlotRefused(REASON_UNKNOWN_STEP, f"{slot} has no step {step_id!r}")
    if step["kind"] != STEP_COMMAND:
        raise SlotRefused(REASON_STEP_NOT_RUNNABLE, f"{step_id} is a derived {step['kind']} step; it is done by hand")
    cwd_slot = step.get("cwd_slot") or slot
    path = bound_path(cwd_slot)
    if cwd_slot not in live or path is None or not path.is_dir():
        raise SlotRefused(REASON_SLOT_UNBOUND_HERE, f"{cwd_slot} is not bound on this machine")
    overlay = overlay_for(SlotBinding(workspace_id, cwd_slot, str(path)))
    argv = overlay.resolve_argv([str(a) for a in step["argv"]])
    with LOCK:
        _guard_replay(workspace_id, slot, step_id, issued_at)
        registry = registry or spawning_registry()
        session = registry.spawn_local(shlex.join(argv), cwd=str(path),
                                       env_vars=overlay.apply({"PATH": os.environ.get("PATH", "")}),
                                       persist_on_release=True)
        run = _start({"workspace_id": workspace_id, "slot": slot, "step_id": step_id, "kind": RUN_KIND_COMMAND,
                      "cwd_slot": cwd_slot, "env_source": overlay.env_source, "issued_at": issued_at,
                      "started_at": _now()}, session, registry, watch)
    return {"slot": slot, "step_id": step_id, "run": run, "argv": argv, "env_source": overlay.env_source}


# ── settling ─────────────────────────────────────────────────────────────────


def _rereport(workspace_id: str) -> None:
    from .workspace_slots_probe import report

    try:
        report(workspace_id)
    except SlotRefused as exc:  # no machine identity: the run still settles
        logger.warning("slot run settled but the re-report was refused: %s", exc.reason)


def _ending(run: dict[str, Any], session: Any) -> dict[str, Any]:
    if session is None:
        return {"status": RUN_LOST, "reason": END_RUN_LOST, "evidence": "the process registry no longer knows this run"}
    tail = getattr(session, "output_buffer", "")
    if getattr(session, "completion_reason", "exited") == "killed":
        return {"status": RUN_STOPPED, "reason": END_STOPPED, "evidence": redacted_tail(tail)}
    code = getattr(session, "exit_code", None)
    if code == 0 and run.get("kind") == RUN_KIND_CLONE:
        try:
            bound = bind(run["workspace_id"], run["slot"], run["dest_path"], issued_at=_now())
        except SlotRefused as exc:
            return {"status": RUN_FAILED, "reason": END_BIND_REFUSED, "evidence": exc.reason, "exit_code": 0}
        return {"status": RUN_SUCCEEDED, "exit_code": 0, "warnings": bound.get("warnings") or []}
    if code == 0:
        _rereport(run["workspace_id"])
        return {"status": RUN_SUCCEEDED, "exit_code": 0}
    reason = classify_clone_failure(tail) if run.get("kind") == RUN_KIND_CLONE else END_COMMAND_FAILED
    if run.get("kind") == RUN_KIND_COMMAND:
        _rereport(run["workspace_id"])
    return {"status": RUN_FAILED, "reason": reason, "exit_code": code, "evidence": redacted_tail(tail)}


def settle_run(run_id: str, registry: Any = None) -> dict[str, Any] | None:
    """End ``run_id`` from its registry session when it has exited; idempotent, first settler wins."""

    with LOCK:
        run = next((r for r in all_runs() if r.get("run_id") == run_id), None)
        if run is None or run.get("status") in RUN_ENDED:
            return run
        session = (registry or spawning_registry()).get(str(run.get("session_id")))
        if session is not None and not getattr(session, "exited", False):
            return run
        return update_run(run_id, ended_at=_now(), **_ending(run, session))


def settle_runs(workspace_id: str | None = None, registry: Any = None) -> list[dict[str, Any]]:
    """Settle every still-running run (of one workspace, or all) this machine recorded."""

    return [settle_run(str(run["run_id"]), registry) for run in all_runs()
            if run.get("status") == RUN_RUNNING and workspace_id in (None, run.get("workspace_id"))]


def watch_run(run_id: str, registry: Any, *, interval: float = WATCH_INTERVAL_SECONDS,
              wait: Callable[[float], Any] | None = None) -> dict[str, Any] | None:
    """Settle ``run_id`` as soon as it ends (the serve watcher thread; the CLI calls it in-line)."""

    pause = wait or threading.Event().wait
    while True:
        try:
            run = settle_run(run_id, registry)
        except Exception:  # a watcher never takes serve down; settle_runs still answers on read
            logger.exception("slot run watcher failed for %s", run_id)
            return None
        if run is None or run.get("status") in RUN_ENDED:
            return run
        pause(interval)


__all__ = [
    "CLONE_ENV",
    "classify_clone_failure",
    "clone_argv",
    "clone_slot",
    "redacted_tail",
    "run_step",
    "settle_run",
    "settle_runs",
    "watch_run",
]
