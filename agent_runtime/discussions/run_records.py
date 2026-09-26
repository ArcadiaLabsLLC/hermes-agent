"""Atomic run and member records; callers own the transaction."""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Mapping

from .definitions import ParticipantRef, revision
from .run_values import DiscussionError, member_id, native_session_id

__layer__ = "stores"


def read_run_record(conn: sqlite3.Connection, run_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM mc_discussion_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None or (workspace_id is not None and row["workspace_id"] != workspace_id):
        raise DiscussionError("run_not_found")
    result = dict(row)
    result["initial"] = json.loads(result.pop("initial_json"))
    result.pop("request_digest")
    return result


def _advance(conn: sqlite3.Connection, run: Mapping[str, Any], *, phase: str | None = None) -> None:
    if run["revision"] >= 2**53 - 1:
        raise DiscussionError("revision_exhausted")
    conn.execute("UPDATE mc_discussion_runs SET revision=revision+1,phase=?,updated_at=? WHERE run_id=?",
                 (phase or run["phase"], time.time(), run["run_id"]))


def _expect_run(run: Mapping[str, Any], expected: int) -> None:
    if run["revision"] != revision(expected, minimum=1):
        raise DiscussionError("stale_revision", current_revision=run["revision"])


def _add_member(conn: sqlite3.Connection, run_id: str, item: Mapping[str, Any], *, ordinal: int, seat: int) -> None:
    ref = ParticipantRef.parse({k: item[k] for k in ("install_id", "instance_id")})
    try:
        conn.execute("INSERT INTO mc_discussion_instance_claims VALUES(?,?,?)", (ref.install_id, ref.instance_id, run_id))
    except sqlite3.IntegrityError as exc:
        raise DiscussionError("instance_busy", instance_id=ref.instance_id) from exc
    mid = member_id(ref)
    conn.execute("""INSERT INTO mc_discussion_members VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (run_id, mid, ordinal, ref.install_id, ref.instance_id, item["persona_id"], item["profile"],
                  item["display_name"], "agent-" + mid[2:14], native_session_id(run_id, ref.instance_id), seat, "joining"))
