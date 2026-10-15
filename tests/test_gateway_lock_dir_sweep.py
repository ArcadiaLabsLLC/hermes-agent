"""The conftest sweep delegates PID liveness to the platform-aware psutil API.

``tests/conftest.py`` removes the ``HERMES_GATEWAY_LOCK_DIR`` of every pytest
process that is gone. It used to probe each PID with ``os.kill(pid, 0)``,
which on Windows is ``CTRL_C_EVENT`` to the target's console process group
(bpo-14484): it either interrupts a live sibling worker or raises ``OSError``,
which the sweep read as "dead" and deleted that worker's directory.
"""

from __future__ import annotations

import os

import psutil

from tests._fixtures.gateway_lock_dirs import sweep_stale_lock_dirs


def test_sweep_keeps_live_dirs_removes_dead_ones_and_never_signals(tmp_path, monkeypatch):
    signalled = []

    def _no_signals(pid, sig):
        signalled.append((pid, sig))
        raise OSError("os.kill must not be used as a liveness probe")

    monkeypatch.setattr(os, "kill", _no_signals)
    # On POSIX, psutil itself legitimately uses os.kill(pid, 0) as a non-signalling
    # probe. Stub its public, platform-aware API so this test rejects only a
    # direct os.kill call by the sweep, not psutil's correct POSIX internals.
    live_pid, dead_pid = 4241, 4242
    probes = []

    def _pid_exists(pid):
        probes.append(pid)
        assert pid in (live_pid, dead_pid)
        return pid == live_pid

    monkeypatch.setattr(psutil, "pid_exists", _pid_exists)

    prefix = "hermes-test-gateway-locks-"
    live = tmp_path / f"{prefix}{live_pid}"
    dead = tmp_path / f"{prefix}{dead_pid}"
    unrelated = tmp_path / f"{prefix}not-a-pid"
    for d in (live, dead, unrelated):
        d.mkdir()

    sweep_stale_lock_dirs(tmp_path, prefix)

    assert signalled == []
    assert sorted(probes) == [live_pid, dead_pid]
    assert live.is_dir()
    assert not dead.exists()
    assert unrelated.is_dir()
