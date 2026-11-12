"""When an owed realm re-key runs, and what makes it wait (RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §5. ``agent_runtime.realm_rekey``
owns the operation and trusts its caller for idle; this module is that caller, the only one. A re-key renames
folders a running turn has open and ids a running turn holds in memory, so it runs only when nothing is
running, from three triggers:

* **idle** — :func:`run_owed_rekeys` tries every journal that is ``owed`` or ``running`` whenever the serve's
  last turn ends (``turn_activity``'s idle boundary) and every :data:`TICK_SECONDS` (:func:`start_rekey_ticker`);
* **serve start** — the boot sweeps call it before the socket accepts and before the read model is first
  built, so a restarted serve never shows the old ids;
* **a re-join** — :func:`finish_rekey_or_refuse` runs it first, or refuses the adopt ``realm_busy``.

What makes it wait is one of :class:`RekeyBusy`, read in :func:`busy_fact`. Turns are counted serve-wide (no
run body has a cwd or an open file under a folder about to be renamed — what makes Windows safe); Work runs
and builds only for the workspaces of the map. While it runs it holds ``profile_runner``'s workspace-writer
lock, so no run body starts. A step the OS refuses (a folder another program holds open) leaves the journal
``running`` with the step named and reads as ``rename_blocked``; the next trigger runs it again.

An argv child never re-keys while a serve is live on the same store (``serve``): the serve does it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from . import paths
from .realm_rekey_journal import JOURNAL_DIRNAME, RekeyState, read_rekey_journal

__layer__ = "lanes"
__all__ = [
    "REALM_BUSY_CODE",
    "RETRY_AFTER_MS",
    "TICK_SECONDS",
    "RekeyAttempt",
    "RekeyBusy",
    "RekeyTrigger",
    "busy_fact",
    "finish_rekey_or_refuse",
    "pending_rekeys",
    "run_owed_rekeys",
    "start_rekey_ticker",
    "try_rekey",
]

logger = logging.getLogger(__name__)

#: The ``RealmSyncError.code`` a re-join answers while an owed re-key cannot run. Retryable.
REALM_BUSY_CODE = "realm_busy"
TICK_SECONDS = 20.0


class RekeyBusy(str, Enum):
    """Why an owed re-key is not running now — ``running`` on the ``realm_busy`` refusal."""

    TURN = "turn"
    WORK_RUN = "work_run"
    BUILD = "build"
    RENAME_BLOCKED = "rename_blocked"
    #: Asked of an argv child while a serve is live on this store: the serve runs it.
    SERVE = "serve"


class RekeyTrigger(str, Enum):
    LEAVE = "leave"
    IDLE = "idle"
    SERVE_START = "serve_start"
    REJOIN = "rejoin"


#: How long a client waits before asking again, by what is running.
RETRY_AFTER_MS: dict[RekeyBusy, int] = {
    RekeyBusy.TURN: 5_000, RekeyBusy.WORK_RUN: 30_000, RekeyBusy.BUILD: 30_000,
    RekeyBusy.RENAME_BLOCKED: 15_000, RekeyBusy.SERVE: 5_000,
}
_PENDING = frozenset({RekeyState.OWED.value, RekeyState.RUNNING.value})
#: One re-key attempt at a time in this process: the tick, the idle boundary and a re-join may meet.
_ATTEMPT_GATE = threading.Lock()


@dataclass(frozen=True)
class RekeyAttempt:
    """One try at one realm's re-key. ``busy`` is ``None`` when it ran (or had nothing to run)."""

    realm_id: str
    journal: dict[str, Any] | None
    busy: RekeyBusy | None = None

    @property
    def done(self) -> bool:
        return bool(self.journal) and self.journal.get("state") == RekeyState.DONE.value

    def refusal_details(self) -> dict[str, Any]:
        blocked = (self.journal or {}).get("blocked") or {}
        details = {"realm_id": self.realm_id, "running": self.busy.value, "retry_after_ms": RETRY_AFTER_MS[self.busy]}
        return {**details, "blocked_step": blocked["step"]} if blocked.get("step") else details


def pending_rekeys() -> list[str]:
    """The realms (by their id before the re-key) whose journal is ``owed`` or ``running``, oldest debt first."""
    directory = paths.store_root() / JOURNAL_DIRNAME
    found = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        journal = read_rekey_journal(path.stem)
        if journal and journal.get("state") in _PENDING and isinstance(journal.get("map"), dict):
            found.append((str(journal.get("owed_at") or ""), str(journal["map"].get("realm_old") or path.stem)))
    return [realm_id for _, realm_id in sorted(found)]


def _another_serve_is_live(_workspaces: set[str]) -> bool:
    from .serve_registry import CLASSIFICATION_LIVE, CLASSIFICATION_UNKNOWN, list_serve_instances

    return any(row.get("classification") in (CLASSIFICATION_LIVE, CLASSIFICATION_UNKNOWN) and row.get("pid") != os.getpid()
               for row in list_serve_instances(paths.store_root()))


def _a_turn_is_running(_workspaces: set[str]) -> bool:
    from .profile_runner.workdir import agent_runs_in_flight
    from .turn_activity import chat_turns_accepted, chat_turns_admitted

    return bool(agent_runs_in_flight() or chat_turns_admitted() or chat_turns_accepted())


def _a_work_run_is_open(workspaces: set[str]) -> bool:
    from .work_store.engine import RecordState, records

    open_states = {RecordState.STARTING, RecordState.RUNNING}
    return any(record.workspace_id in workspaces and record.state in open_states for record in records())


def _a_build_is_running(workspaces: set[str]) -> bool:
    from .builds.sweep import build_rows

    return any(row.get("workspace_id") in workspaces and row.get("outcome") is None for row in build_rows(time.time()))


#: The busy facts, in the order they are asked. Each takes the workspace ids of the map (old and new).
BUSY_FACTS: tuple[tuple[RekeyBusy, Callable[[set[str]], bool]], ...] = (
    (RekeyBusy.SERVE, _another_serve_is_live),
    (RekeyBusy.TURN, _a_turn_is_running),
    (RekeyBusy.WORK_RUN, _a_work_run_is_open),
    (RekeyBusy.BUILD, _a_build_is_running),
)


def busy_fact(mapping: dict[str, Any]) -> RekeyBusy | None:
    """What is running that the re-key of ``mapping`` must wait for, or ``None``. A fact that cannot be asked
    (a bundle that ships no Work or no builds) is not busy: the rename itself still refuses a folder in use."""
    workspaces = {*(mapping.get("workspaces") or {}), *(mapping.get("workspaces") or {}).values()}
    for fact, holds in BUSY_FACTS:
        try:
            if holds(workspaces):
                return fact
        except Exception:
            logger.debug("realm re-key: busy fact %s could not be asked", fact.value, exc_info=True)
    return None


def try_rekey(realm_id: str) -> RekeyAttempt:
    """Run, or finish, the owed re-key of ``realm_id`` (its id BEFORE the re-key) if nothing is running.
    A realm that owes none answers at once; a busy one answers why and is left as it was."""
    from .profile_runner.workdir import _WORKDIR_LOCK
    from .realm_rekey import rekey_realm
    from .realm_rekey_agents import RekeyAgentBusy

    with _ATTEMPT_GATE:
        journal = read_rekey_journal(realm_id)
        if journal is None or journal.get("state") not in _PENDING:
            return RekeyAttempt(realm_id, journal)
        if not _WORKDIR_LOCK.acquire(blocking=False):  # a workspace writer (a checkpoint restore, an undo) holds it
            return RekeyAttempt(realm_id, journal, RekeyBusy.TURN)
        try:
            busy = busy_fact(journal["map"])
            if busy is None:
                try:
                    return RekeyAttempt(realm_id, rekey_realm(realm_id))
                except RekeyAgentBusy:
                    busy = RekeyBusy.TURN
                except OSError:
                    busy = RekeyBusy.RENAME_BLOCKED
                    logger.warning("realm re-key of %s: a step was refused by the OS; it is tried again", realm_id, exc_info=True)
            return RekeyAttempt(realm_id, read_rekey_journal(realm_id), busy)
        finally:
            _WORKDIR_LOCK.release()


def run_owed_rekeys(trigger: RekeyTrigger) -> list[RekeyAttempt]:
    """Try every owed or half-done re-key. Never raises: a failed one is logged and waits for the next trigger."""
    attempts = []
    for realm_id in pending_rekeys():
        try:
            attempt = try_rekey(realm_id)
        except Exception:
            logger.warning("realm re-key of %s failed (%s); it is tried again", realm_id, trigger.value, exc_info=True)
            continue
        attempts.append(attempt)
        logger.info("realm_rekey trigger=%s realm=%s state=%s busy=%s", trigger.value, realm_id,
                    (attempt.journal or {}).get("state"), attempt.busy.value if attempt.busy else "-")
    return attempts


def finish_rekey_or_refuse(realm_id: str) -> dict[str, Any] | None:
    """A re-join's first step for one granted realm: finish its owed re-key, or refuse ``realm_busy``
    (retryable; ``realm_id``, ``running``, ``retry_after_ms``). Returns the journal, ``None`` for a realm
    that never owed one."""
    from .realm_sync.models import RealmSyncError

    attempt = try_rekey(realm_id)
    if attempt.busy is not None:
        raise RealmSyncError(
            REALM_BUSY_CODE,
            "This realm's local copy is still taking its own ids; join again once what is running has finished.",
            retryable=True, safe_details=attempt.refusal_details(),
        )
    return attempt.journal


#: The serve's request home, bound around a re-key the serve starts off a request (Lens and the shared skills
#: are read from the head home). ``None`` outside a serve: the process environment already names it.
_SERVE_HOME: list[Any] = [None]


def _run_idle() -> None:
    import contextlib

    from .profile_context import process_home_scope

    home = _SERVE_HOME[0]
    with process_home_scope(home) if home is not None else contextlib.nullcontext():
        run_owed_rekeys(RekeyTrigger.IDLE)


def _on_turn_idle() -> None:
    """The serve's last turn just ended. Off the turn's thread: a re-key is seconds of renames and git."""
    if pending_rekeys():
        threading.Thread(target=_run_idle, name="harness-realm-rekey-idle", daemon=True).start()


def start_rekey_ticker(*, stop_event: threading.Event, interval_s: float = TICK_SECONDS, home: Any = None) -> threading.Thread:
    """The serve's idle trigger: the turn-idle boundary, and a tick every ``interval_s`` until ``stop_event``
    (a Work run or a build ending is no turn boundary). ``home`` is the serve's request home."""
    from .turn_activity import register_turn_idle_listener

    _SERVE_HOME[0] = home
    register_turn_idle_listener(_on_turn_idle)

    def _loop() -> None:
        while not stop_event.wait(interval_s):
            if pending_rekeys():
                _run_idle()

    thread = threading.Thread(target=_loop, name="harness-realm-rekey-tick", daemon=True)
    thread.start()
    return thread
