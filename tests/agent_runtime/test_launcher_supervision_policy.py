"""The launcher-supervision transition table (plan ``launcher-mutual-supervision-2026-10-27`` §5, W1).

Pure: every case drives ``agent_runtime.launcher_supervision.policy`` with explicit beats, pids and
wall-clock ticks. The serve-level cases (the real watch, the op, the end reason on disk) are in
``tests/agent_runtime/test_launcher_supervision_ops.py``.
"""

from __future__ import annotations

import pytest

from agent_runtime.launcher_supervision import LauncherBeat, LauncherState, parse_beat
from agent_runtime.launcher_supervision import policy
from agent_runtime.launcher_supervision.contract import BeatRefused
from agent_runtime.launcher_supervision.policy import Record, SupervisionState


def _beat(state: LauncherState = LauncherState.RUNNING, *, pid: int = 100, supervise: bool = True,
          seq: int = 1) -> LauncherBeat:
    return LauncherBeat(seq=seq, pid=pid, state=state, window_visible=True, executable="/opt/launcher",
                        build={"commit": "abc"}, supervise=supervise)


def _beaten(state: LauncherState = LauncherState.RUNNING, *, bound: bool = True,
            supervise: bool = True) -> SupervisionState:
    start = SupervisionState(bound=bound, watched_pid=100)
    return policy.on_beat(start, _beat(state, supervise=supervise))[0]


@pytest.mark.parametrize(
    ("state", "bound", "supervise", "record", "drain"),
    [
        (LauncherState.QUITTING, True, True, Record.QUIT, policy.END_LAUNCHER_QUIT),
        (LauncherState.RUNNING, True, True, Record.CRASHED, policy.END_PARENT_EXITED),
        (LauncherState.SUSPENDED, True, True, Record.CRASHED, policy.END_PARENT_EXITED),
        (LauncherState.CLOSING_FOR_GAME, True, True, Record.CLOSED_FOR_GAME, policy.END_PARENT_EXITED),
        (LauncherState.RUNNING, True, False, Record.EXITED_UNSUPERVISED, policy.END_PARENT_EXITED),
        # A runtime nobody started with --parent-pid (a service) records and keeps serving.
        (LauncherState.RUNNING, False, True, Record.CRASHED, None),
        (LauncherState.QUITTING, False, True, Record.QUIT, None),
    ],
)
def test_a_gone_pid_is_told_apart_by_the_last_beat(state, bound, supervise, record, drain):
    _, decisions = policy.on_pid_gone(_beaten(state, bound=bound, supervise=supervise), 100)
    assert [(d.record, d.drain) for d in decisions] == [(record, drain)]


def test_a_gone_pid_with_no_beat_ever_drains_exactly_as_before():
    _, decisions = policy.on_pid_gone(SupervisionState(bound=True, watched_pid=100), 100)
    assert [(d.record, d.drain) for d in decisions] == [(Record.UNBEATEN_PARENT_EXITED, "parent_exited")]


def test_the_drain_words_are_the_serve_end_reasons():
    from hermes_cli.harness_parts.serve.end_reason import EndReason

    assert policy.END_PARENT_EXITED == EndReason.PARENT_EXITED
    assert policy.END_LAUNCHER_QUIT == EndReason.LAUNCHER_QUIT


def test_a_beat_with_a_new_pid_retargets_and_the_old_pid_then_decides_nothing():
    state = SupervisionState(bound=True, watched_pid=100)
    state, decisions = policy.on_beat(state, _beat(pid=200))
    assert [(d.record, d.retarget_pid) for d in decisions] == [(Record.RETARGETED, 200)]
    assert state.watched_pid == 200
    # Positive control below: the same call with the CURRENT pid does decide.
    assert policy.on_pid_gone(state, 100)[1] == []
    assert policy.on_pid_gone(state, 200)[1][0].record is Record.CRASHED
    # The same pid again is not a re-target.
    assert policy.on_beat(state, _beat(pid=200, seq=2))[1] == []


def test_the_first_quitting_beat_latches_launcher_quit_only_on_a_bound_runtime():
    bound = SupervisionState(bound=True, watched_pid=100)
    _, decisions = policy.on_beat(bound, _beat(LauncherState.QUITTING))
    assert [(d.record, d.note_end, d.drain) for d in decisions] == [(Record.QUITTING, "launcher_quit", None)]
    service = SupervisionState(bound=False, watched_pid=100)
    assert [d.note_end for d in policy.on_beat(service, _beat(LauncherState.QUITTING))[1]] == [None]
    # A second quitting beat latches nothing new.
    again = policy.on_beat(policy.on_beat(bound, _beat(LauncherState.QUITTING))[0],
                           _beat(LauncherState.QUITTING, seq=2))[1]
    assert again == []


def _tick(state: SupervisionState, seconds: float, *, start: float = 1000.0, step: float = 1.0,
          gap_at: float | None = None, gap: float = 0.0) -> tuple[SupervisionState, list]:
    """Tick every ``step`` wall seconds for ``seconds`` awake seconds, one sleep gap optional."""

    decisions: list = []
    state, _ = policy.on_tick(state, start)
    wall, awake = start, 0.0
    while awake < seconds:
        wall += step
        awake += step
        if gap_at is not None and abs(awake - gap_at) < 1e-9:
            wall += gap
        state, made = policy.on_tick(state, wall)
        decisions.extend(made)
    return state, decisions


def test_forty_five_awake_seconds_without_a_beat_is_a_hang_recorded_once():
    state, decisions = _tick(_beaten(), 45.0)
    assert [d.record for d in decisions] == [Record.HUNG]
    assert all(d.drain is None for d in decisions), "W1 records a hang; it never drains or kills"
    assert _tick(state, 20.0, start=2000.0)[1] == []


def test_forty_four_awake_seconds_is_not_a_hang():
    assert _tick(_beaten(), 44.0)[1] == []


def test_a_sleep_gap_inside_forty_five_wall_seconds_is_not_awake_time():
    # 15 ticked seconds, then the machine sleeps 30 s, then 15 more: 60 s of wall, 30 awake.
    assert _tick(_beaten(), 30.0, gap_at=15.0, gap=30.0)[1] == []


def test_suspended_turns_hang_detection_off():
    assert _tick(_beaten(LauncherState.SUSPENDED), 120.0)[1] == []


def test_a_beat_resets_the_hang_clock():
    state, _ = _tick(_beaten(), 40.0)
    state, _ = policy.on_beat(state, _beat(seq=2))
    assert _tick(state, 40.0, start=3000.0)[1] == []


def test_a_dropped_connection_with_the_pid_alive_is_not_a_crash():
    state = _beaten()
    state, decisions = policy.on_connection_dropped(state)
    assert [(d.record, d.drain) for d in decisions] == [(Record.CONNECTION_DROPPED, None)]
    # A reconnect that beats 10 s later clears the clock: nothing at 44 more seconds.
    state, _ = _tick(state, 10.0)
    state, _ = policy.on_beat(state, _beat(seq=2))
    assert _tick(state, 44.0, start=5000.0)[1] == []


def test_a_quitting_launcher_alive_thirty_awake_seconds_later_is_drained_not_waited_on():
    state, decisions = _tick(_beaten(LauncherState.QUITTING), 30.0)
    assert [(d.record, d.drain) for d in decisions] == [(Record.QUIT, "launcher_quit")]
    assert _tick(_beaten(LauncherState.QUITTING), 29.0)[1] == []
    assert _tick(_beaten(LauncherState.QUITTING, bound=False), 60.0)[1] == []


def test_later_quitting_beats_do_not_restart_the_quit_grace():
    state, _ = _tick(_beaten(LauncherState.QUITTING), 20.0)
    state, _ = policy.on_beat(state, _beat(LauncherState.QUITTING, seq=2))
    assert [d.record for d in _tick(state, 10.0, start=4000.0)[1]] == [Record.QUIT]


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"seq": True}, "seq"),
        ({"pid": 0}, "pid"),
        ({"state": "napping"}, "state"),
        ({"supervise": "yes"}, "supervise"),
        ({"window_visible": None}, "window_visible"),
        ({"executable": " "}, "executable"),
        ({"game": {"pid": 1}}, "game"),  # a game rides closing_for_game / suspended only
    ],
)
def test_an_unreadable_beat_is_refused_naming_its_field(patch, field):
    good = {"seq": 1, "pid": 42, "state": "running", "window_visible": False, "executable": "/opt/l",
            "build": "b", "supervise": True}
    assert isinstance(parse_beat(good), LauncherBeat)  # positive control
    refused = parse_beat({**good, **patch})
    assert isinstance(refused, BeatRefused) and refused.field == field
