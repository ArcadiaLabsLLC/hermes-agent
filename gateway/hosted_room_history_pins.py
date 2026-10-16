"""Group Chat meeting-transcript retention opt-ins — fork-owned, beside ``gateway/hosted_rooms.py``.

``pin_room_history`` / ``unpin_room_history`` moved here unchanged from the upstream
``gateway/hosted_rooms.py`` (footprint audit 2026-10-15, lane G). What stays upstream-side is
the seam they rely on: ``MAX_RETAINED_ROOM_HISTORIES``, ``RoomHistoryRetentionFullError``, the
``hosted_room_history_pins`` entry in ``_DEPENDENT_TABLES`` and the prune's pinned-room ordering.

The bodies read ``hosted_rooms``' private helpers through the module at CALL time, as they did
in place (a stub on ``gateway.hosted_rooms`` still reaches the call). Those reaches are
import-layers exceptions (``tests/fixtures/import_layers_grandfathered.json``) waiting on door
J2 of ``docs/agent-runtime-harness/planned/upstream-doors-2026-10-06.md`` (Group Chat host
surface, issue #125258).
"""

from __future__ import annotations

from typing import Any

from gateway import hosted_rooms as rooms
from gateway.hosted_rooms_common import DbPath, table_exists


def pin_room_history(
    db_path: DbPath, *, room_id: Any, expected_gateway_id: Any, expected_epoch: Any
) -> None:
    """Retain a meeting's public log after disband, without retaining active writers.

    A host embedding Group Chat as a finite meeting has a separate explicit End:
    that ends execution, not the user's right to read its transcript. Pin BEFORE
    disband, in the same owning gateway. This generic retention opt-in changes
    neither stock deleted-chat behavior nor gateway byte limits.

    Refusal is TYPED (``history_retention_full``) so a host can report it rather
    than surface a bare storage message. A retention claim is never a lifecycle
    authority: a caller that cannot pin must still be able to finish its meeting.
    """
    room_id = rooms._room_id(room_id)
    expected_gateway_id = rooms._actor_id(expected_gateway_id, "expected_gateway_id")
    rooms._require_positive_int(expected_epoch, "expected_epoch")
    with rooms._transaction(db_path, immediate=True) as conn:
        room = rooms._room_row(conn, rooms._SELECT_ROOM_WITH_BYTES, (room_id,), room_id)
        rooms._require_authority(room, expected_gateway_id, expected_epoch, "stale hosted room authority")
        conn.execute("CREATE TABLE IF NOT EXISTS hosted_room_history_pins (room_id TEXT PRIMARY KEY)")
        if conn.execute("SELECT 1 FROM hosted_room_history_pins WHERE room_id=?", (room_id,)).fetchone():
            return
        if conn.execute("SELECT COUNT(*) FROM hosted_room_history_pins").fetchone()[0] >= rooms.MAX_RETAINED_ROOM_HISTORIES:
            raise rooms.RoomHistoryRetentionFullError("retained room history limit reached")
        conn.execute("INSERT INTO hosted_room_history_pins VALUES(?)", (room_id,))


def unpin_room_history(
    db_path: DbPath, *, room_id: Any, expected_gateway_id: Any, expected_epoch: Any
) -> bool:
    """Release one retention opt-in; ordinary deleted-chat retention applies again.

    The inverse of :func:`pin_room_history`, and the reason the pin table cannot
    grow without a valve. A pin outlives its room row only as litter, so when the
    room is already gone the leftover is dropped without an authority check —
    there is nothing left to be authoritative about. Returns whether a pin was
    actually removed.
    """
    room_id = rooms._room_id(room_id)
    expected_gateway_id = rooms._actor_id(expected_gateway_id, "expected_gateway_id")
    expected_epoch = rooms._require_positive_int(expected_epoch, "expected_epoch")
    with rooms._transaction(db_path, immediate=True) as conn:
        if not table_exists(conn, "hosted_room_history_pins"):
            return False
        room = conn.execute(rooms._SELECT_ROOM_WITH_BYTES, (room_id,)).fetchone()
        if room is not None:
            rooms._require_authority(room, expected_gateway_id, expected_epoch, "stale hosted room authority")
        return conn.execute("DELETE FROM hosted_room_history_pins WHERE room_id=?", (room_id,)).rowcount > 0
