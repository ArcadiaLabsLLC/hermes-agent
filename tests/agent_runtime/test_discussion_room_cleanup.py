"""The discussion start-up clean-up (owner ruling 2026-10-15).

RT-DISCUSSION-RETENTION-PIN-LEAK: a crash between the End's retention pin and its
disband leaves a pin on a live room that no prune lane reclaims; start-up clears it.
RT-DISCUSSION-RUN-END-DISBAND: a typed disband refusal no longer holds an End in
``ending`` — the run ends (seats released) with its live room marked, and the next
start-up retries the disband.
"""
from __future__ import annotations

import sqlite3

import pytest

from agent_runtime.discussions.room_state import DISBAND_DEFERRED
from agent_runtime.discussions.service import DiscussionService
from gateway import hosted_room_history_pins as pins
from gateway import hosted_rooms
from tests.agent_runtime.test_discussion_runtime import (
    ExecutionContext, begin, command, room_timings, settled, wait_until)

pytestmark = pytest.mark.timeout(180)


class _Crash(BaseException):
    """The process dying mid-End: no ``except Exception`` handler sees it."""


def _service(tmp_path, *, start_worker: bool = True) -> DiscussionService:
    service = DiscussionService(ExecutionContext(tmp_path), **room_timings())
    if not start_worker:
        service.runtime.start = lambda: None
    service.start()
    return service


def _settled_run(service):
    run = begin(service)
    wait_until(lambda: settled(service, run))
    return run


def _room(service, run_id):
    return hosted_rooms.room_state(service.db_path, room_id=run_id, include_disbanded=True)


def test_a_pin_left_on_a_live_room_by_a_crash_is_cleared_at_start_up(tmp_path, monkeypatch):
    service = _service(tmp_path)
    try:
        run = _settled_run(service)

        def crash(*_args, **_kwargs):
            raise _Crash()

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(hosted_rooms, "disband_room", crash)
            with pytest.raises(_Crash):
                command(service, run, "end")
        assert pins.live_room_pins(service.db_path) == [run["run_id"]]
    finally:
        service.close()

    restarted = _service(tmp_path, start_worker=False)
    try:
        assert pins.live_room_pins(restarted.db_path) == []
    finally:
        restarted.close()

    # The pending End still completes on the next boot, and retains its transcript.
    resumed = _service(tmp_path)
    try:
        wait_until(lambda: resumed.runs.get(run["run_id"])["phase"] == "ended")
        assert _room(resumed, run["run_id"]).get("disbanded_at") is not None
        assert pins.live_room_pins(resumed.db_path) == []
    finally:
        resumed.close()


def test_a_refused_disband_ends_the_run_and_start_up_retries_it(tmp_path, monkeypatch):
    service = _service(tmp_path)
    try:
        run = _settled_run(service)

        def refuse(*_args, **_kwargs):
            raise hosted_rooms.AuthorityConflictError("stale hosted room authority")

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(hosted_rooms, "disband_room", refuse)
            command(service, run, "end")
            ended = wait_until(
                lambda: (r if (r := service.runs.get(run["run_id"]))["phase"] == "ended" else None), 15)
        assert ended["error"] == DISBAND_DEFERRED
        with sqlite3.connect(service.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM mc_discussion_instance_claims WHERE run_id=?",
                                (run["run_id"],)).fetchone()[0] == 0
        assert _room(service, run["run_id"]).get("disbanded_at") is None
        assert pins.live_room_pins(service.db_path) == []
    finally:
        service.close()

    restarted = _service(tmp_path, start_worker=False)
    try:
        assert _room(restarted, run["run_id"]).get("disbanded_at") is not None
        assert restarted.runs.get(run["run_id"])["error"] is None
        with sqlite3.connect(restarted.db_path) as conn:
            assert conn.execute("SELECT 1 FROM hosted_room_history_pins WHERE room_id=?",
                                (run["run_id"],)).fetchone() is not None
    finally:
        restarted.close()
