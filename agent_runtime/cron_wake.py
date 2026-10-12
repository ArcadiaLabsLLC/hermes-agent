"""A cron job's finished run wakes the persona chat that created it.

ADR 0015 step 1 (owner, 2026-10-12). The shape is ``tools/mcp_job_wake.py``'s, proven for QA
builds: bind at the tool result, wake on the finish, one durable checkpoint beside
``processes.json`` so a serve restart keeps every binding.

1. **Bind.** The eternia-harness plugin's ``post_tool_call`` observer hands every tool result
   to :func:`observe_cronjob_result`. A successful ``cronjob``/``cronjob_manage`` ``create``
   names the new ``job_id``; the caller's routing is read on the tool worker thread
   (``get_current_session_key`` — the ``persona_chat_`` root the mission-chat lease bound,
   ``HERMES_SESSION_ID`` as the parent) and the active home is the job's cron store. First
   binding wins.
2. **Wake.** The serve's delivery drain calls :func:`poll_cron_wakes` every pass. For each
   binding it reads the job from ITS home (``cron.jobs.use_cron_store``): a ``last_run_at``
   past the binding's cursor with a settled ``last_status`` is a finished run, and queues one
   ``cron_job_finished`` event on ``process_registry.completion_queue`` — the queue the
   persona-chat drain already empties for finished background terminals — carrying the tail of
   the run's saved output. A recurring job wakes once per run (the cursor advances); a removed
   job drops its binding.
3. **Render.** :func:`format_cron_job_finished` is the ``[IMPORTANT: …]`` text the drain
   injects; the persona turns it into the message the operator reads.

Nothing here edits a cron store or starts a run. The checkpoint is
``<background-work home>/cron_jobs.json``; a row that cannot be read is skipped, never raised.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

__layer__ = "lanes"

logger = logging.getLogger(__name__)

EVENT_TYPE = "cron_job_finished"
CHECKPOINT_FILENAME = "cron_jobs.json"

_CRONJOB_TOOLS = frozenset({"cronjob", "cronjob_manage"})
_OUTPUT_TAIL_CHARS = 4000
#: A binding whose job never fires again (a one-shot that ran, a job deleted by hand) is kept
#: this long after its last wake, then forgotten.
_BINDING_TTL_S = 30 * 24 * 3600

_lock = threading.Lock()


# ── bind ────────────────────────────────────────────────────────────────────


def observe_cronjob_result(tool_name: Any = None, args: Any = None, result: Any = None, **_kwargs: Any) -> bool:
    """``post_tool_call`` observer. True when a binding was recorded. Never raises."""

    try:
        if tool_name not in _CRONJOB_TOOLS or not isinstance(args, dict) or args.get("action") != "create":
            return False
        job_id, name = _created_job(result)
        if not job_id:
            return False
        routing = _routing()
        if not (routing["session_key"] or routing["parent_session_id"]):
            logger.info("cron wake: job %s created outside any session; nothing to wake", job_id)
            return False
        checkpoint = _checkpoint_path()
        if checkpoint is None:
            return False
        row = _binding_row(job_id, name, routing)
        with _lock:
            rows = _read(checkpoint)
            if job_id in rows:
                return False  # the chat that CREATED the job is the one woken
            rows[job_id] = row
            _write(checkpoint, rows)
        logger.info("cron wake: job %s will wake session %r when it runs", job_id, routing["session_key"])
        return True
    except Exception:  # noqa: BLE001 — an observer never breaks the tool result
        logger.debug("cron wake: binding failed", exc_info=True)
        return False


def _created_job(result: Any) -> tuple[str, str]:
    if not isinstance(result, str):
        return "", ""
    try:
        payload = json.loads(result)
    except ValueError:
        return "", ""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return "", ""
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        return "", ""
    return job_id, str(payload.get("name") or "")


def _routing() -> dict[str, str]:
    """The creator's routing, read on the tool worker thread (the same fields a background
    ``terminal`` stamps on its completion)."""

    try:
        from tools.approval_context import get_current_session_key

        session_key = get_current_session_key(default="") or ""
    except Exception:  # noqa: BLE001
        session_key = ""
    try:
        from gateway.session_context import get_session_env

        parent_session_id = get_session_env("HERMES_SESSION_ID", "") or ""
    except Exception:  # noqa: BLE001
        parent_session_id = ""
    try:
        from hermes_constants import get_hermes_home

        home = str(get_hermes_home())
    except Exception:  # noqa: BLE001
        home = ""
    return {"session_key": str(session_key), "parent_session_id": str(parent_session_id), "home": home}


def _binding_row(job_id: str, name: str, routing: Mapping[str, str]) -> dict[str, Any]:
    wall = time.time()
    return {
        "job_id": job_id,
        "name": name[:160],
        "home": routing["home"],
        "session_key": routing["session_key"],
        "parent_session_id": routing["parent_session_id"],
        "bound_at": wall,
        "last_run_at": None,
        "expires_at": wall + _BINDING_TTL_S,
    }


# ── wake ────────────────────────────────────────────────────────────────────


def poll_cron_wakes(*, checkpoint: Path | None = None, now: float | None = None) -> int:
    """Queue a wake for every bound job that finished a run since its cursor. Returns the count.

    Called by the serve's delivery drain each pass. Reads each job from the home it was created
    under; a job that no longer exists, or a binding past its TTL, is forgotten. Never raises."""

    try:
        path = checkpoint or _checkpoint_path()
        if path is None:
            return 0
        wall = time.time() if now is None else now
        queued = 0
        with _lock:
            rows = _read(path)
            if not rows:
                return 0
            changed = False
            for job_id in list(rows):
                row = rows[job_id]
                job = _load_job(row.get("home", ""), job_id)
                if job is None or float(row.get("expires_at") or 0) <= wall:
                    rows.pop(job_id, None)
                    changed = True
                    continue
                # ``last_run_at`` is stamped by upstream's ``_record_run_outcome`` only, i.e. when a
                # run is OVER: a value past the cursor is a finished run, whatever its status.
                run_at = job.get("last_run_at")
                if not run_at or run_at == row.get("last_run_at"):
                    continue
                output = _latest_output_tail(row.get("home", ""), job_id)
                _queue_wake(_wake_event(row, job, output))
                row["last_run_at"] = run_at
                row["expires_at"] = wall + _BINDING_TTL_S
                queued += 1
                changed = True
            if changed:
                _write(path, rows)
        return queued
    except Exception:  # noqa: BLE001 — a drain pass must never die
        logger.debug("cron wake: poll failed", exc_info=True)
        return 0


def _load_job(home: str, job_id: str) -> Optional[dict]:
    try:
        from cron.jobs import get_job, use_cron_store
    except ImportError:
        return None
    try:
        if home:
            with use_cron_store(home):
                return get_job(job_id)
        return get_job(job_id)
    except Exception:  # noqa: BLE001 — an unreadable store is "not now", not "gone"
        logger.debug("cron wake: job %s unreadable under %r", job_id, home, exc_info=True)
        return {}


def _latest_output_tail(home: str, job_id: str) -> str:
    """The tail of the run's saved output (``cron/output/<job>/<stamp>.md``), redacted; ``""`` when none."""

    try:
        from cron.jobs import get_cron_output_dir, use_cron_store

        if home:
            with use_cron_store(home):
                out_dir = get_cron_output_dir() / job_id
        else:
            out_dir = get_cron_output_dir() / job_id
        files = sorted(out_dir.glob("*.md"))
        if not files:
            return ""
        text = files[-1].read_text(encoding="utf-8-sig", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return ""
    tail = text[-_OUTPUT_TAIL_CHARS:]
    try:
        from agent.redact import redact_sensitive_text

        return redact_sensitive_text(tail)
    except Exception:  # noqa: BLE001
        return tail


def _wake_event(row: Mapping[str, Any], job: Mapping[str, Any], output: str) -> dict[str, Any]:
    run_at = str(job.get("last_run_at") or "")
    return {
        "type": EVENT_TYPE,
        "session_id": wake_identity(str(row["job_id"]), run_at),  # the drains' per-event identity
        "session_key": str(row.get("session_key") or ""),
        "parent_session_id": str(row.get("parent_session_id") or ""),
        "task_id": "",
        "owner_task_id": "",
        "job_id": str(row["job_id"]),
        "name": str(job.get("name") or row.get("name") or ""),
        "status": str(job.get("last_status") or ""),
        "error": str(job.get("last_error") or "")[:_OUTPUT_TAIL_CHARS],
        "run_at": run_at,
        "output": output,
    }


def wake_identity(job_id: str, run_at: str) -> str:
    """Per-run identity: one wake per (job, run), replay-safe across drains."""

    digest = hashlib.sha256(json.dumps([job_id, run_at]).encode("utf-8")).hexdigest()[:24]
    return f"cron_job:{digest}"


def _queue_wake(event: dict[str, Any]) -> None:
    from tools.process_registry import process_registry

    process_registry.completion_queue.put(event)
    logger.info("cron wake: job %s ran (%s) — wake queued for session %r",
                event["job_id"], event["status"] or "finished", event["session_key"])


# ── render ──────────────────────────────────────────────────────────────────


def format_cron_job_finished(evt: Mapping[str, Any]) -> str:
    """The ``[IMPORTANT: …]`` text the drain injects for a ``cron_job_finished`` event."""

    name = str(evt.get("name") or evt.get("job_id") or "?")
    status = str(evt.get("status") or "finished")
    when = str(evt.get("run_at") or "")
    head = f"[IMPORTANT: Scheduled job \"{name}\" (job_id: {evt.get('job_id', '?')}) ran" + (f" at {when}" if when else "") + f" — {status}."
    body = str(evt.get("output") or "")
    error = str(evt.get("error") or "")
    parts = [head, "Tell the operator what it produced, in your own words."]
    if error:
        parts.append(f"Error:\n{error}")
    parts.append(f"Output:\n{body}" if body else "Output: (none saved)")
    return "\n".join(parts) + "]"


# ── the checkpoint ──────────────────────────────────────────────────────────


def _checkpoint_path() -> Path | None:
    try:
        from agent_runtime.profile_home import get_hermes_background_work_home

        return Path(get_hermes_background_work_home()) / CHECKPOINT_FILENAME
    except Exception:  # noqa: BLE001
        logger.debug("cron wake: background-work home unresolved", exc_info=True)
        return None


def _read(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = raw.get("jobs") if isinstance(raw, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {str(k): v for k, v in rows.items() if isinstance(v, dict) and v.get("job_id")}


def _write(path: Path, rows: Mapping[str, Mapping[str, Any]]) -> None:
    from utils import atomic_json_write

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, {"version": 1, "jobs": dict(rows)})


__all__ = [
    "CHECKPOINT_FILENAME",
    "EVENT_TYPE",
    "format_cron_job_finished",
    "observe_cronjob_result",
    "poll_cron_wakes",
    "wake_identity",
]
