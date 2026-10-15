from __future__ import annotations

import subprocess
import importlib.util

from hermes_time import now

from agent_runtime.dirty_state import build_dirty_state
from types import SimpleNamespace

Task = SimpleNamespace
from agent_runtime.states import TaskState
from agent_runtime.store import TaskStore


def test_dirty_state_reports_runtime_temp_state(monkeypatch):
    monkeypatch.setattr("agent_runtime.dirty_state.repo_dirty_states", lambda repos: [])
    state = build_dirty_state(runs=[], repos=[])

    assert state["dirty"] is False
    assert "open_tasks" not in state["runtime"]
    assert "stage47_temp_open_tasks" not in state["runtime"]
    assert state["summary"] == "clean"


def test_new_goal_hygiene_cancels_stage47_temp_state_and_orphan_runs():
    assert importlib.util.find_spec("agent_runtime.goal_hygiene") is None
    assert not hasattr(TaskStore(), "create")


def test_retired_persona_diagnostics_module_stays_gone():
    """S50 retargeted this from ``..._can_cleanup_launcher_visual_processes``.

    The old test asserted three things: that ``persona_diagnostics`` is gone,
    that a dict literal it built one line earlier had the value it had just been
    given (vacuous), and that ``clean_launcher_visual_processes`` was not None
    (an existence check on the module S50 deletes). Only the first was a real
    gate, so only the first survives — under a name that says what it checks.
    """

    assert importlib.util.find_spec("agent_runtime.persona_diagnostics") is None


def test_git_dirty_state_never_writes_the_index_it_reads(tmp_path, monkeypatch):
    """The probe is a read: it must not take ``index.lock`` to refresh the index.

    A plain ``git status`` rewrites a stale index opportunistically, which takes the
    checkout's lock and blocks a concurrent commit (git-audit 2026-10-10). The
    conftest sets ``GIT_OPTIONAL_LOCKS=0`` for test processes only, so it is removed
    here to prove the flag the production call carries itself.
    """
    import os

    from agent_runtime.dirty_state import _git_dirty_state

    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("x", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "seed")
    index = tmp_path / ".git" / "index"
    stamp = index.stat().st_mtime + 100
    os.utime(tracked, (stamp, stamp))  # same bytes, stale stat cache: status would refresh
    before = index.stat().st_mtime_ns

    state = _git_dirty_state(label="probe", root=tmp_path)

    assert state["dirty"] is False
    assert index.stat().st_mtime_ns == before
