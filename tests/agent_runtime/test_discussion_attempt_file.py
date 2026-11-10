"""Turn receipts live in their own file, so their FULL commits never hold the room store's write lock.

RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED: a receipt commit at ``synchronous=FULL`` fsyncs the WAL under the
write lock of the file it is in; in the shared ``state.db`` a stalled fsync refused every room, run and
definition writer past the 10 s busy timeout. The receipts moved beside it; an older build's rows move with a
fence that makes an older gateway refuse rather than claim a turn in the legacy table.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``AttemptStore.__init__`` keeps ``self.db_path = self.legacy_path`` (receipts back in ``state.db``)
  -> ``test_a_held_receipt_write_does_not_block_a_room_write`` red (``database is locked``).
* ``_move_legacy_rows`` drops its ``UPDATE … SET version`` fence
  -> ``test_legacy_receipts_move_and_an_older_build_refuses_the_legacy_table`` red.
* ``_move_legacy_rows`` drops its ``INSERT OR IGNORE`` copy -> the same test red (the row is not found).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from agent_runtime.discussions import attempt_store
from agent_runtime.discussions.attempt_store import AttemptStore
from agent_runtime.discussions.run_store import DiscussionError

MEMBER = {"member_id": "m1", "session_id": "s1"}


def test_a_held_receipt_write_does_not_block_a_room_write(tmp_path):
    state = tmp_path / "state.db"
    store = AttemptStore(state)
    store.begin("run", "task", 1, MEMBER, "hello")
    # A receipt commit stalled in its fsync holds its file's write lock exactly like this.
    held = store.connect()
    held.execute("BEGIN IMMEDIATE")
    try:
        with closing(sqlite3.connect(state, timeout=0.2)) as room:
            room.execute("CREATE TABLE IF NOT EXISTS room_probe(x)")
            room.execute("BEGIN IMMEDIATE")
            room.execute("INSERT INTO room_probe VALUES (1)")
            room.execute("COMMIT")
    finally:
        held.rollback()
        held.close()


def _legacy_receipt(state):
    """What an older build left: the receipts table inside ``state.db`` with one running turn."""
    with closing(sqlite3.connect(state)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        attempt_store._initialize(conn)
        conn.execute("""INSERT INTO mc_discussion_attempts
            (run_id,task_id,generation,member_id,session_id,native_id,prompt,stage,owner_pid)
            VALUES('run','task',1,'m1','s1','native-1','hello','running',4242)""")
        conn.commit()


def test_legacy_receipts_move_and_an_older_build_refuses_the_legacy_table(tmp_path):
    state = tmp_path / "state.db"
    _legacy_receipt(state)
    row = AttemptStore(state).get("run", "task", 1)
    assert row is not None and (row["stage"], row["native_id"], row["owner_pid"]) == ("running", "native-1", 4242)
    with closing(sqlite3.connect(state)) as legacy:
        # An older gateway opening the legacy table fails closed instead of claiming the turn again.
        with pytest.raises(DiscussionError, match="unsupported attempt schema"):
            attempt_store._ready(legacy)
    # A second store on the same home (another gateway) neither re-copies nor refuses.
    again = AttemptStore(state)
    assert again.update(row, stage="terminal", receipt={"status": "settled"})
    assert AttemptStore(state).get("run", "task", 1)["stage"] == "terminal"
