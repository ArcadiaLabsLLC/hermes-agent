"""A group cutover intent and its atomic commit on the existing run record."""
from __future__ import annotations

from hermes_cli.sqlite_util import transaction
from .definition_store import _encode
from .member_schema import member_record
from .run_records import _advance, _expect_run, read_run_record
from .run_values import DiscussionError

__layer__ = "stores"


def reserve(runs, run, intent, expected):
    with transaction(runs.connect(), immediate=True) as conn:
        current = read_run_record(conn, run["run_id"])
        prior = current["initial"].get("group_migration")
        if prior is not None:
            if prior["intent"] != intent:
                raise DiscussionError("migration_target_changed")
            return current
        _expect_run(current, expected)
        if current["phase"] != "paused" or "group" not in current["initial"]:
            raise DiscussionError("pause_before_migration")
        if conn.execute("SELECT 1 FROM mc_discussion_commands WHERE run_id=? AND state='pending'",
                        (run["run_id"],)).fetchone():
            raise DiscussionError("pending_commands")
        initial = {**current["initial"], "group_migration": {"intent": intent, "state": "pending"}}
        conn.execute("UPDATE mc_discussion_runs SET initial_json=? WHERE run_id=?", (_encode(initial), run["run_id"]))
        _advance(conn, current)
        return read_run_record(conn, run["run_id"])


def commit(runs, run, spec, adopted):
    """Keep public event/member identities and receipts; replace only execution bindings."""
    with transaction(runs.connect(), immediate=True) as conn:
        current = read_run_record(conn, run["run_id"])
        migration = current["initial"].get("group_migration")
        if migration != run["initial"]["group_migration"] or current["phase"] != "paused":
            raise DiscussionError("migration_state_changed")
        intent = migration["intent"]
        group = current["initial"]["group"]
        original_members = [member_record(row) for row in conn.execute(
            "SELECT * FROM mc_discussion_members WHERE run_id=? ORDER BY ordinal", (run["run_id"],))]
        if {m["member_id"] for m in original_members} != set(adopted):
            raise DiscussionError("migration_members_changed")
        for member in original_members:
            target = adopted[member["member_id"]]
            conn.execute("""UPDATE mc_discussion_members SET instance_id=?,persona_id=?,session_id=?,binding_json=NULL
                WHERE run_id=? AND member_id=?""", (target["persona_instance_id"], target["persona_id"],
                    target["session_id"], run["run_id"], member["member_id"]))
        initial = {"discussion": spec.to_dict(), "client_scope": group["client"],
            "legacy_group": {"workspace_id": current["workspace_id"], "group": group,
                "members": original_members},
            "group_migration": {**migration, "state": "complete"}}
        conn.execute("UPDATE mc_discussion_runs SET workspace_id=?,initial_json=?,error=NULL WHERE run_id=?",
                     (intent["target_workspace_id"], _encode(initial), run["run_id"]))
        _advance(conn, current)
        return read_run_record(conn, run["run_id"])
