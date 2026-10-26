"""``DiscussionService.bindings``' per-run decision, split out of it (FH-LEGIBILITY-DISCUSSION-BINDINGS-GREW).

The crash repair — an ``ending`` run whose room is already disbanded is ended, not bound — had no
test reaching it: replacing ``_room_disbanded`` with ``False`` left the 46 binding tests green. These
drive the two helpers directly with fakes for the stores they read.
"""
from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.discussions.service import DiscussionService
from gateway import hosted_rooms as rooms


def _service(*, room=None, attempts=(), initialized=None):
    ended: list[str] = []

    def _room(run, include_ended=False):
        if room is None:
            raise rooms.RoomNotFoundError(run["run_id"])
        return room

    fake = SimpleNamespace(
        state=SimpleNamespace(room=_room, initialize=lambda run: (initialized if initialized is not None else []).append(run["run_id"])),
        runs=SimpleNamespace(end=ended.append),
        attempts=SimpleNamespace(rows=lambda run_id: list(attempts)),
    )
    fake._room_disbanded = lambda run: DiscussionService._room_disbanded(fake, run)
    return fake, ended


def _run(phase, **initial):
    return {"run_id": "run_1", "phase": phase, "initial": initial}


def test_an_ending_run_whose_room_is_disbanded_is_ended_not_bound():
    fake, ended = _service(room={"disbanded_at": "2026-10-25T00:00:00Z"})
    assert DiscussionService._bring_to_hosted(fake, _run("ending")) is False
    assert ended == ["run_1"]


def test_an_ending_run_with_no_room_and_no_attempts_is_ended():
    fake, ended = _service(room=None, attempts=())
    assert DiscussionService._bring_to_hosted(fake, _run("ending")) is False
    assert ended == ["run_1"]


def test_an_ending_run_whose_room_still_stands_stays_bound():
    """Positive control: the same run, the room not disbanded (or attempts on record) — bound, not ended."""
    for fake, ended in (_service(room={"disbanded_at": None}), _service(room=None, attempts=("a",))):
        assert DiscussionService._bring_to_hosted(fake, _run("ending")) is True
        assert ended == []


def test_a_pending_compare_import_is_not_bound_and_an_initializing_run_is_initialized():
    initialized: list[str] = []
    fake, _ended = _service(initialized=initialized)
    assert DiscussionService._bring_to_hosted(fake, _run("open", compare_import={"state": "pending"})) is False
    assert DiscussionService._bring_to_hosted(fake, _run("initializing")) is True
    assert initialized == ["run_1"]
