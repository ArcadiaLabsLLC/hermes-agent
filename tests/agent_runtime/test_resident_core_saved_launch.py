"""The first launch after a hermes update paints the saved agent list at once,
labeled stale, while the rebuild runs behind it (row
RT-FU-ETERNIA-SHOWS-THE-SAVED-AGENT-LIST-AT-LAUNCH-EVEN-AFTER-AN-UPDATE).

Driven through the entry point Eternia's launch read uses, ``harness stream
--max-frames 1`` (``stream_frames`` -> ``StreamSession.boot`` ->
``_SnapshotBuildJob.run`` -> ``resident_core.read.answer_hydrate``), with
``build_snapshot`` replaced by a recorder so a build is a counted fact, and the
persisted pair's judgement (``core_cache.lane._armed_window_read``) handed in so
each refusal reason is the case under test.
"""

from __future__ import annotations

import pytest

from agent_runtime import resident_core
from agent_runtime.core_cache import lane as cache_lane
from agent_runtime.core_cache.models import CacheRead
from agent_runtime.core_cache.vocabulary import (
    DEMOTE_BUILD_STAMP_MISMATCH,
    DEMOTE_CONTRACT_MISMATCH,
    DEMOTE_HOME_MISMATCH,
)
from agent_runtime.resident_core import holder, read
from agent_runtime.snapshot import build as snapshot_build
from agent_runtime.stream import build as stream_build
from agent_runtime.stream import stream_frames


def _core(offset: int, *, marker: str) -> dict:
    return {"marker": marker, "parity": {"watermark": {"event_offset": offset, "captured_at": "t"}}}


@pytest.fixture
def launch(isolate_agent_runtime_root, monkeypatch):
    """A serve at launch: lane armed, the boot rebuild running, a saved pair on disk."""

    monkeypatch.setattr(read, "resident_core_enabled", lambda: True)
    monkeypatch.setattr(cache_lane, "_lane_armed", True)
    monkeypatch.setattr(snapshot_build, "build_in_flight", lambda: True)
    builds: list[str] = []

    def _recording_build(*args, **kwargs):
        builds.append((kwargs.get("build_info") or {}).get("caller", "?"))
        return _core(0, marker="built")

    monkeypatch.setattr(stream_build, "build_snapshot", _recording_build)

    def _saved(reason: str) -> None:
        monkeypatch.setattr(
            cache_lane,
            "_armed_window_read",
            lambda: CacheRead(_core(7, marker="saved"), False, reason, None, {}),
        )

    resident_core.drop("test_setup")
    yield builds, _saved
    resident_core.drop("test_teardown")


def _one_shot() -> dict:
    return next(stream_frames(max_frames=1, caller="cli", poll_interval_seconds=0.01, heartbeat_interval_seconds=60))


def test_a_one_shot_at_launch_after_an_update_is_the_saved_core_marked_stale(launch):
    builds, saved = launch
    saved(DEMOTE_BUILD_STAMP_MISMATCH)
    frame = _one_shot()
    assert frame["type"] == "hydrate"
    assert frame["core"]["marker"] == "saved"
    assert frame["core"]["parity"]["freshness"]["state"] == "stale"
    assert builds == [], "the launch read waited on a build"
    seeded = holder.held()
    assert seeded is not None and seeded.stale, "the saved core did not seed the resident slot"
    # A second launch read is answered from the seed, not a second parse.
    assert _one_shot()["core"]["marker"] == "saved"
    assert builds == []


@pytest.mark.parametrize("reason", [DEMOTE_CONTRACT_MISMATCH, DEMOTE_HOME_MISMATCH])
def test_a_schema_change_paints_no_saved_core(launch, reason):
    builds, saved = launch
    saved(reason)
    frame = _one_shot()
    assert frame["core"]["marker"] == "built"
    assert builds == ["cli"]
    assert holder.held() is None


def test_a_one_shot_with_no_rebuild_running_builds_rather_than_paint_the_saved_core(launch, monkeypatch):
    builds, saved = launch
    saved(DEMOTE_BUILD_STAMP_MISMATCH)
    monkeypatch.setattr(snapshot_build, "build_in_flight", lambda: False)
    assert _one_shot()["core"]["marker"] == "built"
    assert builds == ["cli"]


def test_the_hub_boot_hydrate_never_takes_the_saved_core_as_its_authority(launch):
    _, saved = launch
    saved(DEMOTE_BUILD_STAMP_MISMATCH)
    holder.seed_saved(_core(7, marker="saved"))
    assert read.answer_hydrate(caller="hub", build_info={}, one_shot=False) is None


def test_a_saved_seed_never_answers_a_wait_for_the_log_end_and_a_full_core_replaces_it(launch):
    holder.seed_saved(_core(7, marker="saved"))
    assert holder.wait_through(7, 0.05) is None
    # A patch frame chaining from the seed's offset is not folded onto it.
    holder.observe({"type": "patch", "base_offset": 7, "watermark": {"event_offset": 8}, "patches": []})
    assert holder.held().offset == 7 and holder.held().stale
    holder.observe({"type": "hydrate", "watermark": {"event_offset": 9}, "core": _core(9, marker="full")})
    replaced = holder.held()
    assert replaced is not None and not replaced.stale and replaced.core["marker"] == "full"
    # And a late saved seed never overwrites the full core.
    assert holder.seed_saved(_core(7, marker="saved")) is False
    assert holder.held().core["marker"] == "full"
