"""Discussion run schema; initialized under one SQLite write transaction."""
from __future__ import annotations

import sqlite3

from .run_values import DiscussionError

__layer__ = "stores"

_RUN_COLUMNS = """(
    run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, table_id TEXT,
    start_key TEXT NOT NULL, request_digest TEXT NOT NULL, revision INTEGER NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('initializing','open','stopping','paused','ending','ended','failed')),
    initial_json TEXT NOT NULL, topic TEXT NOT NULL, actor_id TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, error TEXT,
    UNIQUE(workspace_id,start_key))"""
_INDEX = "CREATE INDEX mc_discussion_runs_workspace ON mc_discussion_runs(workspace_id,created_at,run_id)"


def run_schema_ready(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='mc_discussion_runs_schema'").fetchone() is None:
        return False
    rows = conn.execute("SELECT version FROM mc_discussion_runs_schema").fetchall()
    if len(rows) != 1 or rows[0][0] not in (1, 2):
        raise DiscussionError("unsupported_run_schema")
    return rows[0][0] == 2


def initialize_runs(conn: sqlite3.Connection) -> None:
    if run_schema_ready(conn):
        return
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='mc_discussion_runs_schema'").fetchone():
        # Preserve every Mission Control row and claim. Only placement becomes
        # optional; IDs, revisions, snapshots and execution evidence are unchanged.
        conn.execute("CREATE TABLE mc_discussion_runs_v2 " + _RUN_COLUMNS)
        conn.execute("INSERT INTO mc_discussion_runs_v2 SELECT * FROM mc_discussion_runs")
        conn.execute("DROP TABLE mc_discussion_runs")
        conn.execute("ALTER TABLE mc_discussion_runs_v2 RENAME TO mc_discussion_runs")
        conn.execute(_INDEX)
        conn.execute("UPDATE mc_discussion_runs_schema SET version=2")
        return
    statements = (
        "CREATE TABLE mc_discussion_runs_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)",
        "CREATE TABLE mc_discussion_runs " + _RUN_COLUMNS,
        _INDEX,
        """CREATE TABLE mc_discussion_table_claims (
            workspace_id TEXT NOT NULL, table_id TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE,
            PRIMARY KEY(workspace_id,table_id))""",
        """CREATE TABLE mc_discussion_instance_claims (
            install_id TEXT NOT NULL, instance_id TEXT NOT NULL, run_id TEXT NOT NULL,
            PRIMARY KEY(install_id,instance_id))""",
        """CREATE TABLE mc_discussion_members (
            run_id TEXT NOT NULL, member_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            install_id TEXT NOT NULL, instance_id TEXT NOT NULL, persona_id TEXT NOT NULL,
            profile TEXT NOT NULL, display_name TEXT NOT NULL, handle TEXT NOT NULL,
            session_id TEXT NOT NULL, seat INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('joining','active','removing','removed')),
            PRIMARY KEY(run_id,member_id), UNIQUE(run_id,ordinal), UNIQUE(run_id,session_id))""",
        """CREATE TABLE mc_discussion_commands (
            run_id TEXT NOT NULL, command_key TEXT NOT NULL, operation TEXT NOT NULL,
            digest TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            created_at REAL NOT NULL, PRIMARY KEY(run_id,command_key))""",
    )
    for statement in statements:
        conn.execute(statement)
    conn.execute("INSERT INTO mc_discussion_runs_schema VALUES(1,2)")
