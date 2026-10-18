"""The Lens fold rides the push lane: the snapshot's top-level ``lens`` section.

Owner ruling 2026-10-18: one top-level
``lens`` section, the method lane's ``runtime.lens.fold`` answer, landed with the
launcher's fold painter.

Gates and their killing mutations:

* the built frame carries ``lens`` equal to the fold — killed by dropping the
  ``("lens", ...)`` phase from ``SECTIONS`` (AttributeError on ``lens_section``)
  or the ``"lens"`` key from ``frame``;
* a worker build carries the SERVE's watcher — killed by making
  ``watcher_state`` ignore ``_RECORDED_WATCHER``;
* a Lens write moves the core-cache key, so a cached core is never served with
  a stale fold — killed by dropping ``lens_store`` from ``INPUT_CLASSES``.
"""

from __future__ import annotations

from agent_runtime import core_cache
from agent_runtime.lens.poller import WATCHER
from agent_runtime.lens.snapshot_fold import lens_fold, recorded_watcher
from agent_runtime.lens.store import LensStore, MonitorState
from agent_runtime.snapshot import build_snapshot


def _enable_monitor() -> LensStore:
    manifest = {"version": 1, "monitor_id": "status",
                "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                           "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
                "rules": [], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
                "persona_id": None}
    store = LensStore()
    store.create(manifest)
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    return store


def test_the_snapshot_carries_the_lens_fold_as_a_top_level_section(isolate_agent_runtime_root):
    _enable_monitor()

    snapshot = build_snapshot()

    assert snapshot["lens"] == lens_fold()
    assert snapshot["lens"]["monitors_enabled"] == 1
    [latest] = snapshot["lens"]["latest"]
    assert (latest["monitor_id"], latest["feed_id"], latest["gap"], latest["reason"]) == (
        "status", "api", True, "never_read")


def test_a_home_without_lens_carries_the_empty_fold_and_creates_no_store(isolate_agent_runtime_root):
    snapshot = build_snapshot()

    assert (snapshot["lens"]["monitors_enabled"], snapshot["lens"]["open_episodes"],
            snapshot["lens"]["latest"]) == (0, [], [])
    assert not LensStore().exists()


def test_a_worker_build_folds_the_serve_watcher():
    serve = {"running": True, "since_ms": 1_000, "last_tick_ms": 2_000}

    with recorded_watcher(serve):
        assert lens_fold()["watcher"] == serve
    with recorded_watcher({"running": True}):
        assert lens_fold()["watcher"] == WATCHER.to_json()


def test_a_lens_write_moves_the_core_cache_key(isolate_agent_runtime_root):
    before = core_cache.build_input_fingerprint()
    assert before is not None

    _enable_monitor()

    after = core_cache.build_input_fingerprint()
    assert after is not None and after.digest != before.digest
