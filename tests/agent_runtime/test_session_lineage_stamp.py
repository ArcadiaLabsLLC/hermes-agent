"""The SessionDB lineage stamp moves on every message write and on nothing else (plan S1)."""
from __future__ import annotations

from hermes_state import SessionDB

from agent_runtime.session_lineage_stamp import TRIGGER_NAMES, lineage_stamp


def _chain(db):
    """root --compression--> tip (live)."""
    db.create_session("root", source="tui")
    db.append_message("root", role="user", content="the start")
    db.append_message("root", role="assistant", content="first answer")
    db.end_session("root", "compression")
    db.create_session("tip", source="tui", parent_session_id="root")
    db.append_message("tip", role="user", content="continued")


def _user_row(db, session_id):
    return next(m["id"] for m in db.get_messages(session_id) if m["role"] == "user")


def test_stamp_spans_the_compression_lineage_and_is_stable_without_writes(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    first = lineage_stamp(db, "root")
    assert first.tip == "tip"
    assert first.sessions == ("root", "tip")
    assert lineage_stamp(db, "root") == first
    assert lineage_stamp(db, "tip") == first
    db.close()


def test_an_insert_moves_the_stamp(tmp_path):
    """Positive control: the INSERT trigger is wired at all."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    db.append_message("tip", role="assistant", content="reply")
    assert lineage_stamp(db, "root") != before
    db.close()


def test_an_in_place_content_update_moves_the_stamp(tmp_path):
    """Killing mutation: drop the UPDATE trigger -> an in-place repair leaves the stamp equal."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    assert db.set_user_message_content("tip", _user_row(db, "tip"), "rewritten prompt") == 1
    after = lineage_stamp(db, "root")
    assert after != before
    assert after.revisions[1] > before.revisions[1]
    db.close()


def test_an_ancestor_flip_moves_the_stamp(tmp_path):
    """A write to a compressed ancestor, not the tip, still moves the lineage stamp."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    assert db.deactivate_message("root", _user_row(db, "root")) == 1
    after = lineage_stamp(db, "root")
    assert after.tip == before.tip and after.revisions[0] > before.revisions[0]
    db.close()


def test_a_delete_moves_the_stamp(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    row_id = _user_row(db, "tip")
    db._execute_write(lambda conn: conn.execute("DELETE FROM messages WHERE id = ?", (row_id,)))
    assert lineage_stamp(db, "root") != before
    db.close()


def test_a_dropped_trigger_reinstalls_under_a_new_epoch(tmp_path):
    """A table rebuild drops triggers; writes in the gap are invisible, so no old stamp may match."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    db._execute_write(lambda conn: conn.execute(f"DROP TRIGGER {TRIGGER_NAMES[1]}"))
    db.set_user_message_content("tip", _user_row(db, "tip"), "edited while unwatched")
    after = lineage_stamp(db, "root")
    assert after.epoch != before.epoch
    with db._read_ctx() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert set(TRIGGER_NAMES) <= names
    db.close()


def test_a_read_only_store_without_the_schema_has_no_stamp(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    db.close()
    reader = SessionDB(tmp_path / "state.db", read_only=True)
    assert lineage_stamp(reader, "root") is None
    reader.close()


def test_a_store_without_the_native_readers_has_no_stamp():
    assert lineage_stamp(object(), "root") is None


def test_every_messages_column_is_classified(tmp_path):
    """Read from the live schema: a column upstream adds must be classified before the stamp trusts it."""
    from agent_runtime.session_lineage_stamp import DERIVED_COLUMNS, PAYLOAD_COLUMNS

    db = SessionDB(tmp_path / "state.db")
    with db._read_ctx() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    db.close()
    assert columns == set(PAYLOAD_COLUMNS) | set(DERIVED_COLUMNS)
    assert not set(PAYLOAD_COLUMNS) & set(DERIVED_COLUMNS)


def test_a_derived_only_update_does_not_move_the_stamp(tmp_path):
    """The write-budget skip, positive-controlled: the same row's payload write does move it."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    before = lineage_stamp(db, "root")
    row_id = _user_row(db, "tip")
    db._execute_write(lambda conn: conn.execute("UPDATE messages SET display_order = 999 WHERE id = ?", (row_id,)))
    assert lineage_stamp(db, "root") == before
    db._execute_write(lambda conn: conn.execute(
        "UPDATE messages SET display_order = 998, content = 'x' WHERE id = ?", (row_id,)))
    assert lineage_stamp(db, "root") != before
    db.close()
