"""Fork-owned tests moved out of ``tests/hermes_cli/test_gui_command.py`` (lane CARRY).

The upstream file is byte-identical to upstream. Since lane ADOPT (2026-09-24)
the sweep under test is upstream's own
``hermes_cli.main_desktop._stop_desktop_processes_locking_build``; these pins
drive it through ``psutil.process_iter`` / ``psutil.wait_procs``, where it reads.
"""

from __future__ import annotations
import os
import sys
import pytest
from hermes_cli import main_desktop

from tests.hermes_cli.test_gui_command import (  # noqa: F401 — upstream names the moved tests use
    _isolate_xdg_data_home,
    _stable_keychain_detection,
)


class _FakeProc:
    """Minimal psutil.Process stand-in for the lock-breaker tests."""

    def __init__(self, pid: int, exe: str | None):
        self.pid = pid
        self.info = {"pid": pid, "exe": exe}
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _drive_psutil(monkeypatch, rows, *, still_locked=()):
    """Serve ``rows`` from ``psutil.process_iter``; ``still_locked`` outlive terminate."""
    psutil = pytest.importorskip("psutil")
    calls = {"iter": 0, "waits": []}

    def process_iter(attrs=None):
        calls["iter"] += 1
        return iter(rows)

    def wait_procs(procs, timeout=None):
        procs = list(procs)
        calls["waits"].append([p.pid for p in procs])
        alive = [p for p in procs if p in still_locked and not p.killed]
        return [p for p in procs if p not in alive], alive

    monkeypatch.setattr(psutil, "process_iter", process_iter)
    monkeypatch.setattr(psutil, "wait_procs", wait_procs)
    return calls


@pytest.mark.skipif(sys.platform != "win32", reason="the sweep is win32-only")
class TestDesktopBuildLockSweep:
    """Upstream's sweep stops exactly the processes executing from this release tree."""

    def test_a_locking_process_is_terminated_and_reported(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        release = desktop / "release" / "win-unpacked"
        release.mkdir(parents=True)
        locker = _FakeProc(4242, str(release / "Hermes.exe"))
        # Two rows the filter must reject, for the two different reasons:
        # an exe outside the release tree, and this very process.
        outsider = _FakeProc(4343, str(tmp_path / "elsewhere" / "Hermes.exe"))
        myself = _FakeProc(os.getpid(), str(release / "Hermes.exe"))
        calls = _drive_psutil(monkeypatch, [locker, outsider, myself])

        assert main_desktop._stop_desktop_processes_locking_build(desktop) == [4242]
        assert calls["iter"] == 1
        assert locker.terminated is True
        assert outsider.terminated is False
        assert myself.terminated is False

    def test_a_process_that_keeps_the_lock_is_killed(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        release = desktop / "release" / "win-unpacked"
        release.mkdir(parents=True)
        stubborn = _FakeProc(5151, str(release / "Hermes.exe"))
        calls = _drive_psutil(monkeypatch, [stubborn], still_locked=(stubborn,))

        assert main_desktop._stop_desktop_processes_locking_build(desktop) == [5151]
        assert stubborn.terminated is True
        assert stubborn.killed is True
        assert calls["waits"] == [[5151], [5151]]

    def test_no_inspector_stops_nothing(self, tmp_path, monkeypatch):
        desktop = tmp_path / "apps" / "desktop"
        (desktop / "release").mkdir(parents=True)
        monkeypatch.setitem(sys.modules, "psutil", None)  # ``import psutil`` raises
        assert main_desktop._stop_desktop_processes_locking_build(desktop) == []


def test_the_directory_fence_hands_every_scan_an_empty_process_table():
    """``tests/_downstream/hermes_cli_conftest._no_live_process_table`` reaches the
    call both upstream scans make. Positive control: the sweep tests above drive
    rows through the same attribute and see them."""
    psutil = pytest.importorskip("psutil")
    assert list(psutil.process_iter(["pid", "exe"])) == []
