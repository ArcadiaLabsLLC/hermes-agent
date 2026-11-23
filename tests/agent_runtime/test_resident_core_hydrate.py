"""A one-shot hydrate is answered from the serve's resident core, never a build of
its own (row RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE,
step 4).

Covers ``agent_runtime.resident_core.read.answer_hydrate`` through the entry point
``harness stream --max-frames 1`` uses (``stream_frames`` → ``StreamSession.boot`` →
``_SnapshotBuildJob.run``), with ``build_snapshot`` replaced by a recorder so a
build is a counted fact.
"""

from __future__ import annotations

import threading
import time

import pytest

from agent_runtime import resident_core
from agent_runtime.parity import events_position
from agent_runtime.resident_core import holder, read
from agent_runtime.stream import build as stream_build
from agent_runtime.stream import stream_frames


@pytest.fixture
def resident_on(isolate_agent_runtime_root, monkeypatch):
    monkeypatch.setattr(read, "resident_core_enabled", lambda: True)
    builds: list[str] = []

    def _recording_build(*args, **kwargs):
        builds.append((kwargs.get("build_info") or {}).get("caller", "?"))
        return _core(int(events_position()["event_offset"] or 0), marker="built")

    monkeypatch.setattr(stream_build, "build_snapshot", _recording_build)
    resident_core.drop("test_setup")
    yield builds
    resident_core.drop("test_teardown")


def _core(offset: int, *, marker: str) -> dict:
    return {"marker": marker, "parity": {"watermark": {"event_offset": offset, "captured_at": "t"}}}


def _seed_at(offset: int) -> None:
    holder.observe({"type": "hydrate", "watermark": {"event_offset": offset}, "core": _core(offset, marker="resident")})


def _one_shot(caller: str = "cli") -> dict:
    return next(stream_frames(max_frames=1, caller=caller, poll_interval_seconds=0.01, heartbeat_interval_seconds=60))


def _append_one() -> int:
    from agent_runtime.events import EventLog
    from agent_runtime.models import Event
    from hermes_time import now

    EventLog().append(Event(now(), "workspace.updated", None, None, None, {"change": "test"}))
    return int(events_position()["event_offset"])


def test_a_one_shot_at_the_log_end_is_the_resident_core_and_no_build(resident_on):
    builds = resident_on
    _seed_at(_append_one())
    frame = _one_shot()
    assert frame["type"] == "hydrate"
    assert frame["core"]["marker"] == "resident"
    assert builds == []


def test_a_one_shot_behind_the_log_waits_for_the_pending_apply_not_a_build(resident_on):
    builds = resident_on
    _seed_at(_append_one())
    end = _append_one()

    def _apply_later():
        time.sleep(0.3)
        _seed_at(end)

    threading.Thread(target=_apply_later, daemon=True).start()
    frame = _one_shot()
    assert frame["core"]["marker"] == "resident"
    assert frame["watermark"]["event_offset"] == end
    assert builds == []


def test_with_no_live_producer_a_one_shot_behind_the_log_builds_at_once(resident_on, monkeypatch):
    builds = resident_on
    _seed_at(_append_one())
    _append_one()
    monkeypatch.setattr(holder, "_last_seen", 0.0)
    started = time.monotonic()
    frame = _one_shot()
    assert frame["core"]["marker"] == "built"
    assert builds == ["cli"]
    assert time.monotonic() - started < read.PENDING_APPLY_WAIT_S / 2, "it did not wait for an apply nobody makes"


def test_with_no_resident_core_a_one_shot_builds(resident_on):
    builds = resident_on
    frame = _one_shot()
    assert frame["core"]["marker"] == "built"
    assert builds == ["cli"]
