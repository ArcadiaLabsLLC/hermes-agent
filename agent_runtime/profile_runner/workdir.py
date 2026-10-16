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
    """Ground this run in *workdir* CONTEXT-LOCALLY: no ``os.chdir``, no env write.

    Run-serialization S4. The directory reaches the tools through upstream's own
    per-context channel, the terminal scope (``tools.terminal_scope``): every
    ``TERMINAL_*`` read (``terminal_env`` / ``_tenv``) and ``resolve_agent_cwd()`` answer
    from it, so the terminal tool, the file tools' workspace anchor, context-file
    discovery and the system prompt all see this run's directory while another run in
    the same process sees its own. The scope is this run's current policy with
    ``TERMINAL_CWD`` replaced: a bound scope is copied, an unbound one is the process
    env's ``TERMINAL_*`` after upstream's one-shot config bridge — the same values the
    tools read before, so only the directory changes. A refusal scope is kept as is
    (the run cannot use a terminal; grounding does not lift that).
    """

    if workdir is None:
        yield
        return
    path = Path(workdir).expanduser().resolve()
    if not path.is_dir():
        raise ProfileRunnerError("requested agent workdir could not be entered")
    from tools.terminal_scope import (
        TerminalPolicyRefusal,
        get_terminal_scope,
        reset_terminal_scope,
        set_terminal_scope,
    )

    current = get_terminal_scope()
    if isinstance(current, TerminalPolicyRefusal):
        yield
        return
    if current is None:
        from tools.terminal_tool import _ensure_terminal_env_bridged

        _ensure_terminal_env_bridged()
        current = {key: value for key, value in os.environ.items() if key.startswith("TERMINAL_")}
    token = set_terminal_scope({**current, "TERMINAL_CWD": str(path)})
    try:
        yield
    finally:
        reset_terminal_scope(token)


# Serializes every ``_execute_agent_run`` body, on purpose. One process-global
# mutation still makes the wide scope load-bearing (audited 2026-08-09; the
# ``os.chdir`` half was retired by run-serialization S4, 2026-10-16):
# ``persona_profile_context`` saves/mutates/restores HERMES_HOME / HOME /
# HERMES_AUTH_HOME / HERMES_AGENT_RUNTIME_ROOT in ``os.environ``. The restore is
# only correct while runs are serialized; concurrent entry is a lost-update race
# that leaves the process env pointing at a finished turn's profile. S5 of
# docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md
# deletes those writes and shrinks this lock to one per chat root.
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
