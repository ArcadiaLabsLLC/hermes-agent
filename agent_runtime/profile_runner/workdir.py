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
    "_PROCESS_HOME_LOCK",
    "_WORKDIR_LOCK",
    "_agent_workdir",
    "_counted_agent_run",
    "_posix_process_home",
    "_validate_workdir",
    "_workspace_turnstile",
    "agent_runs_in_flight",
    "root_run_lock",
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


# The workspace writer's lock, no longer a whole-run lock (run-serialization S5,
# 2026-10-16). Until S5 every run held it for its whole body, because
# ``persona_profile_context`` and ``_agent_workdir`` rewrote process-global env and
# cwd; S2-S4 moved all of that into the run's context, so a run now passes through
# it once at entry (:func:`_workspace_turnstile`) and holds :func:`root_run_lock`
# instead. Its remaining holders are the operator workspace writers
# (``operator_checkpoints.restore_operator_checkpoint``,
# ``operator_undo._workspace_writer``): they take it non-blocking, refuse while
# ``agent_runs_in_flight()`` is non-zero, and while they hold it no run body starts.
_WORKDIR_LOCK = RLock()


@contextmanager
def _workspace_turnstile():
    """Pass through ``_WORKDIR_LOCK`` once: a run never STARTS while a workspace writer holds it."""

    with _WORKDIR_LOCK:
        pass
    yield


#: Key a run with no chat root shares: unrooted runs keep serializing among themselves.
UNROOTED_RUN_KEY = "<unrooted>"

_ROOT_LOCKS_GUARD = Lock()
#: ``root key -> [RLock, holders]``; an entry lives while anyone holds or waits on it.
_ROOT_LOCKS: dict[str, list] = {}


@contextmanager
def root_run_lock(root_key: str | None):
    """One run at a time per chat root (run-serialization S5). Other roots run alongside.

    The conversation model needs this regardless of process state: two turns of one
    root would interleave one transcript. Reentrant, so a nested run of the same root
    on the same thread (a relay hop back into its own root) does not deadlock itself.
    """

    key = str(root_key or "").strip() or UNROOTED_RUN_KEY
    with _ROOT_LOCKS_GUARD:
        entry = _ROOT_LOCKS.setdefault(key, [RLock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _ROOT_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0 and _ROOT_LOCKS.get(key) is entry:
                del _ROOT_LOCKS[key]


#: Serializes runs on POSIX only, for the ONE process write left: ``HOME``.
_PROCESS_HOME_LOCK = RLock()


@contextmanager
def _posix_process_home(binding):
    """POSIX: hold ``_PROCESS_HOME_LOCK`` for the run and point ``HOME`` at the profile's ``home/``.

    ``os.path.expanduser`` / ``Path.home()`` read ``HOME`` on POSIX and have no context hook,
    so a persona whose ``~`` must resolve to its profile (``skills.external_dirs`` spelled
    with ``~``, the ``~/.codex`` / ``~/.qwen`` credential files) still needs the process
    write — and the write is only sound while every run on the box is serialized behind
    this lock, bound or not. The upstream door that retires it is plan decision 3.
    Native Windows: a no-op — ``ntpath.expanduser`` reads ``USERPROFILE``, never ``HOME``
    (measured, field notes S1), and every factory-built child computes its own ``HOME``.
    """

    if os.name == "nt":
        yield
        return
    with _PROCESS_HOME_LOCK:
        profile_home = getattr(binding, "profile_home", None)
        home_dir = Path(profile_home) / "home" if profile_home is not None else None
        if home_dir is None or not home_dir.exists():
            yield
            return
        previous = os.environ.get("HOME")
        os.environ["HOME"] = str(home_dir)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous


#: Real agent runs currently between ``ProfileAgentRunner.run``'s entry and its
#: return, in THIS process. Not a lock and never waited on — a background
#: prewarm reads it to decide whether to stand down.
#:
#: Why it exists: a prewarm holds its chat root's lock (``root_run_lock``; until
#: run-serialization S5 it was the process-wide ``_WORKDIR_LOCK``), so a
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
