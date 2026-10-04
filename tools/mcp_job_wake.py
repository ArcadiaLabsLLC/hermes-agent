"""Fork-owned MCP job wake: an MCP server's "job finished" notification wakes the agent that started the job.

Owner ruling 2026-10-03: a QA build is a background task, like ``terminal(background=True,
notify_on_complete=True)``. When it finishes, the agent that started it is woken and continues.

The join, end to end:

1. A tool call's result names a running job (``build_job.job_id`` — the launcher QA server's
   ``launch_or_attach`` / ``open_app_tab`` while an isolated rebuild runs; ``job.job_id`` for any
   other server). :func:`routing_for_call` snapshots the caller's routing on the tool worker
   thread — the same fields a background ``terminal`` stamps on its completion — and
   :func:`observe_call_result` binds the job id to it.
2. The server later sends ``notifications/message`` whose ``data`` is a job-finished event
   (``event == "qa_build_finished"`` from logger ``stagec_qa_mcp_server.qa_build``, or any
   ``*_finished`` event with a ``job_id``). :func:`on_log_notification` turns it into a
   ``mcp_job_finished`` event on ``process_registry.completion_queue`` — the queue every surface
   (CLI, TUI, serve's persona-chat lane) already drains for finished background terminals.
3. :func:`format_job_finished` renders the ``[IMPORTANT: ...]`` text the drain injects.
4. Background work: every bound job is a row in ``<background-work home>/mcp_jobs.json`` — the
   checkpoint the ``running_work`` projection's ``mcp_job`` lane reads, beside ``processes.json``
   (``agent_runtime/running_work/lanes_process.py``). ``running`` on bind; ``ready``/``failed``
   (with elapsed and the redacted tail) on the finish notification; gone once the serve drain
   settles the wake (:func:`note_wake_settled`), or past the row's own ``expires_at``.

A job id wakes at most once: the binding is popped when the wake is queued. A notification for a
job id nobody bound — unknown, foreign, or already woken — is logged and dropped. A notification
that is not a job event is never touched here and stays log-only.

0. Before any of that, :func:`advertise_job_wake` makes the client's ``initialize`` declare
   ``capabilities.experimental["eternia.job_wake"] = {"version": 1}`` whenever the logging route
   that carries the wake is installed, so a server may answer "build started — end your turn, you
   will be woken" instead of telling the agent to block in a status poll. A server that does not
   know the key ignores it (``experimental`` is free-form in the spec).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger("tools.mcp_tool")

EVENT_TYPE = "mcp_job_finished"
QA_BUILD_LOGGER = "stagec_qa_mcp_server.qa_build"
QA_BUILD_FINISHED = "qa_build_finished"
_JOB_RESULT_KEYS = ("build_job", "job")
_SEARCH_DEPTH = 4
_MAX_ROUTES = 128
_ROUTE_TTL_S = 6 * 3600.0
_TAIL_CHARS = 4000
#: How long a FINISHED row stays in background work when no drain settles its wake (a CLI/TUI
#: drain has no settle hook) — long enough to be seen, short enough not to become an archive.
_FINISHED_TTL_S = 30 * 60.0
CHECKPOINT_FILENAME = "mcp_jobs.json"
ROW_RUNNING, ROW_READY, ROW_FAILED = "running", "ready", "failed"
_OK_OUTCOMES = frozenset({"ready", "finished", "completed", "succeeded", "done", "ok"})

JOB_WAKE_CAPABILITY = "eternia.job_wake"
JOB_WAKE_VERSION = 1

_lock = threading.Lock()
_routes: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
#: The background-work rows, keyed like ``_routes``. A route is popped when its wake is queued
#: (wake at most once); its row outlives it until the wake is settled or the row expires.
_rows: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
_writer_identity: Optional[tuple[int, Any]] = None


def advertise_job_wake(session: Any) -> bool:
    """Make *session*'s capability ad carry ``experimental["eternia.job_wake"]``. True when installed.

    The SDK builds every ad (``initialize``, the stateless era's per-request capabilities, and our own
    pinned re-handshake) through ``ClientSession._build_capabilities`` with ``experimental=None``
    hard-coded, so the instance's builder is wrapped. A session without that builder (an older SDK,
    a double) is left alone and the server sees no declaration — the wake itself still works."""
    build = getattr(session, "_build_capabilities", None)
    if not callable(build) or getattr(build, "_eternia_job_wake", False):
        return False

    def _with_job_wake(version):
        caps = build(version)
        experimental = dict(getattr(caps, "experimental", None) or {})
        experimental[JOB_WAKE_CAPABILITY] = {"version": JOB_WAKE_VERSION}
        return caps.model_copy(update={"experimental": experimental})

    _with_job_wake._eternia_job_wake = True
    try:
        session._build_capabilities = _with_job_wake
    except Exception:
        logger.debug("MCP job-wake capability could not be declared", exc_info=True)
        return False
    return True


def routing_for_call(call_kwargs: Mapping[str, Any]) -> dict:
    """The caller's routing, read on the TOOL WORKER thread (contextvars do not cross to the MCP loop).

    Same fields and fallbacks a background ``terminal`` stamps on its completion, so every drain that
    can prove a terminal completion's owner proves this one the same way."""
    task_id = str(call_kwargs.get("task_id") or "")
    try:
        from tools.approval_context import get_current_session_key
        session_key = get_current_session_key(default="") or task_id
    except Exception:
        session_key = task_id
    try:
        from gateway.session_context import get_session_env
        parent_session_id = get_session_env("HERMES_SESSION_ID", "")
    except Exception:
        parent_session_id = ""
    return {"session_key": session_key, "task_id": task_id, "owner_task_id": task_id,
            "parent_session_id": parent_session_id, "checkpoint": _checkpoint_path()}


def _checkpoint_path() -> str:
    """Where this call's rows go — resolved HERE, on the worker thread, because that is the
    thread a persona turn's head-home scope is recorded on (the same place a ``terminal``
    spawned by this turn resolves ``processes.json``). Empty when no home resolves."""
    try:
        from agent_runtime.profile_home import get_hermes_background_work_home
        return str(Path(get_hermes_background_work_home()) / CHECKPOINT_FILENAME)
    except Exception:
        logger.debug("MCP job checkpoint home unresolved", exc_info=True)
        return ""


def observe_call_result(server_name: str, result: Any, routing: Optional[dict]) -> None:
    """Bind every RUNNING job a tool result names to *routing*. Never raises; first binding wins."""
    if not routing:
        return
    try:
        for job_key, job in _running_jobs(result):
            _bind(server_name, job["job_id"], routing, _job_facts(server_name, job_key, job))
    except Exception:
        logger.debug("MCP job routing capture failed for '%s'", server_name, exc_info=True)


def _bind(server_name: str, job_id: str, routing: dict, facts: Optional[dict] = None) -> None:
    key = (server_name, job_id)
    with _lock:
        _expire_locked(time.monotonic())
        if key in _routes:
            return  # the agent that STARTED the job is the one woken
        _routes[key] = {**routing, "bound_at": time.monotonic()}
        _rows[key] = _running_row(server_name, job_id, routing, facts or {})
        while len(_routes) > _MAX_ROUTES:
            dropped, _ = _routes.popitem(last=False)
            _rows.pop(dropped, None)
            logger.warning("MCP job route cap reached; forgetting %s/%s", *dropped)
        _write_checkpoints_locked(routing.get("checkpoint", ""))
    logger.info("MCP server '%s': job %s will wake session %r when it finishes",
                server_name, job_id, routing.get("session_key"))


def _expire_locked(now: float) -> None:
    for key in [k for k, v in _routes.items() if now - v["bound_at"] > _ROUTE_TTL_S]:
        _routes.pop(key, None)
        logger.warning("MCP job %s/%s expired unwoken after %.0fs", key[0], key[1], _ROUTE_TTL_S)
    wall = time.time()
    for key in [k for k, row in _rows.items() if row["expires_at"] <= wall]:
        _write_checkpoints_locked(_rows.pop(key)["checkpoint"])


def _running_jobs(result: Any) -> list[tuple[str, dict]]:
    """``(result key, job block)`` for every RUNNING job named in the result; first mention wins."""
    found: list[tuple[str, dict]] = []
    for payload in _json_payloads(result):
        _collect_jobs(payload, found, _SEARCH_DEPTH)
    unique: dict[str, tuple[str, dict]] = {}
    for job_key, job in found:
        unique.setdefault(job["job_id"], (job_key, job))
    return list(unique.values())


def _running_job_ids(result: Any) -> list[str]:
    """Job ids of RUNNING jobs named in ``structuredContent`` or in any JSON text block."""
    return [job["job_id"] for _key, job in _running_jobs(result)]


def _job_facts(server_name: str, job_key: str, job: dict) -> dict:
    """What background work shows about a job, read off its block: label, timing, kind."""
    commit = str(job.get("commit") or "")[:7]
    if job_key == "build_job":
        label = f"QA build {commit}" if commit else "QA build"
    else:
        label = str(job.get("label") or f"{server_name} job {job['job_id']}")
    return {"label": label[:160], "job_kind": "qa_build" if job_key == "build_job" else "",
            "eta_ms": _ms(job.get("eta_ms")), "expected_ms": _ms(job.get("expected_ms")),
            "elapsed_ms": _ms(job.get("elapsed_ms"))}


def _ms(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def _json_payloads(result: Any) -> list:
    payloads = []
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        payloads.append(structured)
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.lstrip().startswith("{"):
            try:
                payloads.append(json.loads(text))
            except ValueError:
                continue
    return payloads


def _collect_jobs(node: Any, found: list, depth: int) -> None:
    if depth < 0 or not isinstance(node, dict):
        return
    for key in _JOB_RESULT_KEYS:
        job = node.get(key)
        if isinstance(job, dict) and isinstance(job.get("job_id"), str) and job["job_id"]:
            if str(job.get("status") or "running") == "running":
                found.append((key, job))
    for value in node.values():
        if isinstance(value, dict):
            _collect_jobs(value, found, depth - 1)
        elif isinstance(value, list):
            for item in value:
                _collect_jobs(item, found, depth - 1)


def on_log_notification(server_name: str, params: Any) -> bool:
    """Queue the wake for a job-finished notification. True only when a wake was queued.

    Not a job event: untouched (False). A job event with no bound route — unknown job, foreign
    job, or one already woken — is logged and dropped (False)."""
    try:
        data, logger_name = getattr(params, "data", None), str(getattr(params, "logger", None) or "")
        job_id = _finished_job_id(data, logger_name)
        if job_id is None:
            return False
        with _lock:
            route = _routes.pop((server_name, job_id), None)
            if route is not None:
                _finish_row_locked((server_name, job_id), data)
        if route is None:
            logger.info("MCP server '%s': job %s finished but no call routed it here; not waking", server_name, job_id)
            return False
        _queue_wake(_wake_event(server_name, job_id, logger_name, data, route))
        return True
    except Exception:
        logger.debug("MCP job wake failed for '%s'", server_name, exc_info=True)
        return False


def _finished_job_id(data: Any, logger_name: str) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    event, job_id = data.get("event"), data.get("job_id")
    if not (isinstance(job_id, str) and job_id and isinstance(event, str)):
        return None
    if logger_name == QA_BUILD_LOGGER:
        return job_id if event == QA_BUILD_FINISHED else None
    return job_id if event.endswith("_finished") else None


def _wake_event(server_name: str, job_id: str, logger_name: str, data: dict, route: dict) -> dict:
    tail = data.get("failure_tail")
    return {
        "type": EVENT_TYPE,
        "session_id": wake_identity(server_name, job_id),  # the drains' per-event identity
        "session_key": route.get("session_key", ""), "task_id": route.get("task_id", ""),
        "owner_task_id": route.get("owner_task_id", ""), "parent_session_id": route.get("parent_session_id", ""),
        "server": server_name, "job_id": job_id, "job_kind": "qa_build" if logger_name == QA_BUILD_LOGGER else "",
        "outcome": str(data.get("outcome") or "finished"), "elapsed_ms": data.get("elapsed_ms"),
        "failure_tail": _redacted_tail(tail) if isinstance(tail, str) else "",
        "message": str(data.get("message") or "")[:_TAIL_CHARS],
    }


def wake_identity(server_name: str, job_id: str) -> str:
    """The wake's per-event identity: a 32-char digest of both names.

    Born when ``dispatch_delivery.accounting._event_key`` cut ids at 40 chars and a readable
    ``mcp_job:<server>:<job>`` made two wakes of one server on one day the same replay. That
    key now digests any longer id itself; this stays so the keys of wakes already queued
    do not move."""
    digest = hashlib.sha256(json.dumps([server_name, job_id]).encode("utf-8")).hexdigest()[:24]
    return f"mcp_job:{digest}"


def _redacted_tail(tail: str) -> str:
    tail = tail[-_TAIL_CHARS:]
    try:
        from agent.redact import redact_sensitive_text
        return redact_sensitive_text(tail)
    except Exception:
        return tail


def _queue_wake(event: dict) -> None:
    from tools.process_registry import process_registry
    process_registry.completion_queue.put(event)
    logger.info("MCP server '%s': job %s %s — wake queued for session %r",
                event["server"], event["job_id"], event["outcome"], event["session_key"])


def format_job_finished(evt: Mapping[str, Any]) -> str:
    """The ``[IMPORTANT: ...]`` text a drain injects for an ``mcp_job_finished`` event."""
    job_id, outcome = evt.get("job_id", "?"), str(evt.get("outcome") or "finished")
    tail = str(evt.get("failure_tail") or "")
    if evt.get("job_kind") == "qa_build":
        if outcome == "ready":
            return f"[IMPORTANT: QA build ready, job {job_id} — continue: call launch_or_attach/open_app_tab again.]"
        return (f"[IMPORTANT: QA build {outcome}, job {job_id} — read the failure tail, fix that cause, "
                f"then call launch_or_attach again to start a new build.\nFailure tail:\n{tail or '(none reported)'}]")
    message = str(evt.get("message") or "")
    return (f"[IMPORTANT: MCP server {evt.get('server', '?')} job {job_id} finished ({outcome})."
            + (f"\n{message}" if message else "") + (f"\nFailure tail:\n{tail}" if tail else "") + "]")


# Background-work rows: the ``mcp_job`` lane of ``running_work`` reads what these write.


def _running_row(server_name: str, job_id: str, routing: dict, facts: dict) -> dict:
    wall = time.time()
    pid, start = _writer()
    return {
        "server": server_name, "job_id": job_id, "label": facts.get("label") or f"{server_name} job {job_id}",
        "job_kind": facts.get("job_kind", ""), "status": ROW_RUNNING, "outcome": None,
        "started_at": wall - (facts.get("elapsed_ms") or 0) / 1000.0, "eta_ms": facts.get("eta_ms"),
        "expected_ms": facts.get("expected_ms"), "elapsed_ms": None, "finished_at": None, "failure_tail": "",
        "session_key": str(routing.get("session_key") or ""), "expires_at": wall + _ROUTE_TTL_S,
        "pid": pid, "host_start_time": start, "checkpoint": str(routing.get("checkpoint") or ""),
    }


def _finish_row_locked(key: tuple[str, str], data: dict) -> None:
    row = _rows.get(key)
    if row is None:
        return
    outcome, wall, tail = str(data.get("outcome") or "finished"), time.time(), data.get("failure_tail")
    row.update(status=ROW_READY if outcome in _OK_OUTCOMES else ROW_FAILED, outcome=outcome, eta_ms=0,
               elapsed_ms=_ms(data.get("elapsed_ms")), finished_at=wall,
               failure_tail=_redacted_tail(tail) if isinstance(tail, str) else "",
               expires_at=wall + _FINISHED_TTL_S)
    _write_checkpoints_locked(row["checkpoint"])


def note_wake_settled(evt: Mapping[str, Any]) -> bool:
    """The drain is done with this wake (delivered, steered, or dropped for good): retire its row.

    True when a row was removed. Any other event type, or a job with no row, is a no-op."""
    if not isinstance(evt, Mapping) or evt.get("type") != EVENT_TYPE:
        return False
    with _lock:
        row = _rows.pop((str(evt.get("server") or ""), str(evt.get("job_id") or "")), None)
        if row is not None:
            _write_checkpoints_locked(row["checkpoint"])
    return row is not None


def _writer() -> tuple[int, Any]:
    """This process's pid and spawn ticks — the reader's proof the rows' owner still lives."""
    global _writer_identity
    if _writer_identity is None:
        pid, start = os.getpid(), None
        try:
            from gateway.status import get_process_start_time
            start = get_process_start_time(pid)
        except Exception:
            start = None
        _writer_identity = (pid, start)
    return _writer_identity


def _write_checkpoints_locked(path: str) -> None:
    """Rewrite *path*: this process's rows for it, plus other writers' unexpired entries."""
    if not path:
        return
    pid, wall = _writer()[0], time.time()
    mine = [{k: v for k, v in row.items() if k != "checkpoint"} for row in _rows.values() if row["checkpoint"] == path]
    try:
        from utils import atomic_json_write
        foreign = [e for e in _read_checkpoint(path) if e.get("pid") != pid and _expires_after(e, wall)]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, foreign + mine)
    except Exception:
        logger.warning("MCP job checkpoint %s could not be written", Path(path).name, exc_info=True)


def _read_checkpoint(path: str) -> list[dict]:
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _expires_after(entry: dict, wall: float) -> bool:
    expires = entry.get("expires_at")
    return isinstance(expires, (int, float)) and expires > wall


def reset_for_tests() -> None:
    global _writer_identity
    with _lock:
        _routes.clear()
        _rows.clear()
        _writer_identity = None
