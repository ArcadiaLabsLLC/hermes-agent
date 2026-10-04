"""The build sweep with a fake clock (plan ``build-running-work-2026-10-04.md`` §6, §7, row H7).

Owner call 1: agent-started and announced builds that stall past the threshold are ENDED and
their owner notified; a DETECTED build is MARKED only — never ended by hermes. Every ending is
one ``build.ended`` event on the transition, and a known outcome feeds the history median.
"""

from __future__ import annotations

import os
import sys
import threading
import types

import pytest

from agent_runtime.builds import history, sweep
from agent_runtime.builds.registry import new_record, write_record
from agent_runtime.builds.vocabulary import REGISTRY_DIR_ENV

NOW = 1_759_590_720.0


class _Log:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def _row(work_id, source, *, status="running", quiet=0.0, outcome=None, elapsed=60):
    return {"work_id": work_id, "source": source, "status": status, "seconds_since_progress": quiet,
            "outcome": outcome, "elapsed_seconds": elapsed, "project": {"root": "C:/src/launcher"},
            "toolchain": "flutter", "target": "windows", "mode": "release", "owner": {}, "label": work_id}


def _sweep(tmp_path, frames, ended=None):
    log, calls = _Log(), []
    frames = iter(frames)

    def ender(row):
        calls.append(row["work_id"])
        return True

    built = sweep.BuildSweep(rows=lambda now: next(frames), ender=ender, event_log=log,
                             history_dir=lambda: tmp_path / "builds", stall_fail_seconds=900)
    return built, log, calls


def test_a_detected_build_past_the_threshold_is_marked_and_never_ended(tmp_path):
    detected = _row("build:detected:7-11", "detected", status="stalled", quiet=1200)
    built, log, calls = _sweep(tmp_path, [[detected], [detected]])
    first = built.tick(NOW)
    second = built.tick(NOW + 30)
    assert calls == [] and log.events == []
    assert first.marked == second.marked == ["build:detected:7-11"]
    # Positive control: the SAME row from the agent source is ended.
    agent = _row("build:agent:sess", "agent", status="stalled", quiet=1200)
    built, log, calls = _sweep(tmp_path, [[agent]])
    assert built.tick(NOW).stall_failed == ["build:agent:sess"] and calls == ["build:agent:sess"]
    [event] = log.events
    assert (event.type, event.payload["outcome"]) == ("build.ended", "stalled")


def test_a_build_under_the_threshold_or_queued_is_never_ended(tmp_path):
    rows = [_row("build:agent:quiet", "agent", status="stalled", quiet=600),
            _row("build:announced:qb-queued", "announced", status="running", quiet=None)]
    built, log, calls = _sweep(tmp_path, [rows])
    assert built.tick(NOW).stall_failed == [] and calls == []


def test_an_ending_is_one_event_on_the_transition_and_feeds_history(tmp_path):
    running = _row("build:announced:qb-1", "announced")
    done = _row("build:announced:qb-1", "announced", status="completed", outcome="succeeded", elapsed=330)
    built, log, _calls = _sweep(tmp_path, [[running], [done], [done]])
    built.tick(NOW)
    built.tick(NOW + 30)
    built.tick(NOW + 60)
    assert [e.payload["outcome"] for e in log.events] == ["succeeded"]
    assert history.estimate(tmp_path / "builds", project_root="C:/src/launcher", toolchain="flutter",
                            target="windows", mode="release") == (330_000, 1)


def test_a_build_that_leaves_the_projection_ends_with_what_was_observed(tmp_path):
    built, log, _calls = _sweep(tmp_path, [[_row("build:detected:9-1", "detected")], []])
    built.tick(NOW)
    built.tick(NOW + 30)
    [event] = log.events
    assert event.payload["outcome"] is None and event.payload["ended_reason"] == "process_exited"


def test_the_median_rests_on_the_last_five_succeeded_builds(tmp_path):
    directory = tmp_path / "builds"
    for ms in (10, 100, 200, 300, 400, 500):
        history.append(directory, project_root="C:/src/x", toolchain="flutter", target="windows", mode="release",
                       duration_ms=ms, outcome="succeeded", ended_at=NOW)
    history.append(directory, project_root="C:/src/x", toolchain="flutter", target="windows", mode="release",
                   duration_ms=99_999, outcome="failed", ended_at=NOW)
    assert history.estimate(directory, project_root="C:/src/x", toolchain="flutter", target="windows",
                            mode="release") == (300, 5)
    assert history.estimate(directory, project_root="C:/src/y", toolchain="flutter", target="windows",
                            mode="release") == (None, 0)
    assert "C:/src/x" not in (directory / "history.jsonl").read_text(encoding="utf-8")


def test_an_agent_stall_kill_wakes_its_owner_through_the_completion_queue(monkeypatch):
    killed = []
    session = types.SimpleNamespace(notify_on_complete=False)
    registry = types.SimpleNamespace(get=lambda sid: session if sid == "sess" else None,
                                     kill_process=lambda sid, **kw: killed.append((sid, kw)))
    monkeypatch.setitem(sys.modules, "tools.process_registry", types.SimpleNamespace(process_registry=registry))
    assert sweep._end_agent({"work_id": "build:agent:sess"}) is True
    assert session.notify_on_complete is True
    assert killed == [("sess", {"source": "harness.build_stall", "consume_output": False})]


def test_an_announced_request_mode_build_is_asked_to_stop(tmp_path, monkeypatch):
    directory = tmp_path / "builds"
    monkeypatch.setattr(sweep, "registry_home", lambda: directory)
    write_record(directory, new_record(job_id="qb-9", started_at=NOW - 60, controls={"stop": "request", "restart": "none"}))
    row = {"work_id": "build:announced:qb-9", "source": "announced", "announcement": {"record": "qb-9.json"}}
    assert sweep._default_ender(row) is True
    assert (directory / "qb-9.stop").is_file()
    # Positive control: a writer that declines (`none`) is not stopped.
    write_record(directory, new_record(job_id="qb-10", started_at=NOW - 60, controls={"stop": "none", "restart": "none"}))
    assert sweep._default_ender({"work_id": "build:announced:qb-10", "source": "announced",
                                 "announcement": {"record": "qb-10.json"}}) is False


def test_boot_exports_the_registry_dir_and_sweeps_expired_records(tmp_path, monkeypatch):
    directory = tmp_path / "builds"
    monkeypatch.setattr(sweep, "registry_home", lambda: directory)
    monkeypatch.setattr(sweep, "_THREAD", threading.Thread(target=lambda: None))
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.delenv(REGISTRY_DIR_ENV, raising=False)
    write_record(directory, new_record(job_id="old", started_at=1.0, expires_at=2.0))
    answer = sweep.boot_builds()
    assert os.environ[REGISTRY_DIR_ENV] == str(directory)
    assert answer["gc_removed"] == 1 and not (directory / "old.json").exists()
    from agent_runtime.builds import detect

    assert detect.detection_enabled()
    monkeypatch.setattr(detect, "_ENABLED", False)


@pytest.mark.parametrize("source", ["agent", "announced"])
def test_a_stall_ended_build_is_not_ended_twice(tmp_path, source):
    stalled = _row(f"build:{source}:x", source, status="stalled", quiet=1200)
    stopped = _row(f"build:{source}:x", source, status="error", outcome="stopped")
    built, log, calls = _sweep(tmp_path, [[stalled], [stalled], [stopped], []])
    for offset in (0, 30, 60, 90):
        built.tick(NOW + offset)
    assert calls == [f"build:{source}:x"]
    assert [e.payload["outcome"] for e in log.events] == ["stalled"]


def test_the_ending_lands_in_the_real_event_log(tmp_path):
    """``EventLog.append`` refuses an unregistered type: ``build.ended`` is in the contract registry."""

    from agent_runtime.events import EventLog

    frames = iter([[_row("build:announced:qb-r", "announced")],
                   [_row("build:announced:qb-r", "announced", status="error", outcome="failed")]])
    built = sweep.BuildSweep(rows=lambda now: next(frames), ender=lambda row: True,
                             history_dir=lambda: tmp_path / "builds")
    built.tick(NOW)
    built.tick(NOW + 30)
    [event] = [e for e in EventLog().tail(20) if e.type == "build.ended"]
    assert (event.payload["work_id"], event.payload["outcome"]) == ("build:announced:qb-r", "failed")
