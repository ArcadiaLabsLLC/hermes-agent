"""Each discussion store opens at its ruled durability level (RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED).

Owner RULED 2026-11-09: the room and run stores commit at ``synchronous=NORMAL`` (a FULL commit's WAL fsync held
the shared ``state.db`` write lock past the 10 s busy timeout under a disk storm); the attempt receipts stay
``FULL``, since a rolled-back claim would let a turn run twice. Read back from real connections on one file.
"""

from __future__ import annotations

import sys
from contextlib import closing

from agent_runtime.discussions.attempt_store import AttemptStore
from agent_runtime.discussions.definition_store import DefinitionStore
from agent_runtime.discussions.run_store import RunStore
from gateway import hosted_room_driver, hosted_rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint

NORMAL, FULL = 1, 2


def _level(conn) -> int:
    with closing(conn):
        return conn.execute("PRAGMA synchronous").fetchone()[0]


def test_attempt_receipts_stay_full(tmp_path):
    """Killing mutation: ``AttemptStore.connect`` drops ``synchronous="FULL"`` (the NORMAL default) -> red."""

    assert _level(AttemptStore(tmp_path / "state.db").connect()) == FULL


def test_room_and_run_stores_commit_at_normal(tmp_path):
    """Killing mutation: ``hosted_rooms_common.connect``'s ``synchronous`` default back to ``None`` (the build
    default, FULL) -> red."""

    db = tmp_path / "state.db"
    definitions = DefinitionStore(db)
    assert _level(definitions._connect()) == NORMAL
    assert _level(RunStore(definitions).connect()) == NORMAL
    assert _level(hosted_rooms._connect(db)) == NORMAL
    assert _level(hosted_room_driver._connect(db)) == NORMAL
    assert _level(HostedRoomPolicyCheckpoint(db, max_active_events=256)._connect()) == NORMAL


def test_macos_keeps_full_on_the_room_stores(tmp_path, monkeypatch):
    """The Darwin floor still wins: NORMAL is refused there, FULL kept."""

    monkeypatch.setattr(sys, "platform", "darwin")
    assert _level(hosted_rooms._connect(tmp_path / "state.db")) == FULL
