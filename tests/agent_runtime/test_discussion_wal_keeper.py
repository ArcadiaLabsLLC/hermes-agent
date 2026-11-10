"""The discussion service keeps state.db's WAL alive between store ops (RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED).

Each store op opens and closes its own connection; without a held connection every close is the last one,
which checkpoints and deletes ``state.db-wal`` so the next op re-creates it (a 12.3 s commit under a disk
storm). ``RunStore.keep_wal`` is that held connection; the service owns one for its life.
"""

from __future__ import annotations

from contextlib import closing

from agent_runtime.discussions.definition_store import DefinitionStore
from agent_runtime.discussions.run_store import RunStore
from tests.agent_runtime.test_discussion_runtime import engine


def _op(runs: RunStore) -> None:
    with closing(runs.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS keeper_probe(x)")
        conn.execute("INSERT INTO keeper_probe VALUES (1)")
        conn.commit()


def test_the_wal_survives_a_store_ops_close_while_the_keeper_is_held(tmp_path):
    """Killing mutation: ``keep_wal`` without its read (a lazy, lock-free connection) -> the op's close is the
    last, the WAL is deleted, red."""

    runs = RunStore(DefinitionStore(tmp_path / "state.db"))
    runs.connect().close()  # the service opens its keeper after the schema, on a WAL file
    wal = tmp_path / "state.db-wal"
    keeper = runs.keep_wal()
    try:
        _op(runs)
        assert wal.exists()
    finally:
        keeper.close()


def test_without_the_keeper_the_last_close_deletes_the_wal(tmp_path):
    """The control: what the keeper prevents does happen without it."""

    runs = RunStore(DefinitionStore(tmp_path / "state.db"))
    _op(runs)
    assert not (tmp_path / "state.db-wal").exists()


def test_the_service_holds_a_keeper_for_its_life(engine):
    """Killing mutation: drop ``self._wal_keeper = self.runs.keep_wal()`` from ``DiscussionService`` -> red."""

    service, _ = engine
    _op(service.runs)
    assert (service.db_path.parent / "state.db-wal").exists()
