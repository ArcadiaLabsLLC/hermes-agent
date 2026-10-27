"""A batch made only of terminal-process presence rides ONE sequenced ``running_work`` frame.

Row ``RT-EMIT-RUNNING-WORK-CHAT``, plan ``docs/agent-runtime-harness/archive/p10-turn-2026-10-19.md``
§2.4 tests 4-6. A room where every subscriber declared the sixth token
(``running_work_section``) is handed the ``running_work`` section carrying the
batch's ``watermark`` / ``base_offset`` instead of a full core; a room that did
not keeps the un-sequenced ``as_of_offset`` overlay and today's demote core.
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC

import pytest

import agent_runtime.stream as stream_mod
from agent_runtime import running_work
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.patch_coverage import HISTORICAL_FOLD_ENTITIES, RUNNING_WORK_SECTION_CAPABILITY
from agent_runtime.running_work import process_presence
from agent_runtime.state_patches import PATCH_OP_UPSERT, STATE_PATCHED_EVENT_TYPE
from agent_runtime.stream import stream_frames
from agent_runtime.stream.build import _batch_frames_with_liveness
from agent_runtime.stream.frames import (
    WATCHDOG_SOURCE,
    batch_changes_chat_turn_presence,
    batch_changes_running_work_presence,
    batch_is_running_work_only,
)
from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.stream_liveness_helpers import is_boot_liveness

SILENT = sorted(HISTORICAL_FOLD_ENTITIES)
DECLARING = sorted(HISTORICAL_FOLD_ENTITIES | {RUNNING_WORK_SECTION_CAPABILITY})


@pytest.fixture
def home(tmp_path, monkeypatch):
    head = tmp_path / "home"
    head.mkdir(parents=True, exist_ok=True)
    for module in (
        running_work.rows,
        running_work.ownership,
        running_work.lanes_process,
        running_work.lanes_chat,
        running_work.surface,
    ):
        if "_head_home" in vars(module):
            monkeypatch.setattr(module, "_head_home", lambda: (head, "test_home"))
    return head


class _Session:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.pid = 4242
        self.command = "sleep 30"
        self.owner_task_id = ""
        self.started_at = 1_760_000_000.0
        self.exit_code = 0
        self.completion_reason = "exited"


def _batch_since(offset: int) -> list[tuple[int, Event]]:
    return [(int(o), e) for o, e in EventLog().iter_from_offset(offset)]


def _log_end() -> int:
    batch = _batch_since(0)
    return batch[-1][0] if batch else 0


def _process_batch(sid: str = "proc_section") -> tuple[int, list[tuple[int, Event]]]:
    start = _log_end()
    assert process_presence._on_lifecycle("started", _Session(sid))
    assert process_presence._on_lifecycle("finished", _Session(sid))
    batch = _batch_since(start)
    assert [event.type for _, event in batch] == [
        process_presence.EVENT_PROCESS_STARTED,
        process_presence.EVENT_PROCESS_ENDED,
    ]
    return start, batch


class _BuildCounter:
    def __init__(self, monkeypatch):
        self.calls = 0
        real = stream_mod.build_snapshot

        def counting(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)

        patch_where_bound(monkeypatch, stream_mod, "build_snapshot", counting)


def _gate(batch, *, start, accepted):
    return [
        frame
        for frame in _batch_frames_with_liveness(
            batch,
            base_offset=start,
            delta_patches=True,
            resync=False,
            heartbeat_interval_seconds=60,
            fold_entities=accepted,
        )
        if frame.get("type") != "heartbeat"
    ]


def _patched(offset: int) -> tuple[int, Event]:
    return (
        offset,
        Event(
            ts=datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC),
            type=STATE_PATCHED_EVENT_TYPE,
            task_id=None,
            run_id=None,
            persona_id=None,
            payload={"entity": "persona_instance", "id": "personainst_a", "op": PATCH_OP_UPSERT, "changed": {"display_name": "A"}},
        ),
    )


# ── test 4: the declaring room gets ONE sequenced section frame ──────────────


def test_a_declaring_room_gets_one_sequenced_section_and_no_core(isolate_agent_runtime_root, home, monkeypatch):
    """Killing mutation: drop the token gate in ``stream.build._turn_batch_frames``
    → the UNDECLARED room receives a sequenced ``running_work`` frame it cannot fold."""

    builds = _BuildCounter(monkeypatch)
    start, batch = _process_batch()

    frames = _gate(batch, start=start, accepted=DECLARING)
    assert [frame["type"] for frame in frames] == ["running_work"]
    section = frames[0]
    assert section["watermark"]["event_offset"] == batch[-1][0]
    assert section["base_offset"] == start
    assert "as_of_offset" not in section
    assert section["coalesced_count"] == 2
    assert isinstance(section["running_work"]["rows"], list)
    assert builds.calls == 0

    # The undeclared room: today's demote core, never a sequenced section.
    silent = _gate(batch, start=start, accepted=SILENT)
    assert [frame["type"] for frame in silent] == ["delta"]
    assert builds.calls == 1


def test_a_declaring_stream_ships_the_overlay_then_the_sequenced_section(isolate_agent_runtime_root, home, monkeypatch):
    builds = _BuildCounter(monkeypatch)
    patch_where_bound(monkeypatch, stream_mod, "delta_patches_enabled", lambda config=None: True)
    frames = (
        frame
        for frame in stream_frames(
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=60,
            delta_debounce_seconds=0.05,
            max_frames=3,
            fold_entities=DECLARING,
        )
        if not is_boot_liveness(frame)
    )
    hydrate = next(frames)
    assert hydrate["type"] == "hydrate"
    held = hydrate["watermark"]["event_offset"]
    builds_before = builds.calls
    process_presence._on_lifecycle("started", _Session("proc_stream"))
    overlay = next(frames)
    assert overlay["type"] == "running_work"
    assert "watermark" not in overlay
    sequenced = next(frames)
    assert sequenced["type"] == "running_work"
    assert sequenced["base_offset"] == held
    assert sequenced["watermark"]["event_offset"] > held
    assert builds.calls == builds_before


# ── test 5: without the token, the overlay then today's demote ───────────────


def test_an_undeclared_stream_gets_the_unsequenced_overlay_then_the_core(isolate_agent_runtime_root, home, monkeypatch):
    """Killing mutation: the overlay carries a ``watermark`` instead of
    ``as_of_offset`` → it moves the undeclared client's sequence."""

    patch_where_bound(monkeypatch, stream_mod, "delta_patches_enabled", lambda config=None: True)
    frames = (
        frame
        for frame in stream_frames(
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=60,
            delta_debounce_seconds=0.05,
            max_frames=3,
            fold_entities=SILENT,
        )
        if not is_boot_liveness(frame)
    )
    hydrate = next(frames)
    assert hydrate["type"] == "hydrate"
    process_presence._on_lifecycle("started", _Session("proc_silent"))
    overlay = next(frames)
    assert overlay["type"] == "running_work"
    assert "watermark" not in overlay
    assert "base_offset" not in overlay
    assert isinstance(overlay["as_of_offset"], int)
    core = next(frames)
    assert core["type"] == "delta"


# ── test 6: the predicate is ALL, not ANY ────────────────────────────────────


def test_a_mixed_batch_is_not_running_work_only(isolate_agent_runtime_root, home):
    """Killing mutation: ``any`` for ``all`` in ``batch_is_running_work_only``
    → the office row's ``state.patched`` rides a section frame and is lost."""

    start, batch = _process_batch("proc_mixed")
    mixed = [batch[0], _patched(batch[-1][0] + 1)]
    assert batch_is_running_work_only(batch) is True
    assert batch_is_running_work_only(mixed) is False
    frames = _gate(mixed, start=start, accepted=DECLARING)
    assert "running_work" not in [frame["type"] for frame in frames]


def test_the_predicate_admits_a_running_work_only_reconcile_and_nothing_else():
    def reconcile(families):
        return Event(
            ts=datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC),
            type="state.reconciled",
            task_id=None,
            run_id=None,
            persona_id=None,
            payload={"source": WATCHDOG_SOURCE, "fingerprint": "f", "families": families},
        )

    assert batch_is_running_work_only([(1, reconcile(["running_work"]))]) is True
    assert batch_is_running_work_only([(1, reconcile(["running_work", "chat_db"]))]) is False
    assert batch_is_running_work_only([]) is False


def test_presence_covers_both_pairs_and_the_old_name_is_an_alias(isolate_agent_runtime_root, home):
    _start, batch = _process_batch("proc_alias")
    assert batch_changes_running_work_presence(batch) is True
    assert batch_changes_chat_turn_presence is batch_changes_running_work_presence
    assert batch_changes_running_work_presence([_patched(1)]) is False
