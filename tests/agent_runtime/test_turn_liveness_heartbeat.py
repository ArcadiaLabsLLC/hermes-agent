"""A quiet provider wait remains observable until terminal settlement."""
import threading
import time
from types import SimpleNamespace
import pytest
from hermes_cli.harness_parts.persona.tool_heartbeat import ToolHeartbeat


def test_quiet_turn_heartbeat_runs_without_live_tools_and_stops():
    beat = threading.Event()
    frames = []
    def emit(frame):
        frames.append(frame)
        beat.set()
    emitter = SimpleNamespace(turn_id="quiet", elements=[], _started_at=time.monotonic(), _emit_chat_frame=emit)
    heartbeat = ToolHeartbeat(emitter, interval=0.01)
    heartbeat.ensure_running()
    assert beat.wait(2)
    heartbeat.stop()
    heartbeat._thread.join(2)
    assert not heartbeat._thread.is_alive()
    assert frames[0]["type"] == "turn.progress"
    assert frames[0]["turn_id"] == "quiet"
    assert frames[0]["elapsed_ms"] >= 0
    assert frames[0]["next_heartbeat_after_ms"] == 10


@pytest.mark.parametrize("blocked_type", ["turn.progress", "tool.progress"])
def test_inflight_heartbeat_cannot_emit_progress_after_real_finish(monkeypatch, blocked_type):
    from hermes_cli.harness_parts.persona import chat_events
    frames, errors = [], []
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(chat_events, "_emit_chat_frame", lambda frame: frames.append(frame))
    # Schedule the real beat ourselves so the race never depends on wall time.
    monkeypatch.setattr(ToolHeartbeat, "ensure_running", lambda self: None)
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="finish-race", client_message_id="finish-race")
    emitter.delta("reply")
    emitter.elements.append({"kind": "tool", "state": "started", "name": "terminal", "id": "tool", "seq": 2})
    real_emit = emitter._emit_chat_frame
    def blocked_emit(frame):
        if frame["type"] == blocked_type:
            entered.set()
            if not release.wait(2):
                raise AssertionError("test failed to release heartbeat")
        real_emit(frame)
    monkeypatch.setattr(emitter, "_emit_chat_frame", blocked_emit)
    def beat():
        try: emitter._heartbeat.beat()
        except Exception as exc: errors.append(exc)
    worker = threading.Thread(target=beat, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        # The real finish stops the heartbeat; it must not wait for the blocked beat.
        emitter.finish(state="completed")
        assert emitter._heartbeat._stop.is_set()
        assert frames[-1]["type"] == "turn.end"
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not errors
    types = [frame["type"] for frame in frames]
    terminal = types.index("turn.end")
    assert "segment.end" in types[:terminal]
    assert types.count("turn.end") == 1
    assert not any(kind in {"turn.progress", "tool.progress"} for kind in types[terminal + 1:])
