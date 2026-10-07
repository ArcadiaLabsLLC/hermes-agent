"""A quiet provider wait remains observable until terminal settlement."""
import threading
import time
from types import SimpleNamespace
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
