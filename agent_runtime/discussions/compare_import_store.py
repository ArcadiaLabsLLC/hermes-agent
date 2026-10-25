"""Atomic Compare import completion on the existing Discussion run record."""
from __future__ import annotations

from contextlib import closing

from hermes_cli.sqlite_util import transaction
from .definition_store import _encode
from .run_records import _advance, read_run_record
from .run_values import DiscussionError

__layer__ = "stores"


def complete(runs, run, sessions):
    with transaction(runs.connect(), immediate=True) as conn:
        current = read_run_record(conn, run["run_id"])
        receipt = current["initial"]["compare_import"]
        if receipt["state"] == "complete":
            return current
        if receipt != run["initial"]["compare_import"] or current["phase"] != "initializing":
            raise DiscussionError("migration_state_changed")
        for member_id, session_id in sessions.items():
            conn.execute("UPDATE mc_discussion_members SET session_id=?,status='active' WHERE run_id=? AND member_id=?",
                         (session_id, run["run_id"], member_id))
        initial = {**current["initial"], "compare_import": {**receipt, "state": "complete"}}
        conn.execute("UPDATE mc_discussion_runs SET initial_json=?,error=NULL WHERE run_id=?", (_encode(initial), run["run_id"]))
        _advance(conn, current, phase="paused")
        return read_run_record(conn, run["run_id"])


def find(runs, owner, actor_id, source_id):
    with closing(runs.connect()) as conn:
        row = conn.execute("""SELECT run_id FROM mc_discussion_runs
            WHERE actor_id=? AND json_extract(initial_json,'$.client_scope')=?
            AND json_extract(initial_json,'$.compare_import.source.id')=?""",
            (actor_id, owner, source_id)).fetchone()
        return read_run_record(conn, row[0]) if row is not None else None
