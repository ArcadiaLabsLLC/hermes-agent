"""The one Windows spawn rule for a child that must outlive its parent's job (review w1118a.57 D10).

``_subprocess_compat.popen_breaking_away`` spawns with ``CREATE_BREAKAWAY_FROM_JOB`` and, when
the parent's job refuses it, spawns again without it. The launcher relaunch
(``relaunch.spawn_detached``) goes through it. (An agent request's child did too until
2026-11-21, when a dispatched turn became a native turn of the serve and its child retired.)
Built on Linux with a faked ``Popen``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.launcher_supervision import relaunch
from hermes_cli import _subprocess_compat

BREAKAWAY = 0x01000000
NO_WINDOW = 0x08000000


class _FakePopen:
    """Records each spawn's creationflags; refuses the breakaway bit when ``refuse`` is set."""

    def __init__(self, refuse: BaseException | None = None) -> None:
        self.refuse = refuse
        self.flags: list[int] = []

    def __call__(self, argv, **kwargs):
        flags = kwargs.get("creationflags", 0)
        self.flags.append(flags)
        if self.refuse is not None and flags & BREAKAWAY:
            raise self.refuse
        return SimpleNamespace(pid=4242, argv=argv, kwargs=kwargs)


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(_subprocess_compat, "IS_WINDOWS", True)


def test_the_spawn_breaks_away_when_the_job_allows_it(windows):
    popen = _FakePopen()
    result, broke_away = _subprocess_compat.popen_breaking_away(lambda f: popen([], creationflags=f), NO_WINDOW)
    assert broke_away and result.pid == 4242
    assert popen.flags == [NO_WINDOW | BREAKAWAY]


def test_a_refused_breakaway_spawns_inside_the_job(windows):
    popen = _FakePopen(refuse=PermissionError(13, "Access is denied"))
    heard: list[OSError] = []
    result, broke_away = _subprocess_compat.popen_breaking_away(
        lambda f: popen([], creationflags=f), NO_WINDOW, on_refused=heard.append,
    )
    assert not broke_away and result.pid == 4242
    assert popen.flags == [NO_WINDOW | BREAKAWAY, NO_WINDOW]
    assert len(heard) == 1


def test_any_other_spawn_failure_is_not_retried(windows):
    popen = _FakePopen(refuse=FileNotFoundError(2, "no such program"))
    with pytest.raises(FileNotFoundError):
        _subprocess_compat.popen_breaking_away(lambda f: popen([], creationflags=f), NO_WINDOW)
    assert popen.flags == [NO_WINDOW | BREAKAWAY]


def test_off_windows_the_flags_pass_through_once(monkeypatch):
    monkeypatch.setattr(_subprocess_compat, "IS_WINDOWS", False)
    popen = _FakePopen()
    assert _subprocess_compat.popen_breaking_away(lambda f: popen([], creationflags=f), 0)[1] is False
    assert popen.flags == [0]


def test_the_relaunch_takes_the_same_rule(monkeypatch, windows):
    popen = _FakePopen(refuse=PermissionError(13, "Access is denied"))
    monkeypatch.setattr(relaunch, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(relaunch.subprocess, "Popen", popen)
    assert relaunch.spawn_detached(["launcher"], {}) == 4242
    detach = _subprocess_compat.windows_detach_flags_without_breakaway()
    assert popen.flags == [detach | BREAKAWAY, detach]
