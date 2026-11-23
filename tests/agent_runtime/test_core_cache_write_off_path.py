"""A led build answers before its cache copy reaches the disk (row
RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK, folded into
RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE step 6).

Covers ``agent_runtime.core_cache.write_queue.write_back_off_path`` through
``agent_runtime.snapshot.build_snapshot`` (the leader's ``_lead_build_now``), with
``persist._stage_and_land`` held shut so "the build returned" and "the copy landed"
are two observable moments, and ``persist.restat_self_perturbed`` recorded
so the IC-2 restat is pinned to the build's own thread. The build thread re-keys from
the audited classes alone; the whole walk behind ``foreign_moved=`` runs on the writer
thread; and the coalescer's last rider takes the release's copy without a second one.
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
    real_restat = persist.restat_self_perturbed

    def _held_land(*args, **kwargs):
        gate.wait(timeout=25)
        landed.append(real_land(*args, **kwargs))
        return landed[-1]

    def _recorded_restat(key):
        restat_threads.append(threading.get_ident())
        return real_restat(key)

    monkeypatch.setattr(persist, "_stage_and_land", _held_land)
    monkeypatch.setattr(persist, "restat_self_perturbed", _recorded_restat)
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


def test_the_build_thread_re_keys_from_the_audited_classes_alone(isolate_agent_runtime_root, monkeypatch):
    """The re-key's whole second walk left the build thread: it counts ``foreign_moved=`` at the landing."""

    from agent_runtime.core_cache import restat

    walks: list[int] = []
    real_walk = restat.build_input_fingerprint

    def _recorded_walk():
        walks.append(threading.get_ident())
        return real_walk()

    monkeypatch.setattr(restat, "build_input_fingerprint", _recorded_walk)
    build_thread: list[int] = []

    def _build():
        build_thread.append(threading.get_ident())
        build_snapshot(build_info={"caller": "probe"})

    worker = threading.Thread(target=_build, daemon=True)
    worker.start()
    worker.join(timeout=30)
    assert drain_write_backs(timeout_s=60)
    assert build_thread and build_thread[0] not in walks, "the build thread walked the whole closure after its build"
    assert len(walks) == 1, f"the control: the landing counted foreign moves with one whole walk, got {len(walks)}"


def test_the_last_rider_takes_the_release_copy_without_a_second(isolate_agent_runtime_root, monkeypatch):
    """A leader and ONE rider: the release copies the core once and the rider keeps that copy."""

    import copy as copy_module

    from agent_runtime.snapshot import build as snapshot_build
    from agent_runtime.snapshot_worker import executor

    copies: list[int] = []

    class _CountingCopy:
        @staticmethod
        def deepcopy(value):
            copies.append(1)
            return copy_module.deepcopy(value)

    monkeypatch.setattr(snapshot_build, "copy", _CountingCopy)
    release = threading.Event()
    started = threading.Event()
    real_execute = executor.execute_build

    def _held_execute(*args, **kwargs):
        started.set()
        release.wait(timeout=25)
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(executor, "execute_build", _held_execute)
    results: dict[str, dict] = {}
    leader = threading.Thread(
        target=lambda: results.setdefault("leader", build_snapshot(build_info={"caller": "leader"})), daemon=True
    )
    leader.start()
    assert started.wait(timeout=25)
    rider_info: dict = {"caller": "rider"}
    rider = threading.Thread(
        target=lambda: results.setdefault("rider", build_snapshot(accept_inflight=True, build_info=rider_info)),
        daemon=True,
    )
    rider.start()
    deadline = threading.Event()
    while snapshot_build._build_coalesce_state["waiters"] == 0 and not deadline.wait(0.02):
        pass
    release.set()
    leader.join(timeout=30)
    rider.join(timeout=30)
    drain_write_backs(timeout_s=60)
    assert rider_info.get("role") == "rode", rider_info
    assert results["rider"] is not results["leader"], "the rider shares no dict with the leader"
    assert len(copies) == 1, f"the core was deep-copied {len(copies)} times for one rider"
