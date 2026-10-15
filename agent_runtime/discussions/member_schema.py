"""Optional persona ownership; profile groups never manufacture instance IDs."""
from __future__ import annotations

import json
import sqlite3

__layer__ = "stores"

MEMBER_COLUMNS = """(
    run_id TEXT NOT NULL, member_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
    install_id TEXT NOT NULL, instance_id TEXT, persona_id TEXT,
    profile TEXT NOT NULL, display_name TEXT NOT NULL, handle TEXT NOT NULL,
    session_id TEXT NOT NULL, seat INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('joining','active','removing','removed')),
    binding_json TEXT,
    PRIMARY KEY(run_id,member_id), UNIQUE(run_id,ordinal), UNIQUE(run_id,session_id),
    CHECK((instance_id IS NOT NULL AND persona_id IS NOT NULL AND binding_json IS NULL)
       OR (instance_id IS NULL AND persona_id IS NULL AND binding_json IS NOT NULL)))"""


def upgrade_members(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE mc_discussion_members_v3 " + MEMBER_COLUMNS)
    conn.execute("INSERT INTO mc_discussion_members_v3 SELECT *,NULL FROM mc_discussion_members")
    conn.execute("DROP TABLE mc_discussion_members")
    conn.execute("ALTER TABLE mc_discussion_members_v3 RENAME TO mc_discussion_members")
    conn.execute("UPDATE mc_discussion_runs_schema SET version=3")


def member_record(row: sqlite3.Row) -> dict:
    result = dict(row)
    binding = result.pop("binding_json", None)
    if binding is not None:
        result["binding"] = json.loads(binding)
    return result
