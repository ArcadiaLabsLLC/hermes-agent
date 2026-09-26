from contextlib import closing
import sqlite3

import pytest

from agent_runtime.discussions.definitions import DefinitionError
from agent_runtime.discussions.room_definition import RoomSpec
from agent_runtime.discussions.run_store import DiscussionError
from agent_runtime.discussions.run_schema import initialize_runs
from tests.agent_runtime.test_discussion_definitions import table_value
from tests.agent_runtime.test_discussion_runtime import engine, wait_until, settled, command

pytestmark = pytest.mark.timeout(90)


def spec(count=2):
    config = table_value(count)["configuration"]
    return RoomSpec.parse({"name": "Review", "participants": config["participants"], "settings": config["settings"]})


def test_nonspatial_room_uses_same_executor_and_claims_without_furniture(engine):
    service, context = engine
    room = service.begin_room("ws", spec(), key="room", topic="Review", actor_id="operator")
    assert room["table_id"] is None
    assert "table" not in room["initial"]
    view = wait_until(lambda: settled(service, room))
    assert len(context.calls) == 2
    assert len({call.session_id for call in context.calls}) == 2
    assert len([row for row in view["log"]["events"] if row["kind"] == "message.member"]) == 2
    assert service.begin_room("ws", spec(), key="room", topic="Review", actor_id="operator")["run_id"] == room["run_id"]
    with closing(service.runs.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM mc_discussion_table_claims").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM mc_discussion_instance_claims").fetchone()[0] == 2
    table = service.definitions.save_table("ws", "real-table", table_value(), expect_revision=0)
    with pytest.raises(DiscussionError, match="instance busy"):
        service.begin("ws", "real-table", expect_revision=table.revision, key="other", topic="Other", actor_id="operator")
    command(service, room, "end")
    wait_until(lambda: service.view("ws", room["run_id"])["run"]["phase"] == "ended")
    next_run = service.begin("ws", "real-table", expect_revision=table.revision, key="other", topic="Other", actor_id="operator")
    wait_until(lambda: settled(service, next_run))
    assert len(context.calls) == 4


def test_nonspatial_limit_and_idempotency_conflicts_are_not_silent_edits(engine):
    service, _ = engine
    for count in (1, 10):
        with pytest.raises(DefinitionError):
            spec(count)
    run = service.begin_room("ws", spec(9), key="nine", topic="Review", actor_id="operator")
    with pytest.raises(DiscussionError, match="idempotency conflict"):
        service.begin_room("ws", spec(8), key="nine", topic="Review", actor_id="operator")
    view = wait_until(lambda: settled(service, run))
    assert len(view["members"]) == 9


def test_schema_one_upgrade_preserves_every_run_and_claim(tmp_path):
    # Build the OLD schema, not the production v2 schema relabeled as v1.
    db = sqlite3.connect(tmp_path / "old.sqlite")
    try:
        db.execute("CREATE TABLE mc_discussion_runs_schema (singleton INTEGER PRIMARY KEY,version INTEGER)")
        db.execute("INSERT INTO mc_discussion_runs_schema VALUES(1,1)")
        db.execute("""CREATE TABLE mc_discussion_runs (
          run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, table_id TEXT NOT NULL,
          start_key TEXT NOT NULL, request_digest TEXT NOT NULL, revision INTEGER NOT NULL,
          phase TEXT NOT NULL, initial_json TEXT NOT NULL, topic TEXT NOT NULL, actor_id TEXT NOT NULL,
          created_at REAL NOT NULL, updated_at REAL NOT NULL, error TEXT, UNIQUE(workspace_id,start_key))""")
        db.execute("CREATE INDEX mc_discussion_runs_workspace ON mc_discussion_runs(workspace_id,created_at,run_id)")
        db.execute("CREATE TABLE mc_discussion_instance_claims(install_id TEXT,instance_id TEXT,run_id TEXT)")
        db.execute("INSERT INTO mc_discussion_instance_claims VALUES('install','personainst_a','old')")
        row = ('old', 'ws', 'table', 'key', 'digest', 7, 'paused', '{"table":{"name":"Original"}}',
               'Important topic', 'operator', 10.0, 20.0, None)
        db.execute("INSERT INTO mc_discussion_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        db.commit()
        with db:
            initialize_runs(db)
        assert db.execute("SELECT * FROM mc_discussion_runs").fetchone() == row
        assert db.execute("SELECT * FROM mc_discussion_instance_claims").fetchone() == ('install', 'personainst_a', 'old')
        assert db.execute("SELECT version FROM mc_discussion_runs_schema").fetchone()[0] == 2
        db.execute("INSERT INTO mc_discussion_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ('new', 'ws', None, 'new-key', *row[4:]))
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == 'ok'
    finally:
        db.close()
