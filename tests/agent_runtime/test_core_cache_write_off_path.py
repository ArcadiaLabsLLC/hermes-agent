"""A led build answers before its cache copy reaches the disk (row
RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK, folded into
RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE step 6).

Covers ``agent_runtime.core_cache.write_queue.write_back_off_path`` through
``agent_runtime.snapshot.build_snapshot`` (the leader's ``_lead_build_now``), with
``persist._stage_and_land`` held shut so "the build returned" and "the copy landed"
are two observable moments, and ``persist._restat_on_post_build_reality`` recorded
so the IC-2 restat is pinned to the build's own thread.
"""

from __future__ import annotations

import threading

from agent_runtime.core_cache import persist
from agent_runtime.core_cache.write_queue import drain_write_backs
from agent_runtime.snapshot import build_snapshot


def test_a_led_build_answers_before_its_cache_copy_lands(isolate_agent_runtime_root, monkeypatch):
    gate = threading.Event()
    landed: list[bool] = []
    restat_threads: list[int] = []
    real_land = persist._stage_and_land
    real_restat = persist._restat_on_post_build_reality

    def _held_land(*args, **kwargs):
        gate.wait(timeout=25)
        landed.append(real_land(*args, **kwargs))
        return landed[-1]

    def _recorded_restat(key):
        restat_threads.append(threading.get_ident())
        return real_restat(key)

    monkeypatch.setattr(persist, "_stage_and_land", _held_land)
    monkeypatch.setattr(persist, "_restat_on_post_build_reality", _recorded_restat)
    build_thread: list[int] = []
    answered = threading.Event()

    def _build():
        build_thread.append(threading.get_ident())
        build_snapshot(build_info={"caller": "probe"})
        answered.set()

    threading.Thread(target=_build, daemon=True).start()
    try:
        assert answered.wait(timeout=20), "the build waited for its cache copy to reach the disk"
        assert landed == [], "the control: the copy had not landed when the build answered"
        assert restat_threads == build_thread, "the IC-2 restat ran on the build's own thread, right after it"
    finally:
        gate.set()
    assert drain_write_backs(timeout_s=60)
    assert landed == [True], "the copy still lands, on the writer thread"
