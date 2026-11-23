"""A demote-kind batch is answered by re-reading only the sections it moves, not a
full core (row RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE,
step 5).

Covers ``agent_runtime.resident_core.sections.section_core_for`` through the entry
point the hub drives (``stream_frames`` → ``_full_core_batch_frames``), with the
full build replaced by a refusal so a full core is impossible, and the frame's
core compared with a fresh build at the same offset by ``compare_cores``.
"""

from __future__ import annotations

import pytest

from agent_runtime import resident_core
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.parity import core_event_offset
from agent_runtime.resident_core import sections
from agent_runtime.snapshot.build import _build_snapshot_uncoalesced
from agent_runtime.stream import build as stream_build
from hermes_time import now
from tests.agent_runtime.office_seed import seed_workspace_record, settle_task_activity
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from tests.agent_runtime.test_resident_core_equals_rebuild import (
    _differing_sections,
    _next_content,
    _stream,
    patches_on,  # noqa: F401 -- the fixture, re-used
)


@pytest.fixture
def no_full_build(patches_on, isolate_agent_runtime_root, monkeypatch):  # noqa: F811
    mint_free_floating("profile:reviewer")
    seed_workspace_record("ws_sections_a")
    seed_workspace_record("ws_sections_b")
    resident_core.drop("test_setup")
    monkeypatch.setattr(sections, "resident_core_enabled", lambda: True)
    frames = _stream()
    assert _next_content(frames)["type"] == "hydrate"

    def _refused(*args, **kwargs):
        raise AssertionError("a demote-kind batch paid for a full core")

    monkeypatch.setattr(stream_build, "_build_with_liveness", _refused)
    yield frames
    resident_core.drop("test_teardown")


def _assert_equals_a_fresh_build(frame: dict) -> None:
    assert frame["type"] == "delta"
    fresh = _build_snapshot_uncoalesced()
    assert core_event_offset(fresh) == frame["watermark"]["event_offset"], "compared at the same offset"
    assert _differing_sections(frame["core"], fresh) == []


def test_a_task_activity_batch_re_reads_the_workspace_rows_only(no_full_build):
    frames = no_full_build
    settle_task_activity()
    frame = _next_content(frames)
    _assert_equals_a_fresh_build(frame)
    assert all(row.get("tasks_running") == 0 for row in frame["core"]["workspaces"]), "the control: counts moved"
    assert resident_core.held().offset == frame["watermark"]["event_offset"], "the resident core took the frame"


def _held_with_stale_chat_sections() -> None:
    """Positive control: the held core's chat rows and their accounting are wrong,
    so only a rebuild that rewrites both can match the fresh build."""

    held = resident_core.held()
    parity = held.core["parity"]
    stale = {
        **held.core,
        "persona_chat_history": [{"session_id": "stale"}],
        "parity": {**parity, "completeness": {**parity["completeness"], "persona_chat_history": {"stale": True}}},
    }
    resident_core.observe({"type": "hydrate", "watermark": {"event_offset": held.offset}, "core": stale})


def test_an_unnamed_chat_database_move_re_reads_the_chat_sections_only(no_full_build):
    frames = no_full_build
    _held_with_stale_chat_sections()
    EventLog().append(Event(now(), "state.reconciled", None, None, None, {
        "fingerprint": "test", "source": "stream_watchdog", "families": ["chat_db", "running_work"],
    }))
    _assert_equals_a_fresh_build(_next_content(frames))


def test_an_event_the_table_does_not_name_still_builds_the_full_core(no_full_build):
    frames = no_full_build
    EventLog().append(Event(now(), "workspace.updated", None, None, None, {"change": "renamed"}))
    with pytest.raises(AssertionError, match="paid for a full core"):
        _next_content(frames)
