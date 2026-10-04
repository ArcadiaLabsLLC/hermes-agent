"""The announced-job registry: one JSON record per build a writer announces, and the reader's rules.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §2.

**Location.** ``<background-work home>/builds/`` — the directory ``processes.json`` and
``mcp_jobs.json`` already resolve to (``get_hermes_background_work_home``), so writer and
reader agree the way those two do. One file per job, ``<job_id>.json``, written
temp-then-rename by the job's OWN writer: no shared file, no merge, the reader lists the
directory. A writer outside serve finds the directory through
:data:`~agent_runtime.builds.vocabulary.REGISTRY_DIR_ENV` (exported by serve at boot) or
``hermes harness builds registry-path --json``.

**The reader's rules** (:func:`evaluate`), all here so there is one authority:

* ``expires_at`` passed ⇒ the record is dropped ``by_design`` (``build_record_expired``);
  a FILE is deleted only by the serve-boot sweep, never by a read.
* a writer that is dead or recycled while the record says ``running``/``queued`` ⇒
  ``liveness: dead``, ``outcome: lost``, status ``error`` — the row is KEPT, because a
  lost build is exactly what the operator must see.
* a writer whose identity cannot be proven ⇒ ``liveness: unknown``, status ``unknown``,
  and a reader-side ``writer_unidentified`` unknown on the ROW (never in the file).
* ``heartbeat_at`` older than ``stall_seconds`` ⇒ ``stalled``; at half that, ``stalling``.
  A ``queued`` record is never stalled: a slot wait is silent by design.

The projection stays read-only: this module's readers open nothing for write. The PID
identity probe is INJECTED (``pid_identity``) so this module never imports the
``running_work`` package, which imports it.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_runtime.builds.vocabulary import (
    BUILD_OUTCOMES,
    BUILD_REGISTRY_DIRNAME,
    DEFAULT_STALL_SECONDS,
    FINISHED_RECORD_TTL_SECONDS,
    LIVENESS_DEAD,
    LIVENESS_LIVE,
    LIVENESS_STALLED,
    LIVENESS_UNKNOWN,
    OUTCOME_LOST,
    OUTCOME_SUCCEEDED,
    RECORD_CONTROL_NONE,
    RECORD_STATUS_QUEUED,
    RECORD_STATUS_RUNNING,
    REGISTRY_DIR_ENV,
    REGISTRY_SCHEMA_VERSION,
    RUNNING_RECORD_TTL_SECONDS,
    STOP_REQUEST_SUFFIX,
)

__layer__ = "stores"

#: The wire status a row carries, from the evaluated state (§1's table).
STATUS_RUNNING = "running"
STATUS_STALLING = "stalling"
STATUS_STALLED = "stalled"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"
#: A row is ``stalling`` once its quiet time reaches this share of ``stall_seconds``.
STALLING_FRACTION = 0.5

#: ``_pid_identity`` verdicts that DISPROVE the writer is alive (``running_work.vocabulary``).
_DISPROVEN = frozenset({"dead", "recycled"})

#: Every key a v1 record carries, with its default; :func:`new_record` fills the gaps.
RECORD_DEFAULTS: dict[str, Any] = {
    "schema_version": REGISTRY_SCHEMA_VERSION,
    "job_id": "",
    "toolchain": "unknown",
    "target": "",
    "mode": "",
    "project_root": "",
    "label": "",
    "started_by": {"kind": "tool", "label": ""},
    "session_key": "",
    "mcp_job": None,
    "writer": {"pid": None, "host_start_time": None},
    "build_pid": None,
    "build_host_start_time": None,
    "status": RECORD_STATUS_RUNNING,
    "stage": "unknown",
    "stage_detail": "",
    "started_at": None,
    "heartbeat_at": None,
    "finished_at": None,
    "expected_ms": None,
    "outcome": None,
    "exit_code": None,
    "artifact": None,
    "log_path": "",
    "tail": "",
    "controls": {"stop": RECORD_CONTROL_NONE, "restart": RECORD_CONTROL_NONE},
    "restart": None,
    "unknowns": [],
    "expires_at": None,
}


def registry_dir() -> Path:
    """The registry directory under the background-work home (the reader's authority)."""

    from agent_runtime.profile_home import get_hermes_background_work_home

    return Path(get_hermes_background_work_home()) / BUILD_REGISTRY_DIRNAME


def writer_registry_dir() -> Path | None:
    """Where a WRITER announces: the exported env value, else None (announce nothing, say so)."""

    value = os.environ.get(REGISTRY_DIR_ENV, "").strip()
    return Path(value) if value else None


def new_record(**fields: Any) -> dict[str, Any]:
    """A complete v1 record: every key present, ``fields`` over the defaults, TTL filled in."""

    record = {key: (dict(value) if isinstance(value, dict) else value) for key, value in RECORD_DEFAULTS.items()}
    record.update(fields)
    if record.get("expires_at") is None:
        record["expires_at"] = expiry_for(record)
    return record


def expiry_for(record: dict[str, Any]) -> float | None:
    """start + 6 h while running; finish + 30 min once finished; None when neither stamp exists."""

    finished = _epoch(record.get("finished_at"))
    if finished is not None:
        return finished + FINISHED_RECORD_TTL_SECONDS
    started = _epoch(record.get("started_at"))
    return None if started is None else started + RUNNING_RECORD_TTL_SECONDS


def write_record(directory: Path, record: dict[str, Any]) -> Path:
    """Temp-then-rename the record to ``<directory>/<job_id>.json`` (the writer's own file)."""

    job_id = str(record.get("job_id") or "").strip()
    if not job_id or any(sep in job_id for sep in ("/", "\\", "..")):
        raise ValueError(f"invalid job_id {job_id!r}")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{job_id}.json"
    fd, temp = tempfile.mkstemp(prefix=f".{job_id}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return target


def stop_request_path(directory: Path, job_id: str) -> Path:
    return directory / f"{job_id}{STOP_REQUEST_SUFFIX}"


@dataclass(frozen=True)
class RecordFile:
    """One ``*.json`` under the registry: its parsed record, or the error class that refused it."""

    path: Path
    record: dict[str, Any] | None
    error: str = ""


def read_records(directory: Path) -> tuple[list[RecordFile], str]:
    """Every record file, or ``([], <exception class>)`` when the directory itself cannot be listed.

    An ABSENT directory is zero records, proven — the same answer as an empty one.
    """

    try:
        names = sorted(entry for entry in os.listdir(directory) if entry.endswith(".json"))
    except FileNotFoundError:
        return [], ""
    except OSError as exc:
        return [], type(exc).__name__
    return [_read_one(directory / name) for name in names], ""


def _read_one(path: Path) -> RecordFile:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return RecordFile(path, None, type(exc).__name__)
    if not isinstance(record, dict) or record.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        return RecordFile(path, None, "schema_mismatch")
    return RecordFile(path, record)


@dataclass(frozen=True)
class RecordVerdict:
    """What the reader concluded about one record (§1's liveness/outcome/status table)."""

    expired: bool
    liveness: str
    outcome: str | None
    status: str
    writer_verified: bool
    writer_identified: bool
    heartbeat_age: float | None


def _epoch(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _default_pid_identity(pid: Any, expected: Any) -> tuple[bool, bool, str]:
    from agent_runtime.running_work.ownership import _pid_identity

    return _pid_identity(pid, expected)


def evaluate(
    record: dict[str, Any],
    *,
    now: float | None = None,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    pid_identity: Callable[[Any, Any], tuple[bool, bool, str]] | None = None,
) -> RecordVerdict:
    """Apply the reader's rules to one record. Pure apart from the injected identity probe."""

    now = time.time() if now is None else now
    expires = _epoch(record.get("expires_at"))
    expired = expires is not None and expires <= now
    outcome = record.get("outcome") if record.get("outcome") in BUILD_OUTCOMES else None
    if outcome is not None:
        status = STATUS_COMPLETED if outcome == OUTCOME_SUCCEEDED else STATUS_ERROR
        return RecordVerdict(expired, LIVENESS_DEAD, outcome, status, True, True, None)
    writer = record.get("writer") if isinstance(record.get("writer"), dict) else {}
    probe = pid_identity or _default_pid_identity
    _alive, verified, verdict = probe(writer.get("pid"), writer.get("host_start_time"))
    if verdict in _DISPROVEN:
        return RecordVerdict(expired, LIVENESS_DEAD, OUTCOME_LOST, STATUS_ERROR, False, True, None)
    if not verified:
        return RecordVerdict(expired, LIVENESS_UNKNOWN, None, STATUS_UNKNOWN, False, False, None)
    return _heartbeat_verdict(record, expired=expired, now=now, stall_seconds=stall_seconds)


def _heartbeat_verdict(record: dict[str, Any], *, expired: bool, now: float, stall_seconds: float) -> RecordVerdict:
    beat = _epoch(record.get("heartbeat_at")) or _epoch(record.get("started_at"))
    age = None if beat is None else max(0.0, now - beat)
    if record.get("status") == RECORD_STATUS_QUEUED or age is None:
        return RecordVerdict(expired, LIVENESS_LIVE, None, STATUS_RUNNING, True, True, age)
    if age >= stall_seconds:
        return RecordVerdict(expired, LIVENESS_STALLED, None, STATUS_STALLED, True, True, age)
    status = STATUS_STALLING if age >= stall_seconds * STALLING_FRACTION else STATUS_RUNNING
    return RecordVerdict(expired, LIVENESS_LIVE, None, status, True, True, age)


def gc_expired(directory: Path, *, now: float | None = None, grace_seconds: float) -> list[str]:
    """Delete record files (and their stop requests) past ``expires_at`` + ``grace_seconds``.

    The SERVE-BOOT sweep's verb (§2): the projection never deletes. Returns the job ids removed.
    """

    now = time.time() if now is None else now
    files, _error = read_records(directory)
    removed: list[str] = []
    for item in files:
        expires = _epoch((item.record or {}).get("expires_at"))
        if expires is None or expires + grace_seconds > now:
            continue
        job_id = str(item.record.get("job_id") or item.path.stem)
        item.path.unlink(missing_ok=True)
        stop_request_path(directory, job_id).unlink(missing_ok=True)
        removed.append(job_id)
    return removed
