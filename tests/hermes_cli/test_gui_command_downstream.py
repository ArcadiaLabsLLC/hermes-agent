"""Fork-owned tests moved out of ``tests/hermes_cli/test_gui_command.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from __future__ import annotations
import sys
import pytest
from hermes_cli import main as cli_main

from tests.hermes_cli.test_gui_command import (  # noqa: F401 — upstream names the moved tests use
    _isolate_xdg_data_home,
    _stable_keychain_detection,
)


class _FakeProc:
    """Minimal psutil.Process stand-in for the lock-breaker tests.

    ``still_locked_after_terminate`` makes ``wait`` raise the way psutil's does
    when a terminated process outlives the timeout, which is the only way the
    kill escalation is reachable at all.
    """

    def __init__(self, pid: int, exe: str | None, *, still_locked_after_terminate=False):
        self.pid = pid
        self.info = {"pid": pid, "exe": exe}
        self.terminated = False
        self.killed = False
        self.waits: list[float] = []
        self._still_locked = still_locked_after_terminate

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self._still_locked:
            raise TimeoutError("still holding the lock")
        return 0


class _RefusingProcessIter:
    """Stands in for ``psutil.process_iter`` and refuses to enumerate.

    Counting alone would let a mutant walk the live table and still pass on a
    machine that happens to be running nothing from this build's release tree;
    raising makes the bypass fatal wherever it happens. Same instrument as
    ``tests/hermes_cli/test_profiles.py``'s ``_RealEnumeratorRecorder``.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError(
            "the desktop build-lock sweep reached the live process table"
        )


@pytest.fixture(autouse=True)
def _no_live_process_iter(monkeypatch):
    """No test in THIS FILE may enumerate the machine's processes.

    ``cmd_gui`` -> ``_stop_desktop_processes_locking_build`` used to call
    ``psutil.process_iter`` once per run of this file (ledger B20(vi)). The
    directory conftest already defaults the seam to an empty table; this pins
    the stronger claim at the layer underneath it — nothing here reaches psutil
    at all, whichever way it tries.
    """
    psutil = pytest.importorskip("psutil")
    recorder = _RefusingProcessIter()
    monkeypatch.setattr(psutil, "process_iter", recorder)
    yield recorder
    assert recorder.calls == 0


def _driven_table(rows, *, self_pid=424242):
    from hermes_cli import profiles

    return profiles._ProcessTable(
        self_pid=self_pid,
        ancestor_pids=frozenset(),
        current_username=None,
        processes=tuple(rows),
    )


def _row(proc: _FakeProc):
    from hermes_cli import profiles

    return profiles._ProcessFacts(
        pid=proc.pid, exe=proc.info["exe"], inspector_handle=proc
    )


class _DrivenDesktopLister:
    def __init__(self, table):
        self._table = table
        self.reads = 0

    def read(self):
        self.reads += 1
        return self._table


@pytest.mark.skipif(sys.platform != "win32", reason="the sweep is win32-only")
class TestDesktopBuildLockSweepSeam:
    """The sweep reads the injected table, never the machine's."""

    def test_a_locking_process_is_terminated_and_reported(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        release = desktop / "release" / "win-unpacked"
        release.mkdir(parents=True)
        locker = _FakeProc(4242, str(release / "Hermes.exe"))
        # Two rows the filter must reject, for the two different reasons:
        # an exe outside the release tree, and this very process.
        outsider = _FakeProc(4343, str(tmp_path / "elsewhere" / "Hermes.exe"))
        myself = _FakeProc(424242, str(release / "Hermes.exe"))

        lister = _DrivenDesktopLister(
            _driven_table([_row(locker), _row(outsider), _row(myself)])
        )
        monkeypatch.setattr(cli_main, "_DESKTOP_PROCESS_LISTER", lister)

        assert cli_main._stop_desktop_processes_locking_build(desktop) == [4242]
        assert lister.reads == 1
        assert locker.terminated is True
        assert outsider.terminated is False
        assert myself.terminated is False

    def test_a_process_that_keeps_the_lock_is_killed(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        release = desktop / "release" / "win-unpacked"
        release.mkdir(parents=True)
        stubborn = _FakeProc(
            5151, str(release / "Hermes.exe"), still_locked_after_terminate=True
        )

        monkeypatch.setattr(
            cli_main,
            "_DESKTOP_PROCESS_LISTER",
            _DrivenDesktopLister(_driven_table([_row(stubborn)])),
        )

        assert cli_main._stop_desktop_processes_locking_build(desktop) == [5151]
        assert stubborn.terminated is True
        assert stubborn.killed is True
        assert len(stubborn.waits) == 1

    def test_no_inspector_stops_nothing(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        (desktop / "release").mkdir(parents=True)

        class _NoInspector:
            def read(self):
                return None

        monkeypatch.setattr(cli_main, "_DESKTOP_PROCESS_LISTER", _NoInspector())
        assert cli_main._stop_desktop_processes_locking_build(desktop) == []
