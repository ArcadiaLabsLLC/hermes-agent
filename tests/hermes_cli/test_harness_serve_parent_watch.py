"""``harness serve --parent-pid``: a bundled runtime drains itself when its Launcher dies.

Embedded-hermes D1 exit: crashing leaves no bundled Hermes running. The owner is
a real child process here (the stand-in Launcher); killing it runs no stop verb,
exactly like a crash. The seam is the real ``serve_loop``; the end reason is read
back from the real sidecar.

Killing mutations are recorded in the commit that added this file.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from agent_runtime import parent_watch
from agent_runtime.serve_registry import read_serve_ended
from hermes_cli.harness_parts import serve as serve_module
from hermes_cli.harness_parts.serve import serve_loop

WAIT = 25.0


class _Pipe:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()

    def __iter__(self) -> "_Pipe":
        return self

    def __next__(self) -> str:
        item = self._queue.get()
        if item is None:
            raise StopIteration
        return item

    def close(self) -> None:
        self._queue.put(None)


class _Sink:
    def __init__(self) -> None:
        self._parts: list[str] = []
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._parts.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def frames(self) -> list[dict]:
        with self._lock:
            raw = "".join(self._parts)
        out = []
        for line in raw.splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def wait_for(self, event: str, timeout: float = WAIT) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in self.frames():
                if frame.get("event") == event:
                    return frame
            time.sleep(0.02)
        raise AssertionError(f"no {event!r} frame within {timeout}s: {[f.get('event') for f in self.frames()]}")


def _owner() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


@pytest.fixture
def no_console_handler(monkeypatch):
    # Arming the end-reason recorder installs a process-wide console handler on Windows.
    monkeypatch.setattr(serve_module.boot_phases, "_install_console_ctrl_reason_handler", lambda recorder: None)


def _serve(parent_pid):
    pipe, sink, result = _Pipe(), _Sink(), {}

    def go() -> None:
        result["code"] = serve_loop(pipe, sink, parent_pid=parent_pid, record_end_reason=True,
                                    drain_wakeup=pipe.close, liveness_pump_interval_seconds=60.0,
                                    dispatch=lambda argv: 0)

    thread = threading.Thread(target=go, name="serve-parent-watch", daemon=True)
    thread.start()
    return pipe, sink, thread, result


def test_the_runtime_drains_itself_when_its_owner_dies(no_console_handler, monkeypatch):
    monkeypatch.setattr(parent_watch, "PARENT_POLL_SECONDS", 0.1)
    owner = _owner()
    try:
        pipe, sink, thread, result = _serve(owner.pid)
        ready = sink.wait_for("ready")
        assert ready["parent_pid"] == owner.pid
        # Positive control for the kill below: an owner that is alive is not "gone".
        time.sleep(1.5)
        assert "parent_exited" not in {f.get("event") for f in sink.frames()}
        owner.kill()
        owner.wait(10)
        gone = sink.wait_for("parent_exited")
        assert gone["parent_pid"] == owner.pid
        sink.wait_for("drain_complete")
        thread.join(WAIT)
        assert not thread.is_alive(), "the runtime outlived its owner"
        assert result["code"] == 0
        from agent_runtime import paths

        assert (read_serve_ended(paths.store_root(), os.getpid()) or {}).get("reason") == "parent_exited"
    finally:
        if owner.poll() is None:
            owner.kill()


def test_without_the_flag_nothing_is_watched(no_console_handler):
    pipe, sink, thread, result = _serve(None)
    try:
        ready = sink.wait_for("ready")
        assert ready["parent_pid"] is None
    finally:
        pipe.close()
        thread.join(WAIT)
    assert "parent_exited" not in {f.get("event") for f in sink.frames()}


def test_an_owner_already_gone_at_boot_drains_at_once():
    owner = _owner()
    owner.kill()
    owner.wait(10)
    fired = threading.Event()
    watch = parent_watch.start_parent_watch(owner.pid, fired.set, poll_seconds=0.05)
    assert fired.wait(10)
    # A pid no process holds (the owner's record is gone too): Windows cannot even open it.
    bogus = threading.Event()
    parent_watch.start_parent_watch(0x7FFFFFFC, bogus.set, poll_seconds=0.05)
    assert bogus.wait(10)
    # Positive control: a live process does not fire.
    alive = threading.Event()
    live = parent_watch.start_parent_watch(os.getpid(), alive.set, poll_seconds=0.05)
    assert not alive.wait(0.5)
    live.stop.set()
    watch.stop.set()


def test_a_non_positive_parent_pid_is_refused(capsys):
    from types import SimpleNamespace

    from hermes_cli.harness_parts.serve.commands import _cmd_serve

    code = _cmd_serve(SimpleNamespace(ndjson=True, service=False, no_socket=True, parent_pid=0))
    assert code == 2 and json.loads(capsys.readouterr().out)["error"] == "invalid_parent_pid"
