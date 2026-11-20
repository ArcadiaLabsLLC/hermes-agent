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
__all__ = ["close_job", "end_job", "spawn_child"]

logger = logging.getLogger(__name__)


def spawn_child(argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start the child: both streams piped, stdin closed, hidden on Windows, leading its own group.

    The child leads its own process group (POSIX) or Job Object (Windows), recorded with
    ``child.note_child_group``, so Stop, the budget kill and the settle reach what it
    started even after it exits (review w1118a.55 D10). Windows assigns the job right
    after the spawn: a grandchild started in the Python child's first moments, before
    the assignment, is outside it (the interpreter's boot outlasts that window).
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
    if os.name == "nt":
        try:
            from hermes_cli._subprocess_compat import windows_hide_flags

            popen_kwargs["creationflags"] = windows_hide_flags()
        except Exception:
            pass
    else:
        # detached-spawn: ok — the group exists so Stop, the budget kill and the settle end what the child left (child.end_child_group); a dispatch child may outlive its serve by design (its row settles when it exits)
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **popen_kwargs)
    note_child_group(proc.pid, _assign_job(proc) if os.name == "nt" else None)
    return proc


# --------------------------------------------------------------------------
# Windows: the child's Job Object (POSIX never reaches these)
# --------------------------------------------------------------------------


def _job_kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # windows-footgun: ok — Windows-only, reached under os.name == "nt"
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def _assign_job(proc: subprocess.Popen) -> Any:
    """A new Job Object holding ``proc``, or None (the tree-kill alone then, as before)."""

    try:
        kernel32 = _job_kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        logger.debug("dispatch child %s job assignment failed", proc.pid, exc_info=True)
        return None


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
