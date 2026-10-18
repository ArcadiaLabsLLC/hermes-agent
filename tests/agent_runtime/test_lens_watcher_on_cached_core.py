"""A core served from the persisted cache carries the LIVE Lens watcher (``RT-LENS-WATCHER-ON-CACHED-CORE``).

``lens.watcher`` is process memory (``lens.poller.WATCHER``), not a core-cache input. Both serving paths
— the matched consult and the stale-first paint — go through ``core_cache.lane.served_cached_core``,
which overlays the watcher read now.

Killing mutation: drop the ``lens["watcher"] = watcher_state()`` overlay from ``served_cached_core`` →
both tests red (the served core says ``running: False``, the build's).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_runtime import core_cache
from agent_runtime.core_cache.lane import take_stale_first_core
from agent_runtime.lens import poller
from agent_runtime.snapshot import BUILD_ROLE_CACHE, build_snapshot
from tests.agent_runtime.test_core_fingerprint_cache import (  # noqa: F401 - fixtures
    _new_context,
    _rewrite_workspace_name,
    fresh_cache_lane,
    seeded_cache,
    shadow_requests,
)

_SINCE = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _poller_now_running(monkeypatch) -> dict:
    """The poller started AFTER the persisted core was built (it was built with ``running: False``)."""

    monkeypatch.setattr(poller.WATCHER, "running", True)
    monkeypatch.setattr(poller.WATCHER, "since", _SINCE)
    monkeypatch.setattr(poller.WATCHER, "last_tick", _SINCE)
    return poller.WATCHER.to_json()


def test_a_matched_cache_hit_serves_the_live_watcher(isolate_agent_runtime_root, seeded_cache, monkeypatch):
    live = _poller_now_running(monkeypatch)
    _new_context()
    info: dict = {"caller": "probe"}
    core = build_snapshot(build_info=info)

    assert info["role"] == BUILD_ROLE_CACHE and core["parity"]["core_source"] == core_cache.CORE_SOURCE_CACHE
    assert core["lens"]["watcher"] == live


def test_the_stale_first_paint_serves_the_live_watcher(isolate_agent_runtime_root, seeded_cache, monkeypatch):
    _rewrite_workspace_name("beta-two")  # the persisted key no longer matches: a stale-first paint
    live = _poller_now_running(monkeypatch)
    _new_context()
    core = take_stale_first_core(caller="probe")

    assert core is not None and core["parity"]["core_stale"] is True
    assert core["lens"]["watcher"] == live
