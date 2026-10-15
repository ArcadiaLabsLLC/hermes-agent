"""Fork-owned tests moved out of ``tests/gateway/test_hosted_rooms.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import sqlite3
import pytest
from gateway import hosted_rooms as rooms

from tests.gateway.test_hosted_rooms import (  # noqa: F401 — upstream names the moved tests use
    USER,
    _append,
    _create,
    _disband,
)


def _pin(db, room_id="room-1", *, gateway="gateway-a", epoch=1):
    return rooms.pin_room_history(
        db, room_id=room_id, expected_gateway_id=gateway, expected_epoch=epoch
    )


def _pins(db) -> set[str]:
    with sqlite3.connect(db) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
                " AND name='hosted_room_history_pins'"
            ).fetchone()
            is None
        ):
            return set()
        return {
            str(row[0])
            for row in conn.execute("SELECT room_id FROM hosted_room_history_pins")
        }


def _event_bytes(db) -> dict[str, int]:
    with sqlite3.connect(db) as conn:
        return {
            str(row[0]): int(row[1])
            for row in conn.execute("SELECT room_id, event_bytes FROM hosted_rooms")
        }


def _fill(db, room_id, *, text="x" * 2000, now=11):
    _append(
        db,
        room_id=room_id,
        event_id=f"{room_id}-note",
        kind="message.user",
        actor=USER,
        payload={"text": text, "thread_id": "thread-1"},
        now=now,
    )


def test_pinned_history_is_exempt_from_the_age_sweep(tmp_path):
    db = tmp_path / "state.db"
    for room_id in ("room-pinned", "room-plain"):
        _create(db, room_id)
        _fill(db, room_id)
    _pin(db, "room-pinned")
    _disband(db, room_id="room-pinned", now=20)
    _disband(db, room_id="room-plain", now=20)

    removed = rooms.prune_disbanded_rooms(
        db, now=20 + rooms.DISBANDED_ROOM_RETENTION_SECONDS + 1
    )

    # The unpinned twin is the positive control: same age, same payload shape.
    assert removed == 1
    assert (
        rooms.room_state(db, room_id="room-pinned", include_disbanded=True)["room_id"]
        == "room-pinned"
    )
    with pytest.raises(rooms.RoomNotFoundError):
        rooms.room_state(db, room_id="room-plain", include_disbanded=True)


def test_byte_budget_reclaims_unpinned_history_before_pinned_history(
    tmp_path,
    monkeypatch,
):
    db = tmp_path / "state.db"
    for room_id in ("room-pinned", "room-plain", "room-live"):
        _create(db, room_id)
        _fill(db, room_id)
    _pin(db, "room-pinned")
    # The PINNED room is the OLDER tombstone, so stock oldest-first reclaim would
    # take it first: reclaiming the newer unpinned room can only be pinned-last
    # ordering, never the untouched order.
    _disband(db, room_id="room-pinned", now=20)
    _disband(db, room_id="room-plain", now=21)
    sizes = _event_bytes(db)
    monkeypatch.setattr(
        rooms,
        "MAX_GATEWAY_EVENT_BYTES",
        sum(sizes.values()) - sizes["room-plain"] + 500,
    )

    _append(
        db,
        room_id="room-live",
        event_id="pressure",
        kind="message.user",
        actor=USER,
        payload={"text": "tiny", "thread_id": "thread-1"},
        now=30,
    )

    assert (
        rooms.room_state(db, room_id="room-pinned", include_disbanded=True)["room_id"]
        == "room-pinned"
    )
    assert _pins(db) == {"room-pinned"}
    with pytest.raises(rooms.RoomNotFoundError):
        rooms.room_state(db, room_id="room-plain", include_disbanded=True)


def test_byte_budget_still_reclaims_pinned_history_and_drops_its_pin(
    tmp_path,
    monkeypatch,
):
    db = tmp_path / "state.db"
    for room_id in ("room-pinned", "room-live"):
        _create(db, room_id)
        _fill(db, room_id)
    _pin(db, "room-pinned")
    _disband(db, room_id="room-pinned", now=20)
    # Only the live room's own history fits: retention must not be able to wedge
    # a host above its byte budget, or every later append fails closed instead.
    monkeypatch.setattr(
        rooms, "MAX_GATEWAY_EVENT_BYTES", _event_bytes(db)["room-live"] + 500
    )

    _append(
        db,
        room_id="room-live",
        event_id="pressure",
        kind="message.user",
        actor=USER,
        payload={"text": "tiny", "thread_id": "thread-1"},
        now=30,
    )

    with pytest.raises(rooms.RoomNotFoundError):
        rooms.room_state(db, room_id="room-pinned", include_disbanded=True)
    # The pin died with the payload it named, rather than outliving it as litter.
    assert _pins(db) == set()


def test_retention_limit_is_typed_and_unpin_frees_a_slot(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    for room_id in ("room-first", "room-second"):
        _create(db, room_id)
    monkeypatch.setattr(rooms, "MAX_RETAINED_ROOM_HISTORIES", 1)
    _pin(db, "room-first")

    with pytest.raises(rooms.RoomHistoryRetentionFullError) as refusal:
        _pin(db, "room-second")

    assert refusal.value.reason == "history_retention_full"
    assert isinstance(refusal.value, rooms.HostedRoomError)
    assert rooms.unpin_room_history(
        db, room_id="room-first", expected_gateway_id="gateway-a", expected_epoch=1
    )
    assert not rooms.unpin_room_history(
        db, room_id="room-first", expected_gateway_id="gateway-a", expected_epoch=1
    )
    # Positive control: the identical pin that was refused now succeeds.
    _pin(db, "room-second")
    assert _pins(db) == {"room-second"}


def test_unpin_rejects_stale_authority_and_tolerates_an_unused_store(tmp_path):
    db = tmp_path / "state.db"
    _create(db, "room-1")

    assert not rooms.unpin_room_history(
        db, room_id="room-1", expected_gateway_id="gateway-a", expected_epoch=1
    )
    _pin(db, "room-1")
    with pytest.raises(rooms.AuthorityConflictError):
        rooms.unpin_room_history(
            db, room_id="room-1", expected_gateway_id="gateway-b", expected_epoch=1
        )

    assert _pins(db) == {"room-1"}
