"""One atomic admission for spatial and non-spatial discussions."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from hermes_cli.sqlite_util import transaction

from .definition_store import DefinitionKind, _encode, _expect, _key, _required
from .definitions import ParticipantRef, identifier, plan_seats, revision
from .room_definition import RoomSpec
from .run_records import _add_member, _run
from .run_values import DiscussionError, digest, text

__layer__ = "stores"

MAX_OPEN_RUNS = 128


@dataclass(frozen=True, slots=True)
class Admission:
    initial: Mapping[str, Any]
    participants: tuple[ParticipantRef, ...]
    positions: Mapping[ParticipantRef, int]
    table_id: str | None = None


def table_admission(conn: sqlite3.Connection, workspace: str, table_id: str, expected: int) -> Admission:
    table = _required(conn, _key(DefinitionKind.TABLE, workspace, table_id))
    _expect(table, expected)
    spec = table.spec
    if len(spec.configuration.participants) < 2:
        raise DiscussionError("at_least_two_agents_required")
    if conn.execute("SELECT 1 FROM mc_discussion_table_claims WHERE workspace_id=? AND table_id=?",
                    (workspace, table_id)).fetchone():
        raise DiscussionError("table_busy")
    plan = plan_seats(spec)
    return Admission({"table": table.to_dict(), "seat_plan": {"capacity": spec.seat_count,
        "assignments": [p.to_dict() for p in plan.assignments]}},
        spec.configuration.participants, {p.participant: p.seat for p in plan.assignments}, table_id)


def room_admission(spec: RoomSpec) -> Admission:
    return Admission({"discussion": spec.to_dict()}, spec.participants,
                     {ref: index for index, ref in enumerate(spec.participants)})


def admit(connect: Callable[[], sqlite3.Connection], workspace: str, *, key: str, topic: str,
          actor_id: str, identity: Mapping[str, Any],
          load: Callable[[sqlite3.Connection], Admission],
          resolve: Callable[[ParticipantRef, str], Mapping[str, Any]]) -> dict[str, Any]:
    identifier(workspace, "workspace_id")
    identifier(key, "idempotency_key")
    topic = text(topic, field="topic")
    signature = digest({**identity, "topic": topic})
    with transaction(connect(), immediate=True) as conn:
        previous = conn.execute("SELECT run_id,request_digest FROM mc_discussion_runs WHERE workspace_id=? AND start_key=?",
                                (workspace, key)).fetchone()
        if previous is not None:
            if previous["request_digest"] != signature:
                raise DiscussionError("idempotency_conflict")
            return _run(conn, previous["run_id"])
        admission = load(conn)
        if conn.execute("SELECT COUNT(*) FROM mc_discussion_runs WHERE phase NOT IN ('ended','failed')").fetchone()[0] >= MAX_OPEN_RUNS:
            raise DiscussionError("too_many_open_discussions")
        catalog = [dict(resolve(ref, workspace)) for ref in admission.participants]
        run_id = "discussion-" + digest({"workspace_id": workspace, "key": key})[:24]
        now = time.time()
        conn.execute("INSERT INTO mc_discussion_runs VALUES(?,?,?,?,?,1,'initializing',?,?,?,?,?,NULL)",
                     (run_id, workspace, admission.table_id, key, signature,
                      _encode(admission.initial), topic, actor_id, now, now))
        if admission.table_id is not None:
            conn.execute("INSERT INTO mc_discussion_table_claims VALUES(?,?,?)", (workspace, admission.table_id, run_id))
        for index, (ref, item) in enumerate(zip(admission.participants, catalog, strict=True)):
            _add_member(conn, run_id, item, ordinal=index, seat=admission.positions[ref])
        return _run(conn, run_id)
