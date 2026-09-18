"""Real SQLite authoring tests; no mocks of transactions or template records."""
from __future__ import annotations

import multiprocessing
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_runtime.discussions.definition_store import DefinitionKind, DefinitionStore
from agent_runtime.discussions.definitions import MAX_REVISION, DefinitionError
from tests.agent_runtime.test_discussion_definitions import table_value


@pytest.fixture
def store(tmp_path):
    return DefinitionStore(tmp_path / "owned" / "state.db")


def preset_value(count=2):
    return {"name":"Engineering recipe", "preferred_capacity":"auto", "configuration":table_value(count)["configuration"]}


def test_constructor_and_rejected_requests_do_not_create_storage(tmp_path):
    store = DefinitionStore(tmp_path / "not-created" / "state.db")
    assert not store.db_path.exists()
    invalid = table_value()
    invalid["capacity"] = True
    with pytest.raises(DefinitionError):
        store.save_table("ws", "table", invalid, expect_revision=0)
    assert not store.db_path.parent.exists()
    with pytest.raises(DefinitionError, match="absolute_database_path_required"):
        DefinitionStore("relative/state.db")


def test_create_update_cas_and_reopen_preserve_data(store):
    original = store.save_table("ws", "table", table_value(), expect_revision=0)
    changed = table_value()
    changed["name"] = "Changed"
    updated = store.save_table("ws", "table", changed, expect_revision=original.revision)
    assert updated.definition_id == original.definition_id
    assert updated.revision == original.revision + 1
    with pytest.raises(DefinitionError, match="stale_revision"):
        store.save_table("ws", "table", table_value(), expect_revision=original.revision)
    assert DefinitionStore(store.db_path).get("table", "ws", "table") == updated


def test_preset_load_and_revert_are_revisioned_copies_not_live_links(store):
    table = store.save_table("ws", "table", table_value(2, 4), expect_revision=0)
    preset = store.save_preset("ws", "recipe", preset_value(3), expect_revision=0)
    loaded = store.load_preset("ws", "table", "recipe", expect_table_revision=table.revision, expect_preset_revision=preset.revision)
    assert not loaded.preset_modified
    assert loaded.spec.transform == table.spec.transform
    assert loaded.spec.capacity == table.spec.capacity and loaded.spec.name == table.spec.name
    assert loaded.preset_origin.revision == preset.revision
    edited = loaded.spec.to_dict()
    edited["configuration"]["settings"]["rounds"] = 1
    changed = store.save_table("ws", "table", edited, expect_revision=loaded.revision)
    assert changed.preset_modified
    source_update = store.save_preset("ws", "recipe", preset_value(4), expect_revision=preset.revision)
    store.delete("preset", "ws", "recipe", expect_revision=source_update.revision)
    assert store.get("table", "ws", "table") == changed
    reverted = store.revert_table("ws", "table", expect_revision=changed.revision)
    assert reverted.spec.configuration == loaded.spec.configuration
    assert not reverted.preset_modified
    assert reverted.preset_origin == loaded.preset_origin


def test_oversized_or_stale_preset_load_is_all_or_nothing(store):
    table = store.save_table("ws", "table", table_value(2, 4), expect_revision=0)
    preset = store.save_preset("ws", "recipe", preset_value(5), expect_revision=0)
    with pytest.raises(DefinitionError, match="capacity_exceeded"):
        store.load_preset("ws", "table", "recipe", expect_table_revision=table.revision, expect_preset_revision=preset.revision)
    assert store.get("table", "ws", "table") == table
    preset = store.save_preset("ws", "recipe", preset_value(3), expect_revision=preset.revision)
    with pytest.raises(DefinitionError, match="stale_preset_revision"):
        store.load_preset("ws", "table", "recipe", expect_table_revision=table.revision, expect_preset_revision=preset.revision-1)
    assert store.get("table", "ws", "table") == table
    loaded = store.load_preset("ws", "table", "recipe", expect_table_revision=table.revision, expect_preset_revision=preset.revision)
    assert len(loaded.spec.configuration.participants) == 3  # Positive control.


def test_shrink_then_revert_requires_room_for_the_saved_recipe(store):
    t = store.save_table("ws", "table", table_value(4, 4), expect_revision=0)
    p = store.save_preset("ws", "recipe", preset_value(4), expect_revision=0)
    t = store.load_preset("ws", "table", "recipe", expect_table_revision=t.revision, expect_preset_revision=p.revision)
    t = store.save_table("ws", "table", table_value(2, 2), expect_revision=t.revision)
    with pytest.raises(DefinitionError, match="capacity_exceeded"):
        store.revert_table("ws", "table", expect_revision=t.revision)
    assert store.get("table", "ws", "table") == t


def test_delete_tombstones_cannot_be_resurrected_by_old_clients(store):
    t = store.save_table("ws", "table", table_value(), expect_revision=0)
    tombstone_revision = store.delete(DefinitionKind.TABLE, "ws", "table", expect_revision=t.revision)
    for expected in (0, t.revision, tombstone_revision):
        with pytest.raises(DefinitionError, match="definition_deleted"):
            store.save_table("ws", "table", table_value(), expect_revision=expected)
    assert not store.list("table", "ws").records
    with pytest.raises(DefinitionError, match="definition_deleted"):
        store.get("table", "ws", "table")
    assert store.save_table("ws", "new_table", table_value(), expect_revision=0).definition_id == "new_table"


def test_workspace_and_kind_are_part_of_the_storage_key(store):
    left = store.save_table("left", "same", table_value(), expect_revision=0)
    right_data = table_value()
    right_data["name"] = "Right"
    right = store.save_table("right", "same", right_data, expect_revision=0)
    preset = store.save_preset("left", "same", preset_value(), expect_revision=0)
    assert store.list("table", "left").records == (left,)
    assert store.list("table", "right").records == (right,)
    assert store.list("preset", "left").records == (preset,)
    with pytest.raises(DefinitionError, match="definition_not_found"):
        store.load_preset("right", "same", "same", expect_table_revision=right.revision, expect_preset_revision=1)


def test_paging_is_bounded_and_does_not_reintroduce_deleted_rows(store):
    rows = [store.save_table("ws", f"table_{i}", table_value(), expect_revision=0) for i in range(5)]
    store.delete("table", "ws", "table_2", expect_revision=rows[2].revision)
    first = store.list("table", "ws", limit=2)
    second = store.list("table", "ws", limit=2, after=first.next_cursor)
    assert [r.definition_id for r in first.records + second.records] == ["table_0","table_1","table_3","table_4"]
    assert second.next_cursor is None
    for invalid in (0, 101, True, 1.0):
        with pytest.raises(DefinitionError, match="invalid_limit"):
            store.list("table", "ws", limit=invalid)


@pytest.mark.parametrize("expected", [True, False, 1.0, "1", -1, 2**53])
def test_revision_inputs_are_lossless_json_integers(store, expected):
    with pytest.raises(DefinitionError, match="invalid_revision"):
        store.save_table("ws", "table", table_value(), expect_revision=expected)
    assert not store.db_path.exists()


def test_unknown_rows_and_revision_exhaustion_are_not_overwrites(store):
    with pytest.raises(DefinitionError, match="definition_not_found"):
        store.save_table("ws", "missing", table_value(), expect_revision=2)
    original = store.save_table("ws", "table", table_value(), expect_revision=0)
    with closing(sqlite3.connect(store.db_path)) as conn, conn:
        conn.execute("UPDATE mc_discussion_definitions SET revision=?", (MAX_REVISION,))
    for mutate in (
        lambda: store.save_table("ws", "table", table_value(), expect_revision=MAX_REVISION),
        lambda: store.delete("table", "ws", "table", expect_revision=MAX_REVISION),
    ):
        with pytest.raises(DefinitionError, match="revision_exhausted"):
            mutate()
    assert store.get("table", "ws", "table").spec == original.spec


def test_database_abort_rolls_back_revision_and_contents(store):
    original = store.save_table("ws", "table", table_value(), expect_revision=0)
    with closing(sqlite3.connect(store.db_path)) as conn, conn:
        conn.execute("""CREATE TRIGGER reject_definition BEFORE UPDATE ON mc_discussion_definitions
                        BEGIN SELECT RAISE(ABORT,'injected-storage-failure'); END""")
    changed = table_value()
    changed["name"] = "New"
    with pytest.raises(sqlite3.IntegrityError, match="injected-storage-failure"):
        store.save_table("ws", "table", changed, expect_revision=original.revision)
    assert store.get("table", "ws", "table") == original
    with closing(sqlite3.connect(store.db_path)) as conn, conn:
        conn.execute("DROP TRIGGER reject_definition")
    assert store.save_table("ws", "table", changed, expect_revision=original.revision).spec.name == "New"


def test_owned_database_does_not_follow_ambient_profile_changes(tmp_path, monkeypatch):
    a = DefinitionStore(tmp_path / "a" / "state.db")
    b = DefinitionStore(tmp_path / "b" / "state.db")
    for home in ("a", "b", "a"):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / home))
        a.save_table("ws", f"table_{home}", table_value(), expect_revision=0 if home == "b" else (1 if a.db_path.exists() else 0))
    b.save_table("ws", "table_b", table_value(), expect_revision=0)
    assert {r.definition_id for r in a.list("table", "ws").records} == {"table_a", "table_b"}
    assert {r.definition_id for r in b.list("table", "ws").records} == {"table_b"}
    assert a.get("table", "ws", "table_a").revision == 2


def test_shared_session_database_and_future_schema_are_preserved(store):
    from hermes_state import SessionDB

    db = SessionDB(db_path=store.db_path)
    try:
        with closing(sqlite3.connect(store.db_path)) as conn:
            before = conn.execute("PRAGMA user_version").fetchone()[0]
            sessions = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        original = store.save_table("ws", "table", table_value(), expect_revision=0)
        with closing(sqlite3.connect(store.db_path)) as conn, conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == before
            assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == sessions
            conn.execute("UPDATE mc_discussion_schema SET version=2")
        with pytest.raises(DefinitionError, match="unsupported_schema"):
            store.save_table("ws", "table", table_value(), expect_revision=original.revision)
        with closing(sqlite3.connect(store.db_path)) as conn:
            assert conn.execute("SELECT revision FROM mc_discussion_definitions").fetchone()[0] == original.revision
            assert conn.execute("SELECT version FROM mc_discussion_schema").fetchone()[0] == 2
    finally:
        db.close()


def test_corrupt_stored_definitions_do_not_look_like_an_empty_list(store):
    store.save_table("ws", "table", table_value(), expect_revision=0)
    with closing(sqlite3.connect(store.db_path)) as conn, conn:
        conn.execute("UPDATE mc_discussion_definitions SET document='{}'")
    with pytest.raises(DefinitionError, match="corrupt_definition"):
        store.list("table", "ws")


def _competing_writer(db_path, start, result, label):
    # Separate interpreter/process and real independent SQLite connection.
    if not start.wait(8):
        result.put("barrier_timeout")
        return
    value = table_value()
    value["name"] = label
    try:
        record = DefinitionStore(Path(db_path)).save_table("ws", "table", value, expect_revision=1)
        result.put(("saved", record.spec.name, record.revision))
    except DefinitionError as error:
        result.put((error.reason, label))


def test_two_processes_with_same_revision_have_exactly_one_winner(store):
    original = store.save_table("ws", "table", table_value(), expect_revision=0)
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    processes = [context.Process(target=_competing_writer, args=(str(store.db_path), start, results, label)) for label in ("Left", "Right")]
    try:
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=8) for _ in processes]
        for process in processes:
            process.join(timeout=3)
            assert process.exitcode == 0
        assert sorted(row[0] for row in outcomes) == ["saved", "stale_revision"]
        winner = next(row for row in outcomes if row[0] == "saved")
        stored = store.get("table", "ws", "table")
        assert stored.spec.name == winner[1] and stored.revision == original.revision + 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=3)
        results.close()
        results.join_thread()
