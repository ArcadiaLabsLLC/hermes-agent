"""The run's working directory and the in-flight run census (one lock, one
counter, one writer).
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import os
from pathlib import Path
from threading import Condition, Lock, RLock, get_ident, local

from agent_runtime.profile_runner.errors import ProfileRunnerError

__layer__ = "stores"

__all__ = [
    "_ACTIVE_RUNS",
    "_ACTIVE_RUNS_LOCK",
    "_PROCESS_HOME",
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
        from hermes_cli.harness_parts._upstream_doors import ensure_terminal_env_bridged

        ensure_terminal_env_bridged()
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


class _ProcessHomeGate:
    """``HOME`` is ONE process value: runs that want the same one hold it together, any other waits.

    ``os.path.expanduser`` / ``Path.home()`` read ``HOME`` on POSIX and have no context hook, so a
    run whose profile carries a ``home/`` directory still needs the process write. What that needs
    is that every run in flight wants the value in force — not that one run is in flight. Until
    2026-11-12 this was one ``RLock`` held for each run's whole body, bound or not: an agent
    waiting on a slow model call froze every other agent's next turn before its agent was even
    built (RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL: 80-143 s, live), although on a host no
    profile has a ``home/`` and nothing was ever written.

    * ``value`` is the ``HOME`` in force: a path, or ``None`` for "the process's own, unwritten".
      Runs wanting it enter side by side; the first in writes it, the last out restores it.
    * A run wanting another value waits until the holders are out, and holds its place in line:
      later arrivals queue behind it, so same-value traffic cannot starve it.
    * Reentrant per thread, as the ``RLock`` was. A nested run that writes nothing, or wants the
      value in force, joins. A nested run wanting ANOTHER value takes ``HOME`` to itself: it waits
      for every other holder to leave, nobody enters while it runs, and its exit puts the outer
      value back. Two threads asking for that at once would wait on each other for ever; the
      second is refused instead (no production path nests a run in-process: an inline send from
      inside a run goes to a child process, ``tools/agent_chat/send.py``).

    The upstream door that retires the write itself is run-serialization decision 3 (row
    ``RT-POSIX-TURNS-SERIALIZE-BEHIND``): runs whose profiles carry DIFFERENT ``home/``
    directories still take turns.
    """

    def __init__(self) -> None:
        self._changed = Condition()
        self._value: str | None = None
        self._holders = 0
        self._line: deque[object] = deque()
        #: What ``HOME`` was before the first holder of the value in force wrote it.
        self._before: str | None = None
        #: The thread a nested run gave ``HOME`` to alone; nobody else enters while it is set.
        self._sole_owner: int | None = None
        self._held = local()

    @staticmethod
    def _write(home: str | None) -> str | None:
        """Point ``HOME`` at ``home`` (``None`` writes nothing); what it was, to put back."""

        before = os.environ.get("HOME")
        if home is not None:
            os.environ["HOME"] = home
        return before

    @staticmethod
    def _restore(home: str | None, before: str | None) -> None:
        if home is None:
            return
        if before is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = before

    @contextmanager
    def hold(self, home: str | None):
        depth = getattr(self._held, "depth", 0)
        me = get_ident()
        sole = False
        with self._changed:
            if depth and (home is None or home == self._value):
                pass  # joins the value in force; nothing to write or put back
            elif depth:
                if self._sole_owner not in (None, me):
                    raise ProfileRunnerError("another run is changing the process home; a nested run cannot")
                sole, outer_owner = True, self._sole_owner
                self._sole_owner = me
                try:
                    while self._holders > depth:
                        self._changed.wait()
                except BaseException:
                    self._sole_owner = outer_owner
                    self._changed.notify_all()
                    raise
                outer_value, self._value = self._value, home
                before = self._write(home)
            else:
                place = object()
                self._line.append(place)
                try:
                    while not (self._line[0] is place and self._sole_owner is None
                               and (self._holders == 0 or self._value == home)):
                        self._changed.wait()
                finally:
                    self._line.remove(place)
                    self._changed.notify_all()
                if self._holders == 0:
                    self._value = home
                    self._before = self._write(home)
            self._holders += 1
        self._held.depth = depth + 1
        try:
            yield
        finally:
            self._held.depth = depth
            with self._changed:
                self._holders -= 1
                if sole:
                    self._restore(home, before)
                    self._value, self._sole_owner = outer_value, outer_owner
                elif self._holders == 0:
                    self._restore(self._value, self._before)
                    self._value = None
                self._changed.notify_all()


#: The one gate every POSIX run passes for the ONE process write left: ``HOME``.
_PROCESS_HOME = _ProcessHomeGate()


@contextmanager
def _posix_process_home(binding):
    """POSIX: point ``HOME`` at the profile's ``home/`` for the run, beside every run that wants the same.

    A profile without a ``home/`` writes nothing and runs beside every other such run; see
    :class:`_ProcessHomeGate` for what waits and why that is all the write needs.
    Native Windows: a no-op — ``ntpath.expanduser`` reads ``USERPROFILE``, never ``HOME``
    (measured, field notes S1), and every factory-built child computes its own ``HOME``.
    """

    if os.name == "nt":
        yield
        return
    profile_home = getattr(binding, "profile_home", None)
    home_dir = Path(profile_home) / "home" if profile_home is not None else None
    with _PROCESS_HOME.hold(str(home_dir) if home_dir is not None and home_dir.exists() else None):
        yield


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
