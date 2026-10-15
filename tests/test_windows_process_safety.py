"""Native Windows PID probes must not send console events to the operator."""

import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tests._fixtures.live_system_guard import _live_system_guard


@pytest.mark.platforms("windows")
@pytest.mark.timeout(60)
def test_collection_and_supervisor_query_processes_without_signalling(tmp_path):
    """Exercise import-time cleanup and real live/dead PID queries in a child."""
    script = r'''
import os, pathlib, runpy, subprocess, sys, tempfile
root = pathlib.Path(sys.argv[1])
scratch = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(root))
tempfile.tempdir = str(scratch)
for key in ("TMP", "TEMP", "TMPDIR"):
    os.environ[key] = str(scratch)
os.environ.pop("HERMES_GATEWAY_LOCK_DIR", None)
live = scratch / f"hermes-test-gateway-locks-{os.getpid()}"
child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW)
child.wait(timeout=10)
dead = scratch / f"hermes-test-gateway-locks-{child.pid}"
live.mkdir()
dead.mkdir()
(live / "sentinel").write_text("active", encoding="utf-8")

def refuse_signal(*args, **kwargs):
    raise AssertionError(f"PID query attempted signal delivery: {args}")

os.kill = refuse_signal
# Track pruning before conftest intentionally resets its own PID's directory.
import shutil
real_remove = shutil.rmtree
def check_remove(path, *args, **kwargs):
    if pathlib.Path(path) == live:
        assert not dead.exists(), "live PID was pruned during the stale sweep"
    return real_remove(path, *args, **kwargs)
shutil.rmtree = check_remove
runpy.run_path(str(root / "tests" / "conftest.py"))
assert not dead.exists()
from tui_gateway.host_supervisor import _pid_alive
assert _pid_alive(os.getpid())
assert not _pid_alive(child.pid)
assert not _pid_alive(0)
assert not _pid_alive(-1)
print("collection and supervisor probes passed")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1]), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "collection and supervisor probes passed" in result.stdout


@pytest.mark.platforms("windows")
def test_guard_refuses_console_events_even_for_own_pid(request, monkeypatch):
    """A no-op spy keeps a broken guard's positive control harmless."""
    with monkeypatch.context() as scoped:
        delivery = Mock()
        scoped.setattr(os, "kill", delivery)
        guard = _live_system_guard.__wrapped__(request, scoped)
        next(guard)
        try:
            for pid in (os.getpid(), 0):
                for event in (signal.CTRL_C_EVENT, signal.CTRL_BREAK_EVENT):
                    with pytest.raises(RuntimeError, match="blocked Windows console event"):
                        os.kill(pid, event)
            delivery.assert_not_called()
        finally:
            with pytest.raises(StopIteration):
                next(guard)
