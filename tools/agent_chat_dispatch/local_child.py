"""The local dispatch leg's child process: ``tools.agent_chat_dispatch.local._spawn_child``'s spawn.

A sibling module so the supervisor pool carries no process spawn where none may start:
``local._spawn_child`` imports this only when ``conversations.subprocess_worker`` is on,
and the bundled phone profile switches it off. Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from .child import note_child_group

__layer__ = "lanes"
__all__ = ["close_job", "end_job", "hold_job_by_name", "open_job_by_name", "spawn_child"]

logger = logging.getLogger(__name__)


def spawn_child(argv: list[str], env: dict[str, str], *, job_name: str | None = None) -> subprocess.Popen:
    """Start the child: both streams piped, stdin closed, hidden on Windows, leading its own group.

    The child leads its own process group (POSIX) or Job Object (Windows), recorded with
    ``child.note_child_group``, so Stop, the budget kill and the settle reach what it
    started even after it exits (review w1118a.55 D10). Windows assigns the job right
    after the spawn: a grandchild started in the Python child's first moments, before
    the assignment, is outside it (the interpreter's boot outlasts that window).

    Windows names the job per request (``job_name``, review w1118a.56 D12) and creates it
    BEFORE the spawn with ``KILL_ON_JOB_CLOSE``: the child opens its own handle by that name
    (``hold_job_by_name``), so a serve restart leaves the job and the child running, a new
    serve opens it by name to Stop it, and when the last of serve and child is gone Windows
    ends whatever the request left.
    """

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        # Never inherit the parent's stdin: in serve that is the launcher's
        # request pipe, and a child reading from it would steal requests.
        "stdin": subprocess.DEVNULL,
        "env": env,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name != "nt":
        # detached-spawn: ok — the group exists so Stop, the budget kill and the settle end what the child left (child.end_child_group); a dispatch child may outlive its serve by design (its row settles when it exits)
        popen_kwargs["start_new_session"] = True
    job = _create_job(job_name) if os.name == "nt" else None
    try:
        proc = _popen_child(argv, popen_kwargs)
    except BaseException:
        if job is not None:
            close_job(job)
        raise
    note_child_group(proc.pid, _assign_job(proc, job) if os.name == "nt" else None)
    return proc


def _popen_child(argv: list[str], popen_kwargs: dict[str, Any]) -> subprocess.Popen:
    """The spawn itself; on Windows hidden and out of the serve's own job when that job allows it.

    The serve runs inside the venv redirector's kill-on-close job, which allows breakaway
    (``hermes_cli.process_identity``). A child left in it ended with the serve, so a restarted
    serve had no request to re-adopt (review w1118a.57 D10). It breaks away through the one
    spawn rule, ``_subprocess_compat.popen_breaking_away``; a job that refuses keeps it inside,
    as before. Its own named job (D12) is assigned after, in either case.
    """
    if os.name != "nt":
        return subprocess.Popen(argv, **popen_kwargs)
    from hermes_cli._subprocess_compat import popen_breaking_away, windows_hide_flags

    def refused(exc: OSError) -> None:
        logger.warning("dispatch child: the serve's job refused breakaway (%s); it ends with this serve", exc)

    # MUTATION: pass ``windows_hide_flags()`` straight to ``subprocess.Popen`` (no breakaway) and
    # test_a_windows_request_child_breaks_away_from_the_serves_job reddens.
    proc, _broke_away = popen_breaking_away(
        lambda flags: subprocess.Popen(argv, **popen_kwargs, creationflags=flags), windows_hide_flags(),
        on_refused=refused,
    )
    return proc


# --------------------------------------------------------------------------
# Windows: the child's Job Object (POSIX never reaches these)
# --------------------------------------------------------------------------


#: ``SetInformationJobObject``'s class for :class:`_ExtendedLimits`.
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
#: The job ends every process in it when its last handle closes (D12).
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
#: Access the child asks for its own handle: enough to hold the job open, nothing more.
JOB_OBJECT_QUERY = 0x0004
#: Access a serve asks for when it opens a re-adopted request's job: Stop and the settle end it.
JOB_OBJECT_TERMINATE = 0x0008

#: The child's own handle to its job (``hold_job_by_name``): never closed, it ends with the process.
_HELD_JOB: Any = None


def _job_structs() -> tuple[Any, Any]:
    """``(JOBOBJECT_BASIC_LIMIT_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION)`` as ctypes types."""

    import ctypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            # IO_COUNTERS: six ULONGLONG counters nothing here reads; only the struct's size matters.
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return _BasicLimits, _ExtendedLimits


def _job_kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # windows-footgun: ok — Windows-only, reached under os.name == "nt"
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def _create_job(job_name: str | None) -> Any:
    """A new Job Object named ``job_name`` (or unnamed) that ends its processes on its last close; None on failure."""

    import ctypes

    try:
        kernel32 = _job_kernel32()
        job = kernel32.CreateJobObjectW(None, job_name)
        if not job:
            return None
        _basic, extended = _job_structs()
        limits = extended()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            # Stop still reaches the tree through the job; only the end-on-last-close is lost.
            logger.warning("dispatch job %s: kill-on-close could not be set", job_name)
        return job
    except Exception:
        logger.debug("dispatch job %s could not be created", job_name, exc_info=True)
        return None


def _assign_job(proc: subprocess.Popen, job: Any) -> Any:
    """``job`` holding ``proc``, or None (the tree-kill alone then, as before)."""

    if job is None:
        return None
    try:
        kernel32 = _job_kernel32()
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        logger.debug("dispatch child %s job assignment failed", proc.pid, exc_info=True)
        return None


def open_job_by_name(job_name: str) -> Any:
    """This process's handle to a running request's job (a serve re-adopting it), or None."""

    try:
        job = _job_kernel32().OpenJobObjectW(JOB_OBJECT_TERMINATE | JOB_OBJECT_QUERY, False, job_name)
        return job or None
    except Exception:
        logger.debug("dispatch job %s could not be opened", job_name, exc_info=True)
        return None


def hold_job_by_name(job_name: str) -> bool:
    """In the dispatch child: open (non-inheritable) and keep its own handle to its job; True when held.

    The serve's handle alone used to be the job's life, so a serve restart would have ended
    every running request once the job ends on its last close (D12). Kept for the process's life.
    """

    global _HELD_JOB
    try:
        job = _job_kernel32().OpenJobObjectW(JOB_OBJECT_QUERY, False, job_name)
    except Exception:
        logger.debug("dispatch job %s could not be held", job_name, exc_info=True)
        return False
    if not job:
        return False
    _HELD_JOB = job
    return True


def end_job(job: Any) -> bool:
    """End every process in the child's Job Object; True when Windows accepted it."""

    try:
        return bool(_job_kernel32().TerminateJobObject(job, 1))
    except Exception:
        logger.debug("dispatch child job end failed", exc_info=True)
        return False


def close_job(job: Any) -> None:
    """Close this process's handle to a settled child's Job Object."""

    try:
        _job_kernel32().CloseHandle(job)
    except Exception:
        logger.debug("dispatch child job close failed", exc_info=True)
