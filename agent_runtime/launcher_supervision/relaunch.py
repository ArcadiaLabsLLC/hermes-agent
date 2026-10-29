"""The relaunch's I/O: verify the beat's executable, kill one hung pid, spawn the launcher detached.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` decisions 5 and 8
(slice W2). :mod:`.policy` decides WHEN; this module is the only code that touches another process.

* **Identity** — a beat's ``executable`` must real-path to the same file as ``psutil.Process(pid).exe()``.
  That is what stops a local caller turning a beat into "run this program": the harness only ever
  relaunches the binary the launcher it watched was actually running. Unreadable is a mismatch.
* **Kill** — the one pid (``psutil.Process.kill``: ``TerminateProcess`` / ``SIGKILL``), never its tree,
  so a game the launcher started survives; refused when the pid's creation time is not the one the
  watch recorded (a reused pid is not the launcher).
* **Spawn** — ``[executable, --harness-relaunch=<reason>, (--start-hidden)]``, out of the harness's
  process tree (``windows_detach_flags`` on Windows, ``start_new_session`` on POSIX), with the
  harness's environment minus every ``HERMES_*`` variable.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence

__layer__ = "lanes"

__all__ = [
    "RELAUNCH_FLAG",
    "START_HIDDEN_FLAG",
    "Relauncher",
    "kill_one",
    "relaunch_argv",
    "relaunch_env",
    "same_executable",
    "spawn_detached",
]

#: The launcher's flags (§2, the launcher plan's wire): the reason word, and the hidden start.
RELAUNCH_FLAG = "--harness-relaunch"
START_HIDDEN_FLAG = "--start-hidden"
#: Creation times read twice from ``psutil`` agree to well inside this.
_CREATE_TIME_TOLERANCE = 0.5


def same_executable(pid: int, executable: str) -> bool:
    """Is ``executable`` the file ``pid`` is running? Unreadable (gone, denied) is ``False``."""
    try:
        import psutil

        running = psutil.Process(pid).exe()
    except Exception:
        return False
    if not running:
        return False
    try:
        return os.path.samefile(os.path.realpath(running), os.path.realpath(executable))
    except OSError:
        return False


def kill_one(pid: int, create_time: float | None) -> bool:
    """Terminate ``pid`` alone; ``False`` when it is gone or is no longer the process the watch saw."""
    try:
        import psutil

        process = psutil.Process(pid)
        if create_time is not None and abs(process.create_time() - create_time) > _CREATE_TIME_TOLERANCE:
            return False
        process.kill()
        return True
    except Exception:
        return False


def relaunch_argv(executable: str, reason: str, *, start_hidden: bool) -> list[str]:
    argv = [executable, f"{RELAUNCH_FLAG}={reason}"]
    if start_hidden:
        argv.append(START_HIDDEN_FLAG)
    return argv


def relaunch_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The harness's environment minus ``HERMES_*``: the launcher picks its own runtime, not this one's."""
    return {key: value for key, value in environ.items() if not key.upper().startswith("HERMES_")}


def spawn_detached(argv: Sequence[str]) -> int | None:
    """Start ``argv`` outside this process tree; its pid, or ``None`` when it could not start."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "env": relaunch_env(os.environ), "close_fds": True}
    if sys.platform == "win32":
        from hermes_cli._subprocess_compat import windows_detach_flags, windows_detach_flags_without_breakaway

        try:
            return subprocess.Popen(list(argv), creationflags=windows_detach_flags(), **kwargs).pid
        except PermissionError:  # a job that forbids breakaway
            kwargs["creationflags"] = windows_detach_flags_without_breakaway()
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(list(argv), **kwargs).pid
    except OSError:
        return None


class Relauncher:
    """The three effects as one injectable object (tests substitute it)."""

    def same_executable(self, pid: int, executable: str) -> bool:
        return same_executable(pid, executable)

    def kill(self, pid: int, create_time: float | None) -> bool:
        return kill_one(pid, create_time)

    def spawn(self, argv: Sequence[str]) -> int | None:
        return spawn_detached(argv)
