"""The supervision transition table: state × event → the decisions to carry out. No I/O.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §3, slice W1:
the harness answers beats, re-targets its parent watch to each beat's pid, tells a Quit from a crash
from a hang, and RECORDS each. W1 relaunches nothing and kills nothing; a runtime started with
``--parent-pid`` (``bound``) still drains when its launcher's pid is gone, exactly as before, only
now under the end reason the table names. A runtime no launcher ever beat to behaves as it did
before this module existed.

Every function returns ``(new_state, decisions)``; the wiring (:mod:`.watchdog`) carries each
decision out and logs one receipt line per decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .contract import LauncherBeat, LauncherState

__layer__ = "policy"

__all__ = [
    "END_LAUNCHER_QUIT",
    "END_PARENT_EXITED",
    "HANG_SECONDS",
    "QUIT_GRACE_SECONDS",
    "SLEEP_GAP_TICKS",
    "TICK_SECONDS",
    "Decision",
    "Record",
    "SupervisionState",
    "on_beat",
    "on_connection_dropped",
    "on_pid_gone",
    "on_tick",
]

#: The beat clock's tick, and the launcher's beat cadence (§2: every 5 s) is five of them.
TICK_SECONDS = 1.0
#: §2: hung = no beat for 45 s of time the harness was awake.
HANG_SECONDS = 45.0
#: Decision 5: a tick whose wall-clock gap exceeds this many tick lengths means the machine slept.
SLEEP_GAP_TICKS = 3
#: Decision 4: a ``quitting`` launcher still alive this long later is not waited on further.
QUIT_GRACE_SECONDS = 30.0

#: The end-reason words this table drains with (``hermes_cli.harness_parts.serve.end_reason.EndReason``
#: spells the same words; a test pins them equal, since this layer may not import the serve).
END_PARENT_EXITED = "parent_exited"
END_LAUNCHER_QUIT = "launcher_quit"


class Record(StrEnum):
    """What one decision records: the ``launcher_supervision`` receipt's ``event`` word."""

    RETARGETED = "retargeted"
    QUITTING = "quitting"
    QUIT = "quit"
    CRASHED = "crashed"
    EXITED_UNSUPERVISED = "exited_unsupervised"
    CLOSED_FOR_GAME = "closed_for_game"
    UNBEATEN_PARENT_EXITED = "unbeaten_parent_exited"
    HUNG = "hung"
    CONNECTION_DROPPED = "connection_dropped"


@dataclass(frozen=True, slots=True)
class Decision:
    record: Record
    #: Drain this runtime, ending with this word. ``None``: keep serving.
    drain: str | None = None
    #: Latch this end-reason word now (first wins), without draining.
    note_end: str | None = None
    #: Disarm the parent watch and arm one on this pid.
    retarget_pid: int | None = None


@dataclass(frozen=True, slots=True)
class SupervisionState:
    #: Started with ``--parent-pid``: the launcher's exit ends this runtime (the bundled lifetime).
    bound: bool
    watched_pid: int | None
    last_beat: LauncherBeat | None = None
    #: Awake seconds since the last beat (decision 5's clock).
    awake_since_beat: float = 0.0
    last_tick_wall: float | None = None
    hang_recorded: bool = False
    #: Awake seconds since the FIRST ``quitting`` beat; later ``quitting`` beats do not reset it.
    quitting_awake: float = 0.0
    quit_grace_spent: bool = False


#: Pid gone → what it was, keyed by the last beat's state (``None``: no beat ever arrived).
_PID_GONE_RECORD: dict[LauncherState | None, Record] = {
    None: Record.UNBEATEN_PARENT_EXITED,
    LauncherState.RUNNING: Record.CRASHED,
    LauncherState.SUSPENDED: Record.CRASHED,
    LauncherState.CLOSING_FOR_GAME: Record.CLOSED_FOR_GAME,
    LauncherState.QUITTING: Record.QUIT,
}
#: A crash under ``supervise: false`` (a debug build) is recorded as an unsupervised exit.
_UNSUPERVISED: dict[Record, Record] = {Record.CRASHED: Record.EXITED_UNSUPERVISED}
#: The word a bound runtime drains with, per record; every other pid-gone record drains ``parent_exited``.
_DRAIN_WORD: dict[Record, str] = {Record.QUIT: END_LAUNCHER_QUIT}


def on_beat(state: SupervisionState, beat: LauncherBeat) -> tuple[SupervisionState, list[Decision]]:
    """A beat: re-target to its pid, latch ``launcher_quit`` on the first ``quitting``, reset the clocks."""

    decisions: list[Decision] = []
    if beat.pid != state.watched_pid:
        decisions.append(Decision(Record.RETARGETED, retarget_pid=beat.pid))
    was_quitting = state.last_beat is not None and state.last_beat.state is LauncherState.QUITTING
    if beat.state is LauncherState.QUITTING and not was_quitting:
        decisions.append(Decision(Record.QUITTING, note_end=END_LAUNCHER_QUIT if state.bound else None))
    quitting_awake = state.quitting_awake if was_quitting else 0.0
    return replace(state, watched_pid=beat.pid, last_beat=beat, awake_since_beat=0.0,
                   hang_recorded=False, quitting_awake=quitting_awake), decisions


def on_pid_gone(state: SupervisionState, pid: int) -> tuple[SupervisionState, list[Decision]]:
    """The watched pid exited. A stale watch's pid (already re-targeted away from) decides nothing."""

    if pid != state.watched_pid:
        return state, []
    beat = state.last_beat
    record = _PID_GONE_RECORD[None if beat is None else beat.state]
    if beat is not None and not beat.supervise:
        record = _UNSUPERVISED.get(record, record)
    drain = _DRAIN_WORD.get(record, END_PARENT_EXITED) if state.bound else None
    return replace(state, watched_pid=None), [Decision(record, drain=drain)]


def on_connection_dropped(state: SupervisionState) -> tuple[SupervisionState, list[Decision]]:
    """The beating connection closed with the pid still alive: not a crash (§2 clarification 2).

    The hang clock already runs from the last beat, so a reconnect that beats inside 45 s
    clears it and one that never comes is a hang — the drop itself decides nothing.
    """

    if state.last_beat is None:
        return state, []
    return state, [Decision(Record.CONNECTION_DROPPED)]


def on_tick(state: SupervisionState, wall: float) -> tuple[SupervisionState, list[Decision]]:
    """One beat-clock tick at wall-clock ``wall``: advance the awake clock, then judge hang and quit grace."""

    if state.last_tick_wall is None:
        return replace(state, last_tick_wall=wall), []
    gap = wall - state.last_tick_wall
    awake = 0.0 if gap < 0 or gap > SLEEP_GAP_TICKS * TICK_SECONDS else gap
    state = replace(state, last_tick_wall=wall, awake_since_beat=state.awake_since_beat + awake,
                    quitting_awake=state.quitting_awake + awake)
    beat = state.last_beat
    if beat is None:
        return state, []
    if (beat.state is LauncherState.RUNNING and not state.hang_recorded
            and state.awake_since_beat >= HANG_SECONDS):
        return replace(state, hang_recorded=True), [Decision(Record.HUNG)]
    if (beat.state is LauncherState.QUITTING and state.bound and not state.quit_grace_spent
            and state.quitting_awake >= QUIT_GRACE_SECONDS):
        return replace(state, quit_grace_spent=True), [Decision(Record.QUIT, drain=END_LAUNCHER_QUIT)]
    return state, []
