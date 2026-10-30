"""Slice W2 of launcher supervision: relaunch, the hang kill, the restart budget (row RT-LAUNCHER-RELAUNCH).

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §3 decisions 4–10
and §5's W2 cases. The pure rows drive ``policy``; the wiring cases drive ``LauncherWatchdog`` with a
recording relauncher; the identity, tree-safety and spawn cases touch real processes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from agent_runtime import paths
from agent_runtime.launcher_supervision import LauncherBeat, LauncherState, LauncherWatchdog, policy, relaunch
from agent_runtime.launcher_supervision.policy import RelaunchReason, Record, SupervisionState


def _beat(state: LauncherState = LauncherState.RUNNING, *, pid: int = 100, supervise: bool = True, seq: int = 1,
          window_visible: bool = True, game: dict | None = None, executable: str = "/opt/launcher") -> LauncherBeat:
    return LauncherBeat(seq=seq, pid=pid, state=state, window_visible=window_visible, executable=executable,
                        build={"commit": "abc"}, supervise=supervise, game=game)


def _beaten(state: LauncherState = LauncherState.RUNNING, **beat) -> SupervisionState:
    return policy.on_beat(SupervisionState(bound=True, watched_pid=100), _beat(state, **beat))[0]


def _crash(state: SupervisionState, now: float) -> tuple[SupervisionState, list]:
    """The watched launcher crashes at ``now``, then its relaunch beats as pid 100 again."""
    state, decisions = policy.on_pid_gone(state, 100, now=now)
    return policy.on_beat(state, _beat(seq=int(now) + 2))[0], decisions


# ── the table ────────────────────────────────────────────────────────────────


def test_three_crashes_in_ten_minutes_back_off_and_the_fourth_drains_restart_limit():
    state, made = _beaten(), []
    for now in (1000.0, 1100.0, 1200.0, 1300.0):
        state, decisions = _crash(state, now)
        made.append([(d.record, d.relaunch, d.delay, d.drain) for d in decisions])
    assert made == [
        [(Record.CRASHED, RelaunchReason.CRASHED, 2.0, None)],
        [(Record.CRASHED, RelaunchReason.CRASHED, 10.0, None)],
        [(Record.CRASHED, RelaunchReason.CRASHED, 30.0, None)],
        [(Record.CRASHED, None, 0.0, None), (Record.RESTART_LIMIT, None, 0.0, "launcher_restart_limit")],
    ]


def test_the_budget_is_a_rolling_window():
    state = _beaten()
    for now in (1000.0, 1100.0, 1200.0):
        state, _ = _crash(state, now)
    # 600 s after the first relaunch it has left the window: one more is allowed, at the third backoff.
    _, decisions = _crash(state, 1600.0)
    assert [(d.relaunch, d.delay) for d in decisions] == [(RelaunchReason.CRASHED, 30.0)]


def test_a_relaunch_no_beat_answers_within_sixty_awake_seconds_spends_the_budget_again():
    state, _ = policy.on_pid_gone(_beaten(), 100, now=1000.0)  # 2 s backoff, then 60 s to beat
    state, _ = policy.on_tick(state, 1000.0)
    wall, made = 1000.0, []
    for _ in range(62):
        wall += 1.0
        state, decisions = policy.on_tick(state, wall)
        made += decisions
    assert [(d.record, d.relaunch, d.delay) for d in made] == [(Record.RELAUNCH_FAILED, RelaunchReason.CRASHED, 10.0)]
    # Positive control: a beat inside the window owes nothing.
    state, _ = policy.on_pid_gone(_beaten(), 100, now=1000.0)
    state, _ = policy.on_tick(state, 1000.0)
    state, _ = policy.on_beat(state, _beat(seq=9))
    assert all(policy.on_tick(state, 1000.0 + n)[1] == [] for n in range(1, 3))


def test_a_supervised_hang_kills_that_pid_relaunches_hung_and_its_exit_is_not_a_second_crash():
    state, _ = policy.on_tick(_beaten(), 1000.0)
    wall, made = 1000.0, []
    for _ in range(45):
        wall += 1.0
        state, decisions = policy.on_tick(state, wall)
        made += decisions
    assert [(d.record, d.kill_pid, d.relaunch, d.delay) for d in made] == [(Record.HUNG, 100, RelaunchReason.HUNG, 2.0)]
    assert policy.on_pid_gone(state, 100, now=wall)[1] == []


@pytest.mark.parametrize("beat", [
    _beat(LauncherState.QUITTING),
    _beat(LauncherState.CLOSING_FOR_GAME),
    _beat(supervise=False),
    _beat(LauncherState.SUSPENDED, game={"session_id": "s1"}),  # waits for the game watch (G1)
])
def test_rows_that_never_relaunch(beat):
    state = policy.on_beat(SupervisionState(bound=True, watched_pid=100), beat)[0]
    assert all(d.relaunch is None for d in policy.on_pid_gone(state, 100, now=1.0)[1])


def test_a_game_ended_relaunch_reason_exists_but_the_budget_only_counts_what_it_spent():
    state, _ = _crash(_beaten(), 1000.0)
    assert state.relaunches == (1000.0,)
    assert RelaunchReason.GAME_ENDED.value == "game_ended"


def test_the_restart_limit_word_is_a_serve_end_reason():
    from hermes_cli.harness_parts.serve.end_reason import EndReason

    assert policy.END_LAUNCHER_RESTART_LIMIT == EndReason.LAUNCHER_RESTART_LIMIT


# ── the wiring ───────────────────────────────────────────────────────────────


class _Relauncher:
    def __init__(self, *, same: bool = True) -> None:
        self.same, self.spawned, self.killed = same, [], []
        self.spawn_done = threading.Event()

    def same_executable(self, pid, executable):
        return self.same

    def kill(self, pid, create_time):
        self.killed.append(pid)
        return True

    def spawn(self, argv):
        self.spawned.append(list(argv))
        self.spawn_done.set()
        return 4242


class _Effects:
    def __init__(self, *, may: bool = True) -> None:
        self.may, self.drained = may, []

    def note_end(self, word):
        pass

    def drain(self, word, pid):
        self.drained.append(word)

    def may_relaunch(self):
        return self.may


def _watchdog(relauncher, effects, *, clock=lambda: 1000.0) -> LauncherWatchdog:
    return LauncherWatchdog(parent_pid=None, effects=effects, tick_seconds=3600.0, clock=clock,
                            relauncher=relauncher)


def test_a_beat_whose_executable_is_not_its_pids_file_supervises_nothing(monkeypatch, caplog):
    monkeypatch.setattr(policy, "BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    for same, expect_spawn in ((False, False), (True, True)):  # the True row is the positive control
        relauncher, effects = _Relauncher(same=same), _Effects()
        watchdog = _watchdog(relauncher, effects)
        try:
            watchdog.beat(_beat(pid=os.getpid(), window_visible=False))
            watchdog._pid_gone(os.getpid())
            assert relauncher.spawn_done.wait(2.0) is expect_spawn
        finally:
            watchdog.stop()
    assert "event=launcher_identity_mismatch" in caplog.text
    assert relauncher.spawned == [["/opt/launcher", "--harness-relaunch=crashed", "--start-hidden"]]


def test_nothing_relaunches_once_the_runtime_is_ending(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(policy, "BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    relauncher = _Relauncher()
    watchdog = _watchdog(relauncher, _Effects(may=False))
    try:
        with caplog.at_level(logging.INFO, logger="agent_runtime.launcher_supervision.watchdog"):
            watchdog.beat(_beat(pid=os.getpid()))
            watchdog._pid_gone(os.getpid())
            deadline = time.monotonic() + 2.0
            while "event=relaunch_skipped" not in caplog.text and time.monotonic() < deadline:
                time.sleep(0.02)
        assert "event=relaunch_skipped" in caplog.text
        assert relauncher.spawned == []
    finally:
        watchdog.stop()


def test_the_budget_survives_a_harness_restart(monkeypatch):
    monkeypatch.setattr(policy, "BACKOFF_SECONDS", (3600.0, 3600.0, 3600.0))  # never fires in the test
    first = _watchdog(_Relauncher(), _Effects())
    try:
        first.beat(_beat(pid=os.getpid()))
        first._pid_gone(os.getpid())
    finally:
        first.stop()
    stored = json.loads(paths.launcher_supervision_state_path().read_text(encoding="utf-8"))
    assert stored["relaunches"] == [1000.0]
    second = _watchdog(_Relauncher(), _Effects())
    try:
        assert second.state.relaunches == (1000.0,)
    finally:
        second.stop()


# ── real processes ───────────────────────────────────────────────────────────


def _sleeper(*args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *args])


def test_identity_is_the_file_not_its_name(tmp_path):
    owner = _sleeper()
    try:
        assert relaunch.same_executable(owner.pid, sys.executable)  # positive control
        impostor = tmp_path / os.path.basename(os.path.realpath(sys.executable))
        impostor.write_bytes(b"not the interpreter")
        assert not relaunch.same_executable(owner.pid, str(impostor))
    finally:
        owner.kill()
        owner.wait(10)


def test_the_hang_kill_takes_the_launcher_and_spares_its_child():
    script = ("import subprocess, sys, time; "
              "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              "print(c.pid, flush=True); time.sleep(60)")
    launcher = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    child_pid = int(launcher.stdout.readline())
    try:
        import psutil

        assert relaunch.kill_one(launcher.pid, psutil.Process(launcher.pid).create_time())
        launcher.wait(10)
        assert psutil.pid_exists(child_pid) and psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE
        assert not relaunch.kill_one(child_pid, 1.0), "a creation time that is not the watched one is refused"
    finally:
        try:
            os.kill(child_pid, 9)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in launcher is a POSIX script")
def test_a_real_spawn_carries_the_relaunch_flag_and_no_hermes_env(tmp_path, monkeypatch):
    out = tmp_path / "argv.json"
    launcher = tmp_path / "launcher"
    launcher.write_text(f"#!{shutil.which('sh') or '/bin/sh'}\n"
                        f"{sys.executable} -c 'import json, os, sys; json.dump([sys.argv[1:], "
                        f"sorted(k for k in os.environ if k.startswith(\"HERMES_\"))], open(\"{out}\", \"w\"))' \"$@\"\n")
    launcher.chmod(0o755)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    pid = relaunch.spawn_detached(relaunch.relaunch_argv(str(launcher), "crashed", start_hidden=True))
    assert pid
    deadline = time.monotonic() + 10
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    argv, hermes_keys = json.loads(out.read_text(encoding="utf-8"))
    assert argv == ["--harness-relaunch=crashed", "--start-hidden"]
    assert hermes_keys == []


# RT-RELAUNCH-GAME-ENDED-SHOWN. Positive control: a hidden crash relaunch keeps the flag; the same
# hidden beat relaunched ``game_ended`` drops it. Mutation: drop the reason guard -> the second reds.
@pytest.mark.parametrize(("reason", "hidden_flag"), [("crashed", True), ("hung", True), ("game_ended", False)])
def test_a_hidden_beat_starts_hidden_except_after_a_game(reason, hidden_flag):
    argv = relaunch.relaunch_argv("/opt/launcher", reason, start_hidden=True)
    assert argv[:2] == ["/opt/launcher", f"--harness-relaunch={reason}"]
    assert (relaunch.START_HIDDEN_FLAG in argv) is hidden_flag
    assert relaunch.START_HIDDEN_FLAG not in relaunch.relaunch_argv("/opt/launcher", reason, start_hidden=False)
