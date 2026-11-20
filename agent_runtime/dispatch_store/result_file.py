"""A dispatch child's durable answer: one result file per request, written before its stdout.

Review w1118a.56 D12 (rows ``RT-AGENT-REQUEST-STILL-RUNNING-WHEN-ITS-SERVE-RESTARTS-IS-PICKED-UP-AGAIN``
and ``RT-WINDOWS-STOP-AFTER-ITS-SUPERVISOR-ENDED-REACHES-WHAT-A-REQUEST-LEFT``): the child's answer used to
reach the store only through its supervising serve's stdout pump, so a child that outlived its serve
wrote its answer into a closed pipe and the request settled ``unknown``. The child now writes its
payload here first (temp + rename, so a reader never sees half of it), then prints it; whoever settles
the request — its supervisor, a serve that re-adopted it, or the orphan sweep — reads it here.

Both halves of the hand-over meet in this module so neither re-spells the other:

* the SERVE side names the file (:func:`dispatch_result_path`) and hands it, with the Windows job's name,
  to the child through :data:`RESULT_FILE_ENV` / :data:`JOB_NAME_ENV`;
* the CHILD side takes both out of its environment at the start of its turn
  (:func:`claim_dispatch_child_env`, so nothing the turn starts inherits them) and writes its payload
  through :func:`write_claimed_result`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

__layer__ = "stores"

__all__ = [
    "JOB_NAME_ENV",
    "RESULT_FILE_ENV",
    "claim_dispatch_child_env",
    "discard_dispatch_result",
    "dispatch_job_name",
    "dispatch_result_path",
    "read_dispatch_result",
    "tolerate_closed_streams",
    "write_claimed_result",
]

logger = logging.getLogger(__name__)

#: The child's result file, named by its supervisor. Absent in every other process.
RESULT_FILE_ENV = "HERMES_DISPATCH_RESULT_FILE"
#: The Windows Job Object the child holds its own handle to (D12). Absent on POSIX.
JOB_NAME_ENV = "HERMES_DISPATCH_JOB_NAME"

_RESULTS_DIRNAME = "dispatch_results"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")

#: What this process claimed from its environment: the result file it writes, if it is a dispatch child.
_claimed_result_path: Path | None = None


def _safe_id(dispatch_id: str) -> str:
    safe = _UNSAFE.sub("_", str(dispatch_id or ""))[:120]
    if not safe.strip("._"):
        raise ValueError(f"no result file for dispatch id {dispatch_id!r}")
    return safe


def dispatch_result_path(dispatch_id: str) -> Path:
    """Where the child of *dispatch_id* writes its answer: beside the dispatch store's database."""

    from .db import dispatch_db_path

    return dispatch_db_path().parent / _RESULTS_DIRNAME / f"{_safe_id(dispatch_id)}.json"


def dispatch_job_name(dispatch_id: str) -> str:
    """The Windows Job Object's name for *dispatch_id*: per logon session (``Local\\``), per request."""

    return f"Local\\hermes-dispatch-{_safe_id(dispatch_id)}"


def read_dispatch_result(dispatch_id: str) -> dict[str, Any] | None:
    """The payload the child of *dispatch_id* left, or ``None`` (none written, or unreadable)."""

    try:
        path = dispatch_result_path(dispatch_id)
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        logger.warning("dispatch %s result file is not JSON; ignored", dispatch_id)
        return None
    return payload if isinstance(payload, dict) else None


def discard_dispatch_result(dispatch_id: str) -> None:
    """Remove the result file once the request is settled (or before a fresh child starts). Never raises."""

    try:
        dispatch_result_path(dispatch_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.debug("dispatch %s result file discard failed", dispatch_id, exc_info=True)


def claim_dispatch_child_env() -> tuple[Path | None, str | None]:
    """In a dispatch child: take the result file and job name out of the environment; ``(path, job)``.

    Removed from ``os.environ`` so a process the turn starts (a nested ``hermes`` call) never writes
    this request's answer. Idempotent: a second call answers the first claim's path and no job.
    """

    global _claimed_result_path
    raw = os.environ.pop(RESULT_FILE_ENV, None)
    job = os.environ.pop(JOB_NAME_ENV, None) or None
    if raw:
        _claimed_result_path = Path(raw)
    return _claimed_result_path, job


def write_claimed_result(payload: dict[str, Any]) -> bool:
    """Write *payload* to this child's claimed result file (temp + rename); True when written.

    No claim (any process that is not a dispatch child) writes nothing. A write failure is logged
    and answers False: stdout still carries the payload to a live supervisor.
    """

    path = _claimed_result_path
    if path is None:
        return False
    try:
        from utils import atomic_json_write

        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, payload, indent=None, default=str)
        return True
    except Exception:
        logger.warning("dispatch result file %s could not be written", path, exc_info=True)
        return False


class _ClosedPipeTolerantStream:
    """A text stream whose write/flush swallow a closed pipe (D12: the child outlives its serve).

    Once the serve that read the child's stdout and stderr is gone, every write meets a closed
    pipe; an unguarded ``print`` anywhere in the turn would then end the turn before its answer
    reached the result file. Everything else is the wrapped stream's own.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        try:
            return self._stream.write(text)
        except (OSError, ValueError):
            return len(text)

    def flush(self) -> None:
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def tolerate_closed_streams() -> None:
    """In a dispatch child: make ``sys.stdout`` / ``sys.stderr`` survive their reader's end. Idempotent."""

    import sys

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and not isinstance(stream, _ClosedPipeTolerantStream):
            setattr(sys, name, _ClosedPipeTolerantStream(stream))
