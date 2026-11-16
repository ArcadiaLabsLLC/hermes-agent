"""The stream heartbeat carries the Lens store revision, so an idle Lens panel sees a poll.

``RT-LENS-REVISION-RIDES-THE-HEARTBEAT`` (Eternia ``MC-LENS-OPEN-PANEL-MISSES-A-LATER-POLL``).
A poll's observation moves the Lens store revision but emits no event by design, so the only
message an open, idle panel still receives is the 5 s heartbeat; it carries ``lens_revision``
and nothing else is sent for it.

Killing mutation (red recorded in the change commit): drop ``lens_revision=lens_revision()``
from the tail loop's heartbeat in ``agent_runtime/stream/session.py`` -> this test reds on
``KeyError: 'lens_revision'``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_runtime.lens.store import LensStore
from agent_runtime.stream import stream_frames
from tests.agent_runtime.stream_liveness_helpers import drain_boot_liveness

T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)


def _manifest() -> dict:
    return {"version": 1, "monitor_id": "status",
            "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                       "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
            "rules": [], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
            "persona_id": None}


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _next_heartbeat(frames) -> dict:
    frame = next(frames)
    # A poll-only write sends nothing of its own: the next frame is the beat, not a delta.
    assert frame["type"] == "heartbeat", frame["type"]
    return frame


def test_a_poll_only_write_reaches_the_next_heartbeat_and_nothing_else(isolate_agent_runtime_root):
    _rpc("runtime.lens.create", {"manifest": _manifest()})
    frames = stream_frames(poll_interval_seconds=0.01, heartbeat_interval_seconds=0.01, max_frames=4)
    assert drain_boot_liveness(frames)["type"] == "hydrate"

    before = _next_heartbeat(frames)["lens_revision"]
    assert before == LensStore().store_revision() > 0

    # The poller's write: an observation, which moves the revision and emits no event.
    LensStore().record("status", "api", observed_at=T0, received_at=T0, value=1.0, reason="ok")

    assert _next_heartbeat(frames)["lens_revision"] == before + 1
