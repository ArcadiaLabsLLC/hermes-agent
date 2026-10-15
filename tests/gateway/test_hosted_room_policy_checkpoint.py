"""Behavior tests for the room policy checkpoint's active-projection budget.

The budget is a host-declared bound, not a global: a native discussion admits
more rounds than stock Bot Mode and must be able to say so without changing
what a stock Group Chat projection will load.
"""

from __future__ import annotations

import pytest

from gateway import hosted_rooms as rooms
from gateway import hosted_room_policy_checkpoint as checkpoint

USER = {"kind": "user", "id": "desktop-user", "display_name": "User"}
MEMBER = {"kind": "member", "id": "ops", "profile": "ops"}


def _room(db) -> int:
    """One discussion whose active projection is deliberately over the default."""
    rooms.create_room(
        db,
        room_id="room-1",
        name="Release room",
        members=[{"profile": "ops", "handle": "ops"}],
        authority_gateway_id="gateway-a",
        now=10,
    )
    rooms.append_event(
        db,
        room_id="room-1",
        event_id="user-1",
        kind="message.user",
        actor=USER,
        payload={"text": "Open the discussion.", "thread_id": "thread-1"},
        authority_gateway_id="gateway-a",
        authority_epoch=1,
        now=11,
    )
    for index in range(checkpoint.MAX_ACTIVE_POLICY_EVENTS + 6):
        rooms.append_event(
            db,
            room_id="room-1",
            event_id=f"member-{index}",
            kind="message.member",
            actor=MEMBER,
            payload={
                "text": f"Reply {index}.",
                "thread_id": "thread-1",
                "discussion_event_id": "user-1",
                "member_id": "ops",
            },
            authority_gateway_id="gateway-a",
            authority_epoch=1,
            now=12 + index,
        )
    return int(rooms.room_state(db, room_id="room-1")["latest_seq"])


def test_active_policy_event_budget_bounds_the_projection_it_is_given(tmp_path):
    db = tmp_path / "state.db"
    latest_seq = _room(db)
    expected = checkpoint.MAX_ACTIVE_POLICY_EVENTS + 7  # the user turn plus its replies

    with pytest.raises(RuntimeError, match="active room policy projection exceeded its bound"):
        checkpoint.HostedRoomPolicyCheckpoint(db).snapshot(
            room_id="room-1", latest_seq=latest_seq
        )

    # Positive control: identical room, identical events, one constructor
    # argument changed. Without it a passing bound proves nothing about which
    # events the projection actually held.
    raised = checkpoint.HostedRoomPolicyCheckpoint(db, max_active_events=256)
    snapshot = raised.snapshot(room_id="room-1", latest_seq=latest_seq)
    assert len(snapshot.events) == expected


@pytest.mark.parametrize(
    "value",
    [0, checkpoint.MAX_ACTIVE_POLICY_EVENTS - 1, 1025, float(checkpoint.MAX_ACTIVE_POLICY_EVENTS), True, "64"],
)
def test_active_policy_event_budget_refuses_values_it_cannot_honour(tmp_path, value):
    # Below the stock floor a host would silently shrink stock Group Chat
    # projection; above the ceiling it would unbound a per-turn read.
    with pytest.raises(ValueError, match="invalid active policy event budget"):
        checkpoint.HostedRoomPolicyCheckpoint(tmp_path / "state.db", max_active_events=value)
