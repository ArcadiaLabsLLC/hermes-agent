"""Slice G1 of launcher supervision: the game watch (row RT-GAME-PROCESS-WATCH).

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §3 decisions 6 and
13–15 and §5's G1 cases. The pure rows drive ``policy`` and ``game_watch.on_poll``; the wiring cases
drive ``LauncherWatchdog`` / ``GameWatcher`` with a scripted probe; the bootstrapper case runs real
processes. Autouse conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading

import pytest

from agent_runtime import paths
from agent_runtime.launcher_supervision import LauncherBeat, LauncherState, LauncherWatchdog, policy
from agent_runtime.launcher_supervision import game_watch
from agent_runtime.launcher_supervision.game_watch import GameRecord, GameWatcher, Outcome, ProcessProbe
from agent_runtime.launcher_supervision.policy import RelaunchReason, Record, SupervisionState

_GAME = {"session_id": "play_1", "canonical_game_id": "game_x", "mapping_id": "map_1", "title": "X",
         "pid": 4321, "executable": "/games/x/x.bin", "install_dir": "/games/x", "started_at": "2026-10-29T10:00:00Z"}


def _beat(state: LauncherState = LauncherState.RUNNING, *, pid: int = 100, supervise: bool = True, seq: int = 1,
          game: dict | None = None) -> LauncherBeat:
    return LauncherBeat(seq=seq, pid=pid, state=state, window_visible=True, executable="/opt/launcher",
                        build=None, supervise=supervise, game=game)


def _watched(state: LauncherState, *, game: dict | None = _GAME) -> SupervisionState:
    start = policy.on_game_watch(SupervisionState(bound=True, watched_pid=100), True)[0]
    return policy.on_beat(start, _beat(state, game=game))[0]


# ── the table ────────────────────────────────────────────────────────────────


def test_a_launcher_closed_for_a_watched_game_is_relaunched_when_it_ends_and_not_budgeted():
    state, decisions = policy.on_pid_gone(_watched(LauncherState.CLOSING_FOR_GAME), 100, now=1000.0)
    assert [(d.record, d.drain, d.relaunch) for d in decisions] == [(Record.CLOSED_FOR_GAME, None, None)]

    state, decisions = policy.on_game_ended(state, now=1500.0)
    assert [(d.record, d.relaunch, d.delay) for d in decisions] == [
        (Record.GAME_ENDED, RelaunchReason.GAME_ENDED, 0.0)]
    assert state.relaunches == ()


def test_with_no_watched_game_a_close_still_drains_a_bound_runtime():
    """Positive control for the row above: the watch, not the state word, is what keeps the runtime."""
    state = policy.on_beat(SupervisionState(bound=True, watched_pid=100), _beat(LauncherState.CLOSING_FOR_GAME,
                                                                               game=_GAME))[0]
    _, decisions = policy.on_pid_gone(state, 100)
    assert [(d.record, d.drain) for d in decisions] == [(Record.CLOSED_FOR_GAME, policy.END_PARENT_EXITED)]


def test_a_game_ending_under_a_live_launcher_only_records():
    _, decisions = policy.on_game_ended(_watched(LauncherState.SUSPENDED), now=1500.0)
    assert [(d.record, d.relaunch, d.drain) for d in decisions] == [(Record.GAME_ENDED, None, None)]


def test_a_crash_while_suspended_over_a_game_waits_for_the_game_then_spends_the_budget():
    state, decisions = policy.on_pid_gone(_watched(LauncherState.SUSPENDED), 100, now=1000.0)
    assert [(d.record, d.relaunch) for d in decisions] == [(Record.CRASHED, None)]

    state, decisions = policy.on_game_ended(state, now=1500.0)
    assert [(d.record, d.relaunch, d.delay) for d in decisions] == [
        (Record.GAME_ENDED, RelaunchReason.CRASHED, policy.BACKOFF_SECONDS[0])]
    assert state.relaunches == (1500.0,)


def test_a_launcher_that_beats_again_before_the_game_ends_is_not_relaunched():
    state, _ = policy.on_pid_gone(_watched(LauncherState.CLOSING_FOR_GAME), 100, now=1000.0)
    state, _ = policy.on_beat(state, _beat(pid=200, seq=9))
    _, decisions = policy.on_game_ended(state, now=1500.0)
    assert [d.relaunch for d in decisions] == [None]


# ── the end verdict ──────────────────────────────────────────────────────────


def _record(**fields) -> GameRecord:
    base = game_watch.parse_game(_GAME, now=1000.0, pid_create_time=None, launcher=None)
    assert base is not None
    return GameRecord(**{**{name: getattr(base, name) for name in GameRecord.__slots__}, **fields})


def test_nothing_found_inside_the_start_grace_is_not_an_end():
    record = _record()
    for now in (1010.0, 1030.0, 1059.0):
        record, _ = game_watch.on_poll(record, False, now)
    assert record.active and record.misses == 0


def test_two_consecutive_misses_end_the_game_and_one_does_not():
    record, _ = game_watch.on_poll(_record(), False, 1065.0)
    assert record.active and record.misses == 1
    record, _ = game_watch.on_poll(record, True, 1070.0)  # seen again: the count resets
    record, _ = game_watch.on_poll(record, False, 1075.0)
    assert record.active
    record, write = game_watch.on_poll(record, False, 1080.0)
    assert (record.outcome, record.ended_epoch, write) == (Outcome.EXITED, 1080.0, True)


def test_last_seen_is_refreshed_every_sixty_seconds_while_it_runs():
    record, write = game_watch.on_poll(_record(), True, 1030.0)
    assert (record.last_seen_epoch, write) == (1000.0, False)
    record, write = game_watch.on_poll(record, True, 1061.0)
    assert (record.last_seen_epoch, write) == (1061.0, True)


# ── restart mid-game ─────────────────────────────────────────────────────────


class _Probe(ProcessProbe):
    def __init__(self, running: bool) -> None:
        self.is_running = running

    def create_time(self, pid):
        return 5.0

    def running(self, record):
        return self.is_running


def _on_disk(record: GameRecord) -> None:
    path = paths.launcher_supervision_games_dir() / f"{record.session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_json()), encoding="utf-8")


def _stored(session_id: str = "play_1") -> dict:
    return json.loads((paths.launcher_supervision_games_dir() / f"{session_id}.json").read_text(encoding="utf-8"))


def test_a_booting_harness_closes_a_gone_game_as_lost_with_no_end_time():
    _on_disk(_record(last_seen_epoch=1060.0))
    watcher = GameWatcher(on_ended=lambda record, still: None, probe=_Probe(False), clock=lambda: 9000.0)

    assert watcher.resume() == []
    stored = _stored()
    assert (stored["outcome"], stored["ended_at"], stored["last_seen_epoch"]) == (Outcome.LOST, None, 1060.0)


def test_a_booting_harness_keeps_watching_a_game_still_running():
    _on_disk(_record())
    watcher = GameWatcher(on_ended=lambda record, still: None, probe=_Probe(True), poll_seconds=3600.0)
    try:
        assert [record.session_id for record in watcher.resume()] == ["play_1"]
        assert watcher.watching
        assert _stored()["outcome"] == Outcome.STILL_RUNNING
    finally:
        watcher.stop()


# ── the wiring ───────────────────────────────────────────────────────────────


class _Relauncher:
    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.spawn_done = threading.Event()

    def same_executable(self, pid, executable):
        return True

    def kill(self, pid, create_time):
        return True

    def spawn(self, argv):
        self.spawned.append(list(argv))
        self.spawn_done.set()
        return 4242


class _Effects:
    def __init__(self) -> None:
        self.drained: list[str] = []

    def note_end(self, word):
        pass

    def drain(self, word, pid):
        self.drained.append(word)

    def may_relaunch(self):
        return True


def _watchdog(*, service: bool, probe: _Probe, relauncher: _Relauncher, effects: _Effects,
              clock=lambda: 1000.0) -> LauncherWatchdog:
    holder: dict = {}
    watcher = GameWatcher(on_ended=lambda record, still: holder["dog"]._game_ended(record, still), probe=probe,
                          clock=clock, poll_seconds=3600.0)
    dog = LauncherWatchdog(parent_pid=100, effects=effects, tick_seconds=3600.0, clock=clock, relauncher=relauncher,
                           service=service, game_watcher=watcher, poll_seconds=3600.0)
    holder["dog"] = dog
    return dog


@pytest.mark.parametrize(("service", "watching"), [(False, False), (True, True)])
def test_watching_needs_a_service_runtime(service, watching):
    dog = _watchdog(service=service, probe=_Probe(True), relauncher=_Relauncher(), effects=_Effects())
    try:
        assert dog.beat(_beat(LauncherState.CLOSING_FOR_GAME, pid=os.getpid(), game=_GAME)) is watching
    finally:
        dog.stop()


def test_a_game_none_of_whose_locators_resolve_is_not_watched():
    dog = _watchdog(service=True, probe=_Probe(False), relauncher=_Relauncher(), effects=_Effects())
    try:
        assert dog.beat(_beat(LauncherState.CLOSING_FOR_GAME, pid=os.getpid(), game=_GAME)) is False
        assert not (paths.launcher_supervision_games_dir() / "play_1.json").exists()
    finally:
        dog.stop()


def test_the_launcher_closed_for_a_game_is_relaunched_game_ended_when_the_game_ends():
    now = {"t": 1000.0}
    probe, relauncher, effects = _Probe(True), _Relauncher(), _Effects()
    dog = _watchdog(service=True, probe=probe, relauncher=relauncher, effects=effects, clock=lambda: now["t"])
    try:
        assert dog.beat(_beat(LauncherState.CLOSING_FOR_GAME, pid=os.getpid(), game=_GAME)) is True
        dog._pid_gone(os.getpid())
        assert effects.drained == [], "a launcher closed for a watched game does not end the runtime"
        probe.is_running = False
        for now["t"] in (1065.0, 1070.0):
            dog._games.poll_once()
        assert relauncher.spawn_done.wait(2.0)
        assert relauncher.spawned == [["/opt/launcher", "--harness-relaunch=game_ended"]]
        assert _stored()["outcome"] == Outcome.EXITED
    finally:
        dog.stop()


# ── real processes ───────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="copies a POSIX binary into the install folder")
def test_a_bootstrapper_that_exits_at_once_while_its_game_runs_is_still_watched(tmp_path):
    install_dir = tmp_path / "Game"
    install_dir.mkdir()
    game_binary = install_dir / "game_bin"
    shutil.copy(shutil.which("sleep"), game_binary)
    game = subprocess.Popen([str(game_binary), "60"])
    bootstrapper = subprocess.Popen([sys.executable, "-c", "pass"])
    bootstrapper.wait(10)
    watcher = GameWatcher(on_ended=lambda record, still: None, poll_seconds=3600.0)
    try:
        handed = {**_GAME, "pid": bootstrapper.pid, "executable": None, "install_dir": str(install_dir)}
        assert watcher.handed(handed, launcher=None) is True
        record = game_watch.load_records()[0]
        assert ProcessProbe().running(record) is True
        game.kill()
        game.wait(10)
        assert ProcessProbe().running(record) is False  # positive control: the folder is what matched
    finally:
        watcher.stop()
        if game.poll() is None:
            game.kill()
