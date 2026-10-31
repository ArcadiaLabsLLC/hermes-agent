"""``launcher_beat`` on a real serve: the op, the re-targeted watch, the end reason on disk (W1).

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §5. The owners
are real child processes standing in for a launcher; killing one runs no stop verb, exactly like a
crash. The pure table is ``tests/agent_runtime/test_launcher_supervision_policy.py``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from agent_runtime import parent_watch
from agent_runtime.launcher_supervision import LauncherWatchdog, parse_beat
from agent_runtime.serve_registry import read_serve_ended
from hermes_cli.harness_parts.serve import handle_message
from hermes_cli.harness_parts.serve.manifest import ops_manifest
from tests.hermes_cli.test_harness_serve_parent_watch import WAIT, _owner, _serve, no_console_handler


def _beat_frame(pid: int, state: str = "running", seq: int = 1, *, supervise: bool = True) -> dict:
    return {"op": "launcher_beat", "id": f"beat-{seq}", "seq": seq, "pid": pid, "state": state,
            "window_visible": True, "executable": sys.executable, "build": {"commit": "test"},
            "supervise": supervise}


def _send(pipe, frame: dict) -> None:
    import json

    pipe._queue.put(json.dumps(frame) + "\n")


def test_the_op_is_advertised_on_local_transports_and_never_to_a_device():
    assert "launcher_beat" in ops_manifest(transport="stdio")["ops"]  # positive control
    assert "launcher_beat" in ops_manifest(transport="socket")["ops"]
    assert "launcher_beat" not in ops_manifest(transport="gateway")["ops"]


def test_a_device_sending_a_beat_is_refused_before_anything_is_watched():
    frames: list[dict] = []
    sink = SimpleNamespace(emit=frames.append)
    session = SimpleNamespace(launcher_watchdog=None)
    handler = handle_message.OP_HANDLERS["launcher_beat"]
    handler(session, _beat_frame(os.getpid()), sink, SimpleNamespace(transport="gateway"))
    assert [f["error"] for f in frames] == ["op_not_available_on_gateway"]
    assert session.launcher_watchdog is None


def test_a_beat_moves_the_watch_and_the_first_owner_exiting_then_changes_nothing(no_console_handler, monkeypatch):
    monkeypatch.setattr(parent_watch, "PARENT_POLL_SECONDS", 0.1)
    first, second = _owner(), _owner()
    try:
        pipe, sink, thread, result = _serve(first.pid)
        sink.wait_for("ready")
        # supervise: false so the second owner's exit drains (a supervised one is relaunched, W2).
        _send(pipe, _beat_frame(second.pid, supervise=False))
        ok = sink.wait_for("launcher_beat_ok")
        assert (ok["seq"], ok["watching"]) == (1, False)
        first.kill()
        first.wait(10)
        time.sleep(1.5)
        assert "parent_exited" not in {f.get("event") for f in sink.frames()}, "the old pid still owned the runtime"
        second.kill()
        second.wait(10)
        sink.wait_for("parent_exited")
        sink.wait_for("drain_complete")
        thread.join(WAIT)
        assert not thread.is_alive() and result["code"] == 0
        from agent_runtime import paths

        assert (read_serve_ended(paths.store_root(), os.getpid()) or {}).get("reason") == "parent_exited"
    finally:
        for owner in (first, second):
            if owner.poll() is None:
                owner.kill()


def test_a_launcher_that_beat_quitting_ends_the_runtime_as_launcher_quit(no_console_handler, monkeypatch):
    monkeypatch.setattr(parent_watch, "PARENT_POLL_SECONDS", 0.1)
    owner = _owner()
    try:
        pipe, sink, thread, result = _serve(owner.pid)
        sink.wait_for("ready")
        _send(pipe, _beat_frame(owner.pid, state="quitting"))
        sink.wait_for("launcher_beat_ok")
        owner.kill()
        owner.wait(10)
        sink.wait_for("launcher_quit")
        sink.wait_for("drain_complete")
        thread.join(WAIT)
        assert not thread.is_alive() and result["code"] == 0
        from agent_runtime import paths

        assert (read_serve_ended(paths.store_root(), os.getpid()) or {}).get("reason") == "launcher_quit"
    finally:
        if owner.poll() is None:
            owner.kill()


def test_an_unreadable_beat_is_answered_typed_and_supervises_nothing(no_console_handler):
    pipe, sink, thread, _result = _serve(None)
    try:
        sink.wait_for("ready")
        _send(pipe, {**_beat_frame(os.getpid()), "state": "napping"})
        refused = sink.wait_for("error")
        assert (refused["error"], refused["field"]) == ("invalid_launcher_beat", "state")
        assert "launcher_beat_ok" not in {f.get("event") for f in sink.frames()}
    finally:
        pipe.close()
        thread.join(WAIT)


class _Effects:
    def __init__(self) -> None:
        self.drained: list[str] = []
        self.noted: list[str] = []
        self.done = threading.Event()

    def note_end(self, word: str) -> None:
        self.noted.append(word)

    def drain(self, word: str, pid: int | None) -> None:
        self.drained.append(word)
        self.done.set()


def test_only_the_connection_that_beat_can_drop_it(caplog):
    beat = parse_beat({k: v for k, v in _beat_frame(os.getpid()).items() if k not in {"op", "id"}})
    effects = _Effects()
    watchdog = LauncherWatchdog(parent_pid=None, effects=effects, tick_seconds=3600.0)
    beating, other = object(), object()
    try:
        with caplog.at_level(logging.INFO, logger="agent_runtime.launcher_supervision.watchdog"):
            watchdog.beat(beat, connection=beating)
            watchdog.connection_closed(other)
            assert "event=connection_dropped" not in caplog.text
            watchdog.connection_closed(beating)
        assert "event=connection_dropped" in caplog.text
        assert "event=retargeted" in caplog.text
        assert effects.drained == [], "a dropped connection is not a crash"
    finally:
        watchdog.stop()


def test_a_reused_pid_is_not_the_launcher_it_replaced():
    owner = _owner()
    try:
        fired = threading.Event()
        created = parent_watch.process_create_time(owner.pid)
        assert created is not None
        live = parent_watch.start_parent_watch(owner.pid, fired.set, poll_seconds=0.05, create_time=created)
        assert not fired.wait(0.5)  # positive control: the right creation time is the launcher
        live.disarm()
        if sys.platform == "win32":
            pytest.skip("Windows holds a SYNCHRONIZE handle; pid reuse cannot fool it")
        reused = parent_watch.start_parent_watch(owner.pid, fired.set, poll_seconds=0.05, create_time=created - 60)
        assert fired.wait(10)
        reused.disarm()
    finally:
        owner.kill()
        owner.wait(10)
