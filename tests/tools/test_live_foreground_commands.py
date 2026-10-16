"""live_foreground_commands(): a read-only snapshot of in-flight foreground terminal commands."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from tools.environments import base
from tools.environments.local import LocalEnvironment


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (value := predicate()):
            return value
        time.sleep(0.05)
    return None


def test_snapshot_reports_a_running_command_and_empties_after_it_ends(tmp_path):
    assert base.live_foreground_commands() == []  # control: nothing spawned yet
    env = LocalEnvironment(cwd=str(tmp_path))
    script = tmp_path / "mark.py"
    script.write_text("import time\nprint('mark', flush=True)\ntime.sleep(5)\n", encoding="utf-8")
    command = f"\"{Path(sys.executable).as_posix()}\" \"{script.as_posix()}\""
    worker_tid: list[int] = []

    def _run():
        worker_tid.append(threading.get_ident())
        env.execute(command, timeout=30)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    try:
        live = _wait_for(lambda: [c for c in base.live_foreground_commands() if c.output_chars > 0])
        assert live, "the running command never showed output in the snapshot"
        cmd = live[0]
        assert isinstance(cmd.pid, int)
        assert "mark.py" in cmd.command
        assert cmd.owner_tid == worker_tid[0]
        assert cmd.timeout_seconds == 30
        assert cmd.elapsed_seconds >= 0
        assert "mark" in cmd.tail
        assert isinstance(cmd.seconds_since_output, float)
        assert base.live_foreground_commands(owner_tid=worker_tid[0])
        assert base.live_foreground_commands(owner_tid=-1) == []
    finally:
        base.kill_live_foreground_processes()
        thread.join(15)
        env.cleanup()
    assert not thread.is_alive()
    assert base.live_foreground_commands() == []
