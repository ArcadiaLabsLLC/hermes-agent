"""The ``persona_chat_turn.json`` stream golden (plan h-turn1 §2 C1), built for
``generate_agent_runtime_stream_fixtures.py`` — kept here so that generator stays under
the downstream size ceiling."""

from __future__ import annotations


def build_persona_chat_turn_frame(
    owner_hydrate: dict, persona_id: str, instance_id: str, chat_session: str
) -> dict:
    """One ``persona_chat_turn`` frame for the seeded instance's chat root.

    Read against the SAME seeded store as ``owner_hydrate`` and right after it,
    so the frame's ``operator_channel``, ``persona_instance`` and
    ``running_work`` are that core's rows for ``instance_id`` — the
    C0.3 equality, pinned in bytes by ``test_stream_contract_fixture.py``. The
    root has no SessionDB row in this store, so its history is ``null`` with
    ``omitted: false`` (not a candidate at all, exactly as the core has it).

    The batch is ONE ``persona_chat.turn_started`` built in memory and NOT
    appended: appending would move the log under the frames built after this
    one. Its offset is the owner hydrate's plus one, a fixture position — the
    frame's contract is ``base_offset`` = the held watermark and
    ``watermark.event_offset`` past it, not any particular byte.
    """

    from datetime import datetime, timezone

    from agent_runtime.models import Event
    from agent_runtime.stream import batch_turn_roots, persona_chat_turn_frames

    held = int(owner_hydrate["watermark"]["event_offset"])
    event = Event(
        ts=datetime(2026, 7, 16, 12, 0, 2, tzinfo=timezone.utc),
        type="persona_chat.turn_started",
        task_id=None,
        run_id=None,
        persona_id=persona_id,
        payload={
            "persona_instance_id": instance_id,
            "root_chat_session_id": chat_session,
        },
        session_id=chat_session,
    )
    batch = [(held + 1, event)]
    frames = persona_chat_turn_frames(batch, batch_turn_roots(batch), base_offset=held)
    assert frames is not None and len(frames) == 1, frames
    frame = frames[0]
    core = owner_hydrate["core"]
    assert frame["persona_instance"] == core["persona_instances"][instance_id]
    # ``running_work`` is compared AFTER normalization (its rows carry the
    # generator's pid and wall-clock seconds), by the fixture test.
    assert frame["operator_channel"] in core["operator_channels"].values()
    return frame
