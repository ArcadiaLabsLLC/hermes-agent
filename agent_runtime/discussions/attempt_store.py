"""Native-turn joins and pending human input, not a second turn journal.

A row is written before dispatch and names one hosted task generation. Its
terminal receipt is a cache of native committed truth or a pre-admission refusal.
The native journal is consulted first on recovery, including commit/callback gaps.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from gateway.hosted_rooms_common import connect
from hermes_cli.sqlite_util import transaction
from .definition_store import _encode
from .run_store import DiscussionError, digest, text

__layer__ = "stores"


def _ready(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='mc_discussion_attempts_schema'").fetchone() is None:
        return False
    rows = conn.execute("SELECT version FROM mc_discussion_attempts_schema").fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise DiscussionError("unsupported_attempt_schema")
    return True


def _initialize(conn: sqlite3.Connection) -> None:
    if _ready(conn):
        return
    conn.execute("""CREATE TABLE mc_discussion_attempts (
        run_id TEXT NOT NULL, task_id TEXT NOT NULL, generation INTEGER NOT NULL,
        member_id TEXT NOT NULL, session_id TEXT NOT NULL, continuation INTEGER NOT NULL DEFAULT 0,
        native_id TEXT NOT NULL, prompt TEXT NOT NULL,
        stage TEXT NOT NULL CHECK(stage IN ('pending','running','waiting_input','terminal','uncertain')),
        receipt_json TEXT, question_json TEXT, answer_key TEXT, answer_digest TEXT,
        owner_pid INTEGER, owner_started INTEGER,
        PRIMARY KEY(run_id,task_id,generation))""")
    conn.execute("CREATE TABLE mc_discussion_attempts_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL)")
    conn.execute("INSERT INTO mc_discussion_attempts_schema VALUES(1,1)")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for raw, key in (("receipt_json", "receipt"), ("question_json", "question")):
        value = result.pop(raw)
        result[key] = json.loads(value) if value is not None else None
    return result


def native_id(run: str, task: str, generation: int, continuation: int) -> str:
    return "room-turn-" + digest({"run": run, "task": task, "generation": generation, "continuation": continuation})[:40]


class AttemptStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        return connect(self.db_path, db_label="discussion-attempts", ready=_ready, initialize=_initialize, lock_retries=4)

    def get(self, run: str, task: str, generation: int) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            return _row(conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? AND task_id=? AND generation=?", (run, task, generation)).fetchone())

    def begin(self, run: str, task: str, generation: int, member: Mapping[str, Any], prompt: str) -> dict[str, Any]:
        with transaction(self.connect(), immediate=True) as conn:
            params = (run, task, generation)
            old = _row(conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? AND task_id=? AND generation=?", params).fetchone())
            if old is not None:
                # Continuations retain the original task but deliberately replace prompt.
                if old["member_id"] != member["member_id"] or old["session_id"] != member["session_id"]:
                    raise DiscussionError("attempt_identity_conflict")
                if old["continuation"] == 0 and old["prompt"] != prompt:
                    raise DiscussionError("attempt_payload_conflict")
                return old
            nid = native_id(run, task, generation, 0)
            conn.execute("""INSERT INTO mc_discussion_attempts
                (run_id,task_id,generation,member_id,session_id,native_id,prompt,stage)
                VALUES(?,?,?,?,?,?,?,'pending')""", (*params, member["member_id"], member["session_id"], nid, prompt))
            return _row(conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? AND task_id=? AND generation=?", params).fetchone())

    def claim(self, row: Mapping[str, Any], *, pid: int, started: int) -> bool:
        """Claim a pending turn before entering the native handler. No blind reclaim."""
        with transaction(self.connect(), immediate=True) as conn:
            return bool(conn.execute("""UPDATE mc_discussion_attempts SET stage='running',owner_pid=?,owner_started=?
                WHERE run_id=? AND task_id=? AND generation=? AND native_id=? AND stage='pending'""",
                (pid, started, row["run_id"], row["task_id"], row["generation"], row["native_id"])).rowcount)

    def update(self, row: Mapping[str, Any], *, stage: str, receipt=None, question=None) -> bool:
        if stage not in {"running", "waiting_input", "terminal", "uncertain"}:
            raise DiscussionError("invalid_attempt_stage")
        with transaction(self.connect(), immediate=True) as conn:
            changed = conn.execute("""UPDATE mc_discussion_attempts SET stage=?,receipt_json=?,question_json=?
                WHERE run_id=? AND task_id=? AND generation=? AND native_id=? AND stage!='terminal'""",
                (stage, _encode(receipt) if receipt is not None else None,
                 _encode(question) if question is not None else None,
                 row["run_id"], row["task_id"], row["generation"], row["native_id"])).rowcount
            return bool(changed)

    def answer(self, run: str, task: str, generation: int, *, expected_native_id: str, key: str, answer: str) -> dict[str, Any]:
        answer = text(answer, field="answer", max_bytes=8000)
        adigest = digest({"answer": answer, "native_id": expected_native_id})
        with transaction(self.connect(), immediate=True) as conn:
            row = _row(conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? AND task_id=? AND generation=?", (run, task, generation)).fetchone())
            if row is None:
                raise DiscussionError("attempt_not_found")
            if row["answer_key"] == key:
                if row["answer_digest"] != adigest:
                    raise DiscussionError("idempotency_conflict")
                return row
            if row["stage"] != "waiting_input" or row["native_id"] != expected_native_id:
                raise DiscussionError("clarification_changed")
            # The exact member session and new client message identity persist BEFORE dispatch.
            continuation = row["continuation"] + 1
            if continuation > 8:
                raise DiscussionError("clarification_limit")
            nid = native_id(run, task, generation, continuation)
            conn.execute("""UPDATE mc_discussion_attempts SET continuation=?,native_id=?,prompt=?,stage='pending',
                receipt_json=NULL,question_json=NULL,owner_pid=NULL,owner_started=NULL,answer_key=?,answer_digest=?
                WHERE run_id=? AND task_id=? AND generation=?""",
                (continuation, nid, answer, key, adigest, run, task, generation))
            return _row(conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? AND task_id=? AND generation=?", (run, task, generation)).fetchone())

    def rows(self, run: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            return [_row(row) for row in conn.execute("SELECT * FROM mc_discussion_attempts WHERE run_id=? ORDER BY task_id,generation", (run,))]
