"""The run's working directory and the in-flight run census (one lock, one
counter, one writer).
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from threading import Lock, RLock

from agent_runtime.profile_runner.errors import ProfileRunnerError

__layer__ = "stores"

__all__ = [
    "_ACTIVE_RUNS",
    "_ACTIVE_RUNS_LOCK",
    "_WORKDIR_LOCK",
    "_agent_workdir",
    "_counted_agent_run",
    "_validate_workdir",
    "agent_runs_in_flight",
]


def _validate_workdir(workdir: Path | None) -> None:
    if workdir is None:
        return
    path = Path(workdir).expanduser()
    if not path.is_dir():
        raise ProfileRunnerError("requested agent workdir does not exist or is not a directory")


@contextmanager
def _agent_workdir(workdir: Path | None):
    if workdir is None:
        yield
        return
    path = Path(workdir).expanduser().resolve()
    with _WORKDIR_LOCK:
        previous_cwd = Path.cwd()
        had_terminal_cwd = "TERMINAL_CWD" in os.environ
        previous_terminal_cwd = os.environ.get("TERMINAL_CWD")
        try:
            os.chdir(path)
            os.environ["TERMINAL_CWD"] = str(path)
        except OSError as exc:
            raise ProfileRunnerError("requested agent workdir could not be entered") from exc
        try:
            yield
        finally:
            os.chdir(previous_cwd)
            if had_terminal_cwd:
                os.environ["TERMINAL_CWD"] = previous_terminal_cwd or ""
            else:
                os.environ.pop("TERMINAL_CWD", None)


# Serializes every ``_execute_agent_run`` body, on purpose — NOT only the
# ``os.chdir`` swap in ``_agent_workdir``. Two process-global mutations make the
# wide scope load-bearing (audited 2026-08-09):
#   1. ``persona_profile_context`` saves/mutates/restores HERMES_HOME / HOME /
#      HERMES_AUTH_HOME / HERMES_AGENT_RUNTIME_ROOT in ``os.environ``. The
#      restore is only correct while runs are serialized; concurrent entry is a
#      lost-update race that leaves the process env pointing at a finished
#      turn's profile (see the pin comment in profile_context.py for the env
#      readers that keep those writes alive).
#   2. ``_agent_workdir`` chdirs the process and holds this lock across its
#      whole body (including the yield) whenever a workdir is set, so
#      workdir-bearing runs would still serialize even if the outer
#      acquisition were removed — removing it would only let workdir-less runs
#      race the env mutation in (1).
# Shrinking this lock to just the chdir swap is the desired end state, but it
# requires first context-scoping every reader listed in profile_context.py and
# deleting the env writes. Do not shrink it before that.
_WORKDIR_LOCK = RLock()


#: Real agent runs currently between ``ProfileAgentRunner.run``'s entry and its
#: return, in THIS process. Not a lock and never waited on — a background
#: prewarm reads it to decide whether to stand down.
#:
#: Why it exists: ``_WORKDIR_LOCK`` serializes every run in the process, so a
#: prewarm construction that holds it while an operator message arrives ADDS the
#: full construction cost to that turn instead of removing it. The lock itself
#: cannot answer "is anyone about to want this" — by the time a run blocks on it
#: the damage is done — so the yield decision is taken BEFORE the prewarm enters
#: the scope stack, on this counter.
#:
#: Deliberately counted at ``run`` rather than at the lock: the window that
#: matters starts when a turn enters the runner (it still has admission,
#: profile-context install and MCP admission to do before it needs the agent),
#: not when it reaches the lock. A prewarm that stands down for a turn that
#: turns out to be for the SAME chat root loses nothing — that turn builds the
#: actor it would have built, and registers it in the same registry.
_ACTIVE_RUNS_LOCK = Lock()


_ACTIVE_RUNS = 0


def agent_runs_in_flight() -> int:
    """How many real agent runs this process is inside right now."""

    with _ACTIVE_RUNS_LOCK:
        return _ACTIVE_RUNS


@contextmanager
def _counted_agent_run():
    global _ACTIVE_RUNS
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS += 1
    try:
        yield
    finally:
        with _ACTIVE_RUNS_LOCK:
            _ACTIVE_RUNS -= 1
