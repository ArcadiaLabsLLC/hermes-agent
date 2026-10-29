"""The supervision transition table: state × event → the decisions to carry out. No I/O.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §3. Slice W1:
the harness answers beats, re-targets its parent watch to each beat's pid, tells a Quit from a crash
from a hang, and records each. Slice W2 (decisions 4–9): a SUPERVISED (``supervise: true``) launcher
that crashes, or hangs 45 awake seconds while ``running``, is relaunched from its last beat — a hang
first kills that one pid — after a 2 s / 10 s / 30 s backoff, at most :data:`RESTART_LIMIT` times per
rolling :data:`RESTART_WINDOW_SECONDS`; the next one drains ``launcher_restart_limit`` instead. A
relaunch no beat answers within :data:`RELAUNCH_BEAT_SECONDS` awake seconds counts as failed and
spends the budget again. ``quitting``, ``closing_for_game``, ``supervise: false`` and a ``suspended``
launcher handed a ``game`` keep W1's rows: a runtime started with ``--parent-pid`` (``bound``) drains,
any other records. Slice G1 (decisions 6 and 13–15): while a handed-over game is WATCHED
(:func:`on_game_watch`), a supervised launcher that closes for it, or crashes while ``suspended``
over it, does not drain the runtime; the relaunch waits for the game to end (:func:`on_game_ended`) —
``game_ended`` unbudgeted for a close, ``crashed`` through the budget for a crash. A launcher that
beats again before then is alive, and the game's end only records. A runtime no launcher ever beat
to behaves as it did before this module existed.

Every function returns ``(new_state, decisions)``; the wiring (:mod:`.watchdog`) carries each
decision out and logs one receipt line per decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .contract import LauncherBeat, LauncherState

__layer__ = "policy"

__all__ = [
    "BACKOFF_SECONDS",
    "END_LAUNCHER_QUIT",
    "END_LAUNCHER_RESTART_LIMIT",
    "END_PARENT_EXITED",
    "HANG_SECONDS",
    "RELAUNCH_BEAT_SECONDS",
    "RESTART_LIMIT",
    "RESTART_WINDOW_SECONDS",
    "RelaunchReason",
    "QUIT_GRACE_SECONDS",
    "SLEEP_GAP_TICKS",
    "TICK_SECONDS",
    "Decision",
    "Record",
    "SupervisionState",
    "on_beat",
    "on_connection_dropped",
    "on_game_ended",
    "on_game_watch",
    "on_pid_gone",
    "on_resume_game_watch",
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
END_LAUNCHER_RESTART_LIMIT = "launcher_restart_limit"

#: Decision 7: crash/hang relaunches per rolling window, then the fail-safe drain.
RESTART_LIMIT = 3
RESTART_WINDOW_SECONDS = 600.0
#: Decision 7: the wait before the 1st, 2nd and 3rd relaunch of a window.
BACKOFF_SECONDS: tuple[float, ...] = (2.0, 10.0, 30.0)
#: Decision 7: a relaunched launcher that has not beat this many awake seconds after its spawn failed.
RELAUNCH_BEAT_SECONDS = 60.0


class RelaunchReason(StrEnum):
    """The ``--harness-relaunch=<reason>`` word (§2). ``game_ended`` is G1's and is never budgeted."""

    CRASHED = "crashed"
    HUNG = "hung"
    GAME_ENDED = "game_ended"


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
    RELAUNCH_FAILED = "relaunch_failed"
    RESTART_LIMIT = "restart_limit"
    GAME_ENDED = "game_ended"


@dataclass(frozen=True, slots=True)
class Decision:
    record: Record
    #: Drain this runtime, ending with this word. ``None``: keep serving.
    drain: str | None = None
    #: Latch this end-reason word now (first wins), without draining.
    note_end: str | None = None
    #: Disarm the parent watch and arm one on this pid.
    retarget_pid: int | None = None
    #: Terminate this one pid (never its tree) before anything else (decision 5).
    kill_pid: int | None = None
    #: Spawn the last beat's ``executable`` with ``--harness-relaunch=<this>`` after ``delay`` seconds.
    relaunch: RelaunchReason | None = None
    delay: float = 0.0


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
    #: Wall-clock times of the budgeted relaunches still inside the window (persisted by the watchdog).
    relaunches: tuple[float, ...] = ()
    #: Awake seconds since a relaunch's spawn that no beat has answered yet (``None``: none owed).
    relaunch_awaiting: float | None = None
    #: At least one handed-over game is being watched (G1).
    game_watched: bool = False
    #: The launcher went while a game was watched: the relaunch its game's end owes (``None``: none).
    relaunch_on_game_end: RelaunchReason | None = None


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
#: The launcher states whose pid exiting is a relaunched crash, given ``supervise`` (decisions 4 and 6).
_RELAUNCHED_ON_CRASH = frozenset({LauncherState.RUNNING, LauncherState.SUSPENDED})


def _relaunched(beat: LauncherBeat | None) -> bool:
    """Does this last beat's pid exiting relaunch? Supervised, running or suspended with no game."""
    return (beat is not None and beat.supervise and beat.state in _RELAUNCHED_ON_CRASH
            and not (beat.state is LauncherState.SUSPENDED and beat.game is not None))


def _budgeted(state: SupervisionState, record: Record, reason: RelaunchReason, now: float,
              kill_pid: int | None = None) -> tuple[SupervisionState, list[Decision]]:
    """Spend one relaunch of the rolling budget, or drain ``launcher_restart_limit`` when it is spent."""
    recent = tuple(at for at in state.relaunches if now - at < RESTART_WINDOW_SECONDS)
    if len(recent) >= RESTART_LIMIT:
        return (replace(state, relaunches=recent, relaunch_awaiting=None),
                [Decision(record, kill_pid=kill_pid),
                 Decision(Record.RESTART_LIMIT, drain=END_LAUNCHER_RESTART_LIMIT)])
    delay = BACKOFF_SECONDS[len(recent)]
    return (replace(state, relaunches=(*recent, now), relaunch_awaiting=-delay),
            [Decision(record, kill_pid=kill_pid, relaunch=reason, delay=delay)])


def _owed_on_game_end(state: SupervisionState, beat: LauncherBeat | None) -> RelaunchReason | None:
    """A supervised launcher leaving over a WATCHED game: the relaunch the game's end owes, else ``None``."""
    if not state.game_watched or beat is None or not beat.supervise:
        return None
    if beat.state is LauncherState.CLOSING_FOR_GAME:
        return RelaunchReason.GAME_ENDED
    if beat.state is LauncherState.SUSPENDED and beat.game is not None:
        return RelaunchReason.CRASHED
    return None


def on_game_watch(state: SupervisionState, watched: bool) -> tuple[SupervisionState, list[Decision]]:
    """The game watch started (a beat's ``game`` resolved) or its last game ended."""
    return replace(state, game_watched=watched), []


def on_resume_game_watch(state: SupervisionState, beat: LauncherBeat) -> tuple[SupervisionState, list[Decision]]:
    """Boot found a still-running watched game (decision 15). With no launcher watched, the game's end
    relaunches the launcher the watch was handed by (``beat``, rebuilt from the game's record)."""
    if state.watched_pid is not None or state.last_beat is not None:
        return replace(state, game_watched=True), []
    owed = RelaunchReason.GAME_ENDED if beat.supervise else None
    return replace(state, game_watched=True, last_beat=beat, relaunch_on_game_end=owed), []


def on_game_ended(state: SupervisionState, *, now: float = 0.0,
                  still_watched: bool = False) -> tuple[SupervisionState, list[Decision]]:
    """A watched game ended at wall-clock ``now``. A launcher still alive (``suspended``) only records;
    one that closed for the game is relaunched ``game_ended`` (never budgeted), one that crashed over it
    ``crashed`` through the budget."""
    owed = state.relaunch_on_game_end
    state = replace(state, game_watched=still_watched,
                    relaunch_on_game_end=owed if still_watched else None)
    if owed is None or state.watched_pid is not None or still_watched:
        return state, [Decision(Record.GAME_ENDED)]
    if owed is RelaunchReason.CRASHED:
        return _budgeted(state, Record.GAME_ENDED, RelaunchReason.CRASHED, now)
    return state, [Decision(Record.GAME_ENDED, relaunch=RelaunchReason.GAME_ENDED)]


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
                   hang_recorded=False, quitting_awake=quitting_awake, relaunch_awaiting=None,
                   relaunch_on_game_end=None), decisions


def on_pid_gone(state: SupervisionState, pid: int, *, now: float = 0.0) -> tuple[SupervisionState, list[Decision]]:
    """The watched pid exited at wall-clock ``now``. A stale watch's pid (already re-targeted away
    from, or killed for a hang) decides nothing."""

    if pid != state.watched_pid:
        return state, []
    beat = state.last_beat
    owed = _owed_on_game_end(state, beat)
    if owed is not None:
        record = Record.CLOSED_FOR_GAME if owed is RelaunchReason.GAME_ENDED else Record.CRASHED
        return replace(state, watched_pid=None, relaunch_on_game_end=owed), [Decision(record)]
    if _relaunched(beat):
        return _budgeted(replace(state, watched_pid=None), Record.CRASHED, RelaunchReason.CRASHED, now)
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
    awaiting = None if state.relaunch_awaiting is None else state.relaunch_awaiting + awake
    state = replace(state, last_tick_wall=wall, awake_since_beat=state.awake_since_beat + awake,
                    quitting_awake=state.quitting_awake + awake, relaunch_awaiting=awaiting)
    beat = state.last_beat
    if beat is None:
        return state, []
    if awaiting is not None and awaiting >= RELAUNCH_BEAT_SECONDS:
        return _budgeted(state, Record.RELAUNCH_FAILED, RelaunchReason.CRASHED, wall)
    if (beat.state is LauncherState.RUNNING and not state.hang_recorded and state.watched_pid is not None
            and state.awake_since_beat >= HANG_SECONDS):
        if beat.supervise:
            # Kill the hung pid and stop watching it, so its exit is not ALSO read as a crash.
            hung = replace(state, hang_recorded=True, watched_pid=None)
            return _budgeted(hung, Record.HUNG, RelaunchReason.HUNG, wall, kill_pid=state.watched_pid)
        return replace(state, hang_recorded=True), [Decision(Record.HUNG)]
    if (beat.state is LauncherState.QUITTING and state.bound and not state.quit_grace_spent
            and state.quitting_awake >= QUIT_GRACE_SECONDS):
        return replace(state, quit_grace_spent=True), [Decision(Record.QUIT, drain=END_LAUNCHER_QUIT)]
    return state, []
