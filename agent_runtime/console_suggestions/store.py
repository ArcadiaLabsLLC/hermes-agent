"""Bounded derived payloads and durable attempt receipts, never chat history."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from agent_runtime.serve_registry import default_process_probe
from .settings import SuggestionRefused

__layer__ = "stores"


def attempt_key(subject: dict, source: dict, revision: str) -> str:
    return hashlib.sha256(json.dumps([subject, source["source_turn_id"], source["source_revision"], revision, 1],
                                    sort_keys=True).encode()).hexdigest()


class SuggestionStore:
    def __init__(self, path: Path, *, clock=time.time, receipt_limit=4096, payload_limit=256):
        self.path = path
        self.clock = clock
        self.receipt_limit = receipt_limit
        self.payload_limit = payload_limit
        self.probe = default_process_probe()
        self.pid = os.getpid()
        self.started = None

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=0.2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, subject TEXT NOT NULL, "
                       "source_time REAL NOT NULL, created REAL NOT NULL, state TEXT NOT NULL, "
                       "entry_id TEXT NOT NULL, revision INTEGER NOT NULL, text TEXT, reason TEXT, "
                       "pid INTEGER, started TEXT, usage TEXT)")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _prune(self, db):
        now = self.clock()
        for row in db.execute("SELECT key,pid,started FROM attempts WHERE state='generating'").fetchall():
            alive = self.probe.alive(row["pid"])
            started = self.probe.start_time(row["pid"]) if alive else None
            if alive is False or (started is not None and json.dumps(started) != row["started"]):
                db.execute("UPDATE attempts SET state='unavailable', reason='uncertain_dispatch' WHERE key=?", (row["key"],))
        db.execute("DELETE FROM attempts WHERE state!='generating' AND source_time<?", (now - 7 * 86400,))
        db.execute("UPDATE attempts SET text=NULL WHERE source_time<?", (now - 86400,))

    def claim(self, key: str, subject: dict, source_time: float) -> str:
        if self.started is None:
            self.started = self.probe.start_time(self.pid)
        with self.transaction() as db:
            self._prune(db)
            if db.execute("SELECT 1 FROM attempts WHERE key=?", (key,)).fetchone():
                return "existing"
            if db.execute("SELECT count(*) FROM attempts").fetchone()[0] >= self.receipt_limit:
                return "capacity_limited"
            subject_key = json.dumps(subject, sort_keys=True)
            running = db.execute("SELECT subject FROM attempts WHERE state='generating'").fetchall()
            if len(running) >= 2 or any(row[0] == subject_key for row in running):
                return "capacity_limited"
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (key, subject_key, source_time, self.clock(), "generating", uuid4().hex, 1,
                        None, None, self.pid, json.dumps(self.started), None))
            return "claimed"

    def read(self, key: str) -> dict | None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM attempts WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            state = row["state"]
            result = {"state": state, "entry_id": row["entry_id"], "entry_revision": row["revision"]}
            if state == "ready":
                if row["text"] is None or self.clock() - row["source_time"] > 86400:
                    return {"state": "none", "reason": "expired"}
                result["text"] = row["text"]
            if row["reason"]:
                result["reason"] = row["reason"]
            return result

    def finish(self, key: str, *, text: str | None = None, reason: str | None = None, usage: dict | None = None):
        state = "unavailable" if reason else ("ready" if text else "none")
        with self.transaction() as db:
            db.execute("UPDATE attempts SET state=?,text=?,reason=?,usage=? WHERE key=? AND state='generating'",
                       (state, text, reason or (None if text else "no_useful_suggestion"),
                        json.dumps(usage) if usage else None, key))
            db.execute("UPDATE attempts SET text=NULL WHERE key IN (SELECT key FROM attempts WHERE text IS NOT NULL "
                       "ORDER BY created DESC LIMIT -1 OFFSET ?)", (self.payload_limit,))

    def dismiss(self, key: str, entry_id: str, revision: int):
        with self.transaction() as db:
            row = db.execute("SELECT entry_id,revision,state FROM attempts WHERE key=?", (key,)).fetchone()
            if row is None or row["entry_id"] != entry_id or row["revision"] != revision:
                raise SuggestionRefused("stale_revision")
            db.execute("UPDATE attempts SET state='none',text=NULL,reason='dismissed' WHERE key=?", (key,))

    def erase(self, subject: dict):
        with self.transaction() as db:
            db.execute("DELETE FROM attempts WHERE subject=?", (json.dumps(subject, sort_keys=True),))

    def erase_session(self, session_id: str):
        if not self.path.exists():
            return
        with self.transaction() as db:
            db.execute("DELETE FROM attempts WHERE json_extract(subject, '$.session_id')=?", (session_id,))
