"""Durable native room admission and command intents, beside hosted-room state.

Table and instance claims are acquired with the definition snapshot in ONE
SQLite write transaction. External effects (native session creation and room-log
appends) happen afterward and are replayable from these intents. This store does
not own model turns: hosted_room_driver and the native turn journal do.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from gateway.hosted_rooms_common import connect
from hermes_cli.sqlite_util import transaction

from .definition_store import DefinitionStore, _encode, _expect, _required, _key, DefinitionKind
from .definitions import DefinitionError, ParticipantRef, identifier, revision, plan_seats
from .run_values import DiscussionError, text, digest, member_id, native_session_id
from .run_schema import _ready, _initialize
from .run_records import _run, _advance, _expect_run, _add_member

__layer__ = "stores"

MAX_CATALOG_MEMBERS = 128
MAX_OPEN_RUNS = 128
MAX_PENDING_COMMANDS = 64
COMMANDS = frozenset({"send", "stop", "end", "invite", "remove", "answer", "retry", "abandon"})
LIVE_PHASES = ("initializing", "open", "stopping", "paused", "ending")


class RunStore:
    def __init__(self, definitions: DefinitionStore) -> None:
        self.definitions, self.db_path = definitions, definitions.db_path

    def connect(self) -> sqlite3.Connection:
        # The definition schema and run schema use separate version authorities.
        with closing(self.definitions._connect()):
            pass
        return connect(self.db_path, db_label="native-discussions", ready=_ready, initialize=_initialize, lock_retries=4)

    def get(self, run_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        identifier(run_id, "run_id")
        with closing(self.connect()) as conn:
            return _run(conn, run_id, workspace_id)

    def list(self, workspace_id: str, *, limit: int = 50, after: str = "") -> list[dict[str, Any]]:
        identifier(workspace_id, "workspace_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DefinitionError("invalid_limit", "limit")
        if after:
            identifier(after, "after")
        with closing(self.connect()) as conn:
            ids = conn.execute("SELECT run_id FROM mc_discussion_runs WHERE workspace_id=? AND run_id>? ORDER BY run_id LIMIT ?",
                               (workspace_id, after, limit)).fetchall()
            return [_run(conn, row[0]) for row in ids]

    def owned(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            ids = conn.execute("SELECT run_id FROM mc_discussion_runs WHERE phase NOT IN ('ended','failed') ORDER BY created_at").fetchall()
            return [_run(conn, row[0]) for row in ids]

    def begin(self, workspace_id: str, table_id: str, *, expect_revision: int, key: str, topic: str,
              actor_id: str, resolve: Callable[[ParticipantRef, str], Mapping[str, Any]]) -> dict[str, Any]:
        identifier(key, "idempotency_key")
        expected, topic = revision(expect_revision, minimum=1), text(topic, field="topic")
        table_key = _key(DefinitionKind.TABLE, workspace_id, table_id)
        request_digest = digest({"table_id": table_id, "expect_revision": expected, "topic": topic})
        with transaction(self.connect(), immediate=True) as conn:
            previous = conn.execute("SELECT run_id,request_digest FROM mc_discussion_runs WHERE workspace_id=? AND start_key=?",
                                    (workspace_id, key)).fetchone()
            if previous is not None:
                if previous["request_digest"] != request_digest:
                    raise DiscussionError("idempotency_conflict")
                return _run(conn, previous["run_id"])
            table = _required(conn, table_key)
            _expect(table, expected)
            spec = table.spec
            if len(spec.configuration.participants) < 2:
                raise DiscussionError("at_least_two_agents_required")
            if conn.execute("SELECT 1 FROM mc_discussion_table_claims WHERE workspace_id=? AND table_id=?",
                            (workspace_id, table_id)).fetchone():
                raise DiscussionError("table_busy")
            if conn.execute("SELECT COUNT(*) FROM mc_discussion_table_claims").fetchone()[0] >= MAX_OPEN_RUNS:
                raise DiscussionError("too_many_open_discussions")
            catalog = [dict(resolve(ref, workspace_id)) for ref in spec.configuration.participants]
            run_id = "discussion-" + digest({"workspace_id": workspace_id, "key": key})[:24]
            now = time.time()
            initial = {"table": table.to_dict(), "seat_plan": {"capacity": spec.seat_count,
                       "assignments": [p.to_dict() for p in plan_seats(spec).assignments]}}
            conn.execute("INSERT INTO mc_discussion_runs VALUES(?,?,?,?,?,1,'initializing',?,?,?,?,?,NULL)",
                         (run_id, workspace_id, table_id, key, request_digest, _encode(initial), topic, actor_id, now, now))
            conn.execute("INSERT INTO mc_discussion_table_claims VALUES(?,?,?)", (workspace_id, table_id, run_id))
            seats = {pref.participant: pref.seat for pref in plan_seats(spec).assignments}
            for index, (ref, item) in enumerate(zip(spec.configuration.participants, catalog, strict=True)):
                _add_member(conn, run_id, item, ordinal=index, seat=seats[ref])
            return _run(conn, run_id)

    def activate(self, run_id: str) -> None:
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id)
            if run["phase"] == "initializing":
                conn.execute("UPDATE mc_discussion_members SET status='active' WHERE run_id=? AND status='joining'", (run_id,))
                _advance(conn, run, phase="open")

    def members(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM mc_discussion_members WHERE run_id=? ORDER BY ordinal", (run_id,))]

    def request(self, run_id: str, workspace_id: str, *, key: str, operation: str,
                expect_revision: int, body: Mapping[str, Any]) -> bool:
        """Record a replayable command. False means the identical intent exists."""
        identifier(key, "idempotency_key")
        if operation not in COMMANDS:
            raise DiscussionError("unknown_command")
        command_digest = digest({"operation": operation, "body": body})
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id, workspace_id)
            old = conn.execute("SELECT digest FROM mc_discussion_commands WHERE run_id=? AND command_key=?", (run_id, key)).fetchone()
            if old is not None:
                if old[0] != command_digest:
                    raise DiscussionError("idempotency_conflict")
                return False
            _expect_run(run, expect_revision)
            if run["phase"] in {"ended", "failed"} or (run["phase"] == "initializing" and operation != "end"):
                raise DiscussionError("run_not_editable", phase=run["phase"])
            if run["phase"] == "ending" and operation not in {"end", "abandon"}:
                raise DiscussionError("run_ending")
            count = conn.execute("SELECT COUNT(*) FROM mc_discussion_commands WHERE run_id=? AND state='pending'", (run_id,)).fetchone()[0]
            if count >= MAX_PENDING_COMMANDS:
                raise DiscussionError("command_queue_full")
            if conn.execute("SELECT COUNT(*) FROM mc_discussion_commands WHERE run_id=?", (run_id,)).fetchone()[0] >= 10000:
                raise DiscussionError("command_history_limit")
            if operation in {"stop", "end"}:
                conn.execute("""UPDATE mc_discussion_commands SET state='cancelled_by_stop'
                    WHERE run_id=? AND state='pending' AND operation IN ('send','invite','answer','retry')""", (run_id,))
            conn.execute("INSERT INTO mc_discussion_commands VALUES(?,?,?,?,?,'pending',?)",
                         (run_id, key, operation, command_digest, _encode(body), time.time()))
            phase = {"end": "ending", "stop": "stopping"}.get(operation)
            _advance(conn, run, phase=phase)
            return True

    def pending(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            result = []
            for row in conn.execute("SELECT * FROM mc_discussion_commands WHERE run_id=? AND state='pending' ORDER BY created_at,command_key", (run_id,)):
                item = dict(row)
                item["body"] = json.loads(item["body"])
                result.append(item)
            return result

    def finish_command(self, run_id: str, key: str, *, phase: str | None = None, error: str | None = None) -> None:
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id)
            changed = conn.execute("UPDATE mc_discussion_commands SET state=? WHERE run_id=? AND command_key=? AND state='pending'",
                                   ("failed:" + error if error else "done", run_id, key)).rowcount
            if changed:
                _advance(conn, run, phase=phase if run["phase"] != "ending" else None)
                conn.execute("UPDATE mc_discussion_runs SET error=? WHERE run_id=?", (error, run_id))

    def join(self, run_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id)
            ref = ParticipantRef.parse({k: item[k] for k in ("install_id", "instance_id")})
            existing = conn.execute("SELECT * FROM mc_discussion_members WHERE run_id=? AND member_id=?", (run_id, member_id(ref))).fetchone()
            if existing is not None:
                if existing["status"] != "removed":
                    return dict(existing)
                # A re-invitation keeps the room session and immutable member identity.
                if any(existing[k] != item[k] for k in ("persona_id", "profile")):
                    raise DiscussionError("profile_binding_changed")
                try:
                    conn.execute("INSERT INTO mc_discussion_instance_claims VALUES(?,?,?)", (ref.install_id, ref.instance_id, run_id))
                except sqlite3.IntegrityError as exc:
                    raise DiscussionError("instance_busy", instance_id=ref.instance_id) from exc
                used = {row[0] for row in conn.execute("SELECT seat FROM mc_discussion_members WHERE run_id=? AND status!='removed'", (run_id,))}
                free = next((i for i in range(run["initial"]["seat_plan"]["capacity"]) if i not in used), None)
                if free is None:
                    raise DiscussionError("capacity_exceeded")
                conn.execute("UPDATE mc_discussion_members SET status='joining',seat=? WHERE run_id=? AND member_id=?", (free, run_id, member_id(ref)))
            else:
                rows = conn.execute("SELECT seat,status FROM mc_discussion_members WHERE run_id=?", (run_id,)).fetchall()
                if len(rows) >= MAX_CATALOG_MEMBERS:
                    raise DiscussionError("member_history_limit")
                used = {row["seat"] for row in rows if row["status"] != "removed"}
                free = next((i for i in range(run["initial"]["seat_plan"]["capacity"]) if i not in used), None)
                if free is None:
                    raise DiscussionError("capacity_exceeded")
                _add_member(conn, run_id, item, ordinal=len(rows), seat=free)
            return dict(conn.execute("SELECT * FROM mc_discussion_members WHERE run_id=? AND member_id=?", (run_id, member_id(ref))).fetchone())

    def set_member_status(self, run_id: str, mid: str, status: str) -> None:
        if status not in {"active", "removing", "removed"}:
            raise DiscussionError("invalid_member_status")
        with transaction(self.connect(), immediate=True) as conn:
            row = conn.execute("SELECT * FROM mc_discussion_members WHERE run_id=? AND member_id=?", (run_id, mid)).fetchone()
            if row is None:
                raise DiscussionError("member_not_found")
            if row["status"] == status:
                return
            conn.execute("UPDATE mc_discussion_members SET status=? WHERE run_id=? AND member_id=?", (status, run_id, mid))
            if status == "removed":
                conn.execute("DELETE FROM mc_discussion_instance_claims WHERE run_id=? AND install_id=? AND instance_id=?",
                             (run_id, row["install_id"], row["instance_id"]))
            _advance(conn, _run(conn, run_id))

    def report_error(self, run_id: str, reason: str) -> None:
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id)
            if run.get("error") != reason:
                conn.execute("UPDATE mc_discussion_runs SET error=? WHERE run_id=?", (reason, run_id))
                _advance(conn, run)

    def commands(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute("""SELECT command_key,operation,state,created_at
                FROM mc_discussion_commands WHERE run_id=? ORDER BY created_at DESC LIMIT 64""", (run_id,))]

    def end(self, run_id: str) -> None:
        """Only the service calls this AFTER proving no attempt remains alive."""
        with transaction(self.connect(), immediate=True) as conn:
            run = _run(conn, run_id)
            if run["phase"] == "ended":
                return
            if run["phase"] != "ending":
                raise DiscussionError("end_not_requested")
            conn.execute("DELETE FROM mc_discussion_table_claims WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM mc_discussion_instance_claims WHERE run_id=?", (run_id,))
            _advance(conn, run, phase="ended")
