"""A finished chat turn leaves ``running_work`` the moment it ends.

Measured live 2026-10-01 (events.81417412 lines 17594-17595, the base serve's
log): ``persona_chat.turn_ended`` at 19:37:28.105Z, and the next frame that
carried ``running_work`` was a full core at 19:37:44.7Z — a 10.2 s build queued
behind another caller's. A turn-end batch can never promote to a patch (the
event is uncovered), so for all of that the stream said the turn was running.

The stream now ships the section ALONE, before the batch's core: one
``running_work`` frame per batch that carries a turn end. These cases replay
that turn's tail order — projected, then turn_ended — against a real journal.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import agent_runtime.stream as stream_mod
from agent_runtime import running_work
from agent_runtime.chat_turn_presence import EVENT_TURN_ENDED, ChatTurnPresence
from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.models import Event
from agent_runtime.stream import stream_frames
from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.stream_liveness_helpers import is_boot_liveness

SESSION = "persona_chat_personainst_dev_agent_8b319ebf_fd4fcfb5e926"
INSTANCE = "personainst_dev_agent_8b319ebf"


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


class _Turn:
    """One chat turn driven through the real journal and the real publisher."""

    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.presence = ChatTurnPresence()

    def start(self) -> None:
        persist_mission_chat_turn(
            session_id=SESSION,
            client_message_id=self.turn_id,
            turn_id=self.turn_id,
            elements=None,
            state="executing",
            write_ahead=True,
            metadata={"persona_instance_id": INSTANCE, "root_chat_session_id": SESSION},
        )
        assert self.presence.publish_started(
            session_id=SESSION,
            client_message_id=self.turn_id,
            turn_id=self.turn_id,
            persona_id="dev",
            persona_instance_id=INSTANCE,
            active_session_id=SESSION,
        )

    def end(self) -> None:
        # Line 17594 then 17595: the projection commits, then the turn leaves
        # the in-flight set.
        persist_mission_chat_turn(
            session_id=SESSION,
            client_message_id=self.turn_id,
            turn_id=self.turn_id,
            elements=None,
            state="projected",
        )
        EventLog().append(
            Event(
                ts=datetime.now(timezone.utc),
                type="persona_chat.projected",
                task_id=None,
                run_id=None,
                persona_id="dev",
                payload={"persona_instance_id": INSTANCE, "root_chat_session_id": SESSION, "turn_id": self.turn_id},
                session_id=SESSION,
                turn_id=self.turn_id,
            )
        )
        assert self.presence.publish_ended()


def _chat_turn_ids(section: dict) -> list[str]:
    return [row["work_id"] for row in section.get("rows") or [] if row.get("kind") == "chat_turn"]


def _content(frames):
    for frame in frames:
        if not is_boot_liveness(frame):
            yield frame


class _BuildCounter:
    def __init__(self, monkeypatch):
        self.calls = 0
        real = stream_mod.build_snapshot

        def counting(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)

        patch_where_bound(monkeypatch, stream_mod, "build_snapshot", counting)


def _stream(max_frames: int):
    return _content(
        stream_frames(
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=60,
            delta_debounce_seconds=0.05,
            max_frames=max_frames,
        )
    )


def test_running_work_is_empty_right_after_turn_ended(isolate_agent_runtime_root, home, monkeypatch):
    builds = _BuildCounter(monkeypatch)
    turn = _Turn("agent-chat-send-be095523")
    turn.start()
    frames = _stream(max_frames=2)

    hydrate = next(frames)
    assert hydrate["type"] == "hydrate"
    # Positive control for the empty section below: the fixture really puts
    # the turn in running_work, and the core says so.
    assert _chat_turn_ids(hydrate["core"]["running_work"]) == ["chat_turn:agent-chat-send-be095523"]
    builds_before = builds.calls

    turn.end()
    section = next(frames)

    assert section["type"] == "running_work"
    assert _chat_turn_ids(section["running_work"]) == []
    # It is the section, read without a core build: none has run since the
    # hydrate, so this frame did not wait on one.
    assert builds.calls == builds_before
    assert "core" not in section and "watermark" not in section
    ended_offset = max(
        offset for offset, event in EventLog().iter_from_offset(0) if event.type == EVENT_TURN_ENDED
    )
    assert section["as_of_offset"] >= ended_offset

    # The batch's own core still follows, at the same position, and agrees.
    delta = next(frames)
    assert delta["type"] == "delta"
    assert delta["watermark"]["event_offset"] == section["as_of_offset"]
    assert _chat_turn_ids(delta["core"]["running_work"]) == []


def test_a_batch_without_a_turn_end_ships_no_section_frame(isolate_agent_runtime_root, home):
    """No publish storm: the section rides turn ends only."""

    turn = _Turn("turn-quiet")
    turn.start()
    frames = _stream(max_frames=2)
    assert next(frames)["type"] == "hydrate"

    EventLog().append(
        Event(
            ts=datetime.now(timezone.utc),
            type="state.reconciled",
            task_id=None,
            run_id=None,
            persona_id=None,
            payload={"fingerprint": "quiet"},
        )
    )
    assert next(frames)["type"] == "delta"


def test_two_turns_ending_in_one_batch_cost_one_section_frame(isolate_agent_runtime_root, home):
    first, second = _Turn("turn-a"), _Turn("turn-b")
    first.start()
    second.start()
    frames = _stream(max_frames=2)
    hydrate = next(frames)
    assert sorted(_chat_turn_ids(hydrate["core"]["running_work"])) == ["chat_turn:turn-a", "chat_turn:turn-b"]

    first.end()
    second.end()
    seen = [next(frames), next(frames)]

    assert [frame["type"] for frame in seen] == ["running_work", "delta"]
    assert _chat_turn_ids(seen[0]["running_work"]) == []
    assert len(seen[1]["events"]) >= 4


def test_an_unreadable_section_ships_nothing_and_the_core_still_follows(
    isolate_agent_runtime_root, home, monkeypatch
):
    turn = _Turn("turn-broken")
    turn.start()

    def _boom():
        raise RuntimeError("store unreadable")

    frames = _stream(max_frames=2)
    assert next(frames)["type"] == "hydrate"
    monkeypatch.setattr(running_work, "build_running_work", _boom)
    turn.end()
    assert next(frames)["type"] == "delta"


def test_the_office_lane_does_not_resync_on_a_section_frame():
    """One resync per finished turn would restart the shared producer each time."""

    from agent_runtime.serve_office_subscriptions import office_patch_sink

    sent: list[dict] = []
    sink = office_patch_sink(workspace_id="ws_main", baseline_offset=10, emit=sent.append)
    sink({"type": "running_work", "schema_version": 1, "as_of_offset": 50, "running_work": {"rows": []}})
    assert sent == []
    # Positive control: the same frame under a type the sink was never taught
    # takes the unknown-type resync, so the silence above is the teaching.
    sink({"type": "running_work_v9", "schema_version": 1, "as_of_offset": 50, "running_work": {"rows": []}})
    assert [message["params"]["reason"] for message in sent] == ["unknown_frame_type"]
