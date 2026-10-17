"""The Lens store: one SQLite file per home, ``HERMES_HOME/lens/lens.sqlite3`` (WAL).

Plan ``eternia-lens-in-hermes.md`` §3 (``store.py``). One writer: the serve that
owns the home (the poller starts only on the socket owner), plus the RPC verbs in
that same process.

Tables: ``monitors`` (state, the sealed body + digest + revision, the open draft),
``observations`` (raw; a recorded gap is a row with ``value`` NULL and a typed
``reason``), ``rollups`` (one row per feed-minute, written by retention),
``episodes`` (the Episode JSON by id).

Monitor lifecycle: ``create`` writes a DRAFT (a validated manifest, not yet
running); ``seal`` freezes the draft as the next revision; ``enable`` / ``pause``
switch polling of the sealed revision; ``retire`` stops it for good (its data
stays). Capacity is refused, never made by eviction (W13): at most
:data:`MAXIMUM_MONITORS` monitors that are not retired.

``HERMES_HOME`` is resolved when a store is constructed, never at import.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, UTC
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .episode import Episode
from .feed import Observation
from .manifest import read_manifest
from .seal import SealedManifest, seal_manifest
from .wire_value import canonical_bytes

__layer__ = "stores"

MAXIMUM_MONITORS = 64
_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitors (
  monitor_id TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
  digest TEXT, body BLOB, draft BLOB, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
  monitor_id TEXT NOT NULL, feed_id TEXT NOT NULL, sequence INTEGER NOT NULL,
  observed_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL, value REAL, reason TEXT NOT NULL,
  http_status INTEGER, PRIMARY KEY (monitor_id, feed_id, sequence));
CREATE INDEX IF NOT EXISTS observations_by_time ON observations (monitor_id, feed_id, observed_ms);
CREATE TABLE IF NOT EXISTS feed_sequences (
  monitor_id TEXT NOT NULL, feed_id TEXT NOT NULL, last INTEGER NOT NULL, PRIMARY KEY (monitor_id, feed_id));
CREATE TABLE IF NOT EXISTS rollups (
  monitor_id TEXT NOT NULL, feed_id TEXT NOT NULL, minute_ms INTEGER NOT NULL, samples INTEGER NOT NULL,
  gaps INTEGER NOT NULL, minimum REAL, maximum REAL, total REAL,
  PRIMARY KEY (monitor_id, feed_id, minute_ms));
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, rule_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
  state TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS episodes_by_rule ON episodes (monitor_id, rule_id, ordinal);
"""


class MonitorState(str, Enum):
    DRAFT = "draft"
    ENABLED = "enabled"
    PAUSED = "paused"
    RETIRED = "retired"


class StoreRefusal(str, Enum):
    NOT_FOUND = "monitor_not_found"
    CAPACITY = "capacity_refused"
    NO_DRAFT = "no_draft"
    NOT_SEALED = "not_sealed"
    RETIRED = "monitor_retired"


class LensStoreError(ValueError):
    def __init__(self, code: StoreRefusal) -> None:
        super().__init__(code.value)
        self.code = code


def default_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "lens" / "lens.sqlite3"


def to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _now_ms() -> int:
    return to_ms(datetime.now(UTC))


class LensStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()

    def exists(self) -> bool:
        return self.path.is_file()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                with conn:
                    yield conn
            finally:
                conn.close()

    # --- monitors -------------------------------------------------------------

    def _row(self, conn: sqlite3.Connection, monitor_id: str) -> sqlite3.Row | None:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM monitors WHERE monitor_id = ?", (monitor_id,)).fetchone()

    def create(self, manifest: Any) -> dict[str, Any]:
        """Write ``manifest`` as the monitor's DRAFT (new, or over an existing draft)."""

        doc = read_manifest(manifest)
        with self._db() as conn:
            row = self._row(conn, doc["monitor_id"])
            if row is None:
                live = conn.execute("SELECT COUNT(*) FROM monitors WHERE state != ?", (MonitorState.RETIRED.value,))
                if live.fetchone()[0] >= MAXIMUM_MONITORS:
                    raise LensStoreError(StoreRefusal.CAPACITY)
                conn.execute("INSERT INTO monitors (monitor_id, state, draft, updated_ms) VALUES (?, ?, ?, ?)",
                             (doc["monitor_id"], MonitorState.DRAFT.value, canonical_bytes(doc), _now_ms()))
            elif row["state"] == MonitorState.RETIRED.value:
                raise LensStoreError(StoreRefusal.RETIRED)
            else:
                conn.execute("UPDATE monitors SET draft = ?, updated_ms = ? WHERE monitor_id = ?",
                             (canonical_bytes(doc), _now_ms(), doc["monitor_id"]))
        return self.get(doc["monitor_id"])

    def seal(self, monitor_id: str) -> dict[str, Any]:
        with self._db() as conn:
            row = self._required(conn, monitor_id)
            if row["draft"] is None:
                raise LensStoreError(StoreRefusal.NO_DRAFT)
            sealed = seal_manifest(json.loads(row["draft"]), revision=int(row["revision"]) + 1)
            conn.execute("UPDATE monitors SET revision = ?, digest = ?, body = ?, draft = NULL, updated_ms = ? "
                         "WHERE monitor_id = ?", (sealed.revision, sealed.digest, sealed.body, _now_ms(), monitor_id))
        return self.get(monitor_id)

    def set_state(self, monitor_id: str, state: MonitorState) -> dict[str, Any]:
        with self._db() as conn:
            row = self._required(conn, monitor_id)
            if row["state"] == MonitorState.RETIRED.value:
                raise LensStoreError(StoreRefusal.RETIRED)
            if state is not MonitorState.RETIRED and row["body"] is None:
                raise LensStoreError(StoreRefusal.NOT_SEALED)
            conn.execute("UPDATE monitors SET state = ?, updated_ms = ? WHERE monitor_id = ?",
                         (state.value, _now_ms(), monitor_id))
        return self.get(monitor_id)

    def _required(self, conn: sqlite3.Connection, monitor_id: str) -> sqlite3.Row:
        row = self._row(conn, monitor_id)
        if row is None:
            raise LensStoreError(StoreRefusal.NOT_FOUND)
        return row

    def sealed(self, monitor_id: str) -> SealedManifest | None:
        with self._db() as conn:
            row = self._required(conn, monitor_id)
        if row["body"] is None:
            return None
        return SealedManifest(monitor_id=monitor_id, revision=int(row["revision"]), digest=row["digest"],
                              body=bytes(row["body"]))

    def get(self, monitor_id: str) -> dict[str, Any]:
        with self._db() as conn:
            row = self._required(conn, monitor_id)
        return self._summary(row)

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        sealed = None
        if row["body"] is not None:
            sealed = SealedManifest(monitor_id=row["monitor_id"], revision=int(row["revision"]),
                                    digest=row["digest"], body=bytes(row["body"]))
        return {
            "monitor_id": row["monitor_id"],
            "state": row["state"],
            "sealed": None if sealed is None else {**sealed.reference(), "manifest": sealed.manifest()},
            "draft": None if row["draft"] is None else json.loads(row["draft"]),
            "updated_at_ms": int(row["updated_ms"]),
        }

    def monitors(self, *, states: tuple[MonitorState, ...] | None = None) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        with self._db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM monitors ORDER BY monitor_id").fetchall()
        wanted = None if states is None else {s.value for s in states}
        return [self._summary(row) for row in rows if wanted is None or row["state"] in wanted]

    # --- observations ---------------------------------------------------------

    def record(self, monitor_id: str, feed_id: str, *, observed_at: datetime, received_at: datetime,
               value: float | None, reason: str, http_status: int | None = None) -> Observation:
        """Append one observation (``value`` None is a recorded gap). Sequence is per feed."""

        with self._db() as conn:
            # The counter outlives retention, so a sequence is never reused after a fold.
            conn.execute("INSERT INTO feed_sequences VALUES (?, ?, 1) ON CONFLICT (monitor_id, feed_id) "
                         "DO UPDATE SET last = last + 1", (monitor_id, feed_id))
            sequence = int(conn.execute("SELECT last FROM feed_sequences WHERE monitor_id = ? AND feed_id = ?",
                                        (monitor_id, feed_id)).fetchone()[0])
            conn.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (monitor_id, feed_id, sequence, to_ms(observed_at), to_ms(received_at), value, reason,
                          http_status))
        return Observation(monitor_id=monitor_id, feed_id=feed_id, sequence=sequence, observed_at=observed_at,
                           received_at=received_at, value=value, gap=value is None)

    def observations(self, monitor_id: str, feed_id: str, *, start: datetime, end: datetime,
                     limit: int = 100_000) -> list[dict[str, Any]]:
        """Raw rows over ``[start, end)``, oldest first, each with its typed reason."""

        if not self.exists():
            return []
        with self._db() as conn:
            rows = conn.execute(
                "SELECT sequence, observed_ms, received_ms, value, reason, http_status FROM observations "
                "WHERE monitor_id = ? AND feed_id = ? AND observed_ms >= ? AND observed_ms < ? "
                "ORDER BY observed_ms, sequence LIMIT ?",
                (monitor_id, feed_id, to_ms(start), to_ms(end), int(limit))).fetchall()
        return [
            {"monitor_id": monitor_id, "feed_id": feed_id, "sequence": seq, "observed_ms": obs, "received_ms": rec,
             "value": value, "gap": value is None, "reason": reason, "http_status": status}
            for seq, obs, rec, value, reason, status in rows
        ]

    def latest(self, monitor_id: str, feed_id: str) -> dict[str, Any] | None:
        if not self.exists():
            return None
        with self._db() as conn:
            row = conn.execute(
                "SELECT sequence, observed_ms, value, reason, http_status FROM observations "
                "WHERE monitor_id = ? AND feed_id = ? ORDER BY sequence DESC LIMIT 1", (monitor_id, feed_id)).fetchone()
        if row is None:
            return None
        seq, obs, value, reason, status = row
        return {"monitor_id": monitor_id, "feed_id": feed_id, "sequence": seq, "observed_ms": obs, "value": value,
                "gap": value is None, "reason": reason, "http_status": status}

    def rollups(self, monitor_id: str, feed_id: str) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        with self._db() as conn:
            rows = conn.execute("SELECT minute_ms, samples, gaps, minimum, maximum, total FROM rollups "
                                "WHERE monitor_id = ? AND feed_id = ? ORDER BY minute_ms",
                                (monitor_id, feed_id)).fetchall()
        return [{"minute_ms": m, "samples": s, "gaps": g, "min": lo, "max": hi, "sum": t}
                for m, s, g, lo, hi, t in rows]

    def connection(self):
        """The guarded connection, for retention (the one other writer of these tables)."""

        return self._db()

    # --- episodes -------------------------------------------------------------

    def latest_episode(self, monitor_id: str, rule_id: str) -> Episode | None:
        with self._db() as conn:
            row = conn.execute("SELECT body FROM episodes WHERE monitor_id = ? AND rule_id = ? "
                               "ORDER BY ordinal DESC LIMIT 1", (monitor_id, rule_id)).fetchone()
        return None if row is None else Episode.from_json(json.loads(row[0]))

    def save_episode(self, episode: Episode) -> None:
        with self._db() as conn:
            conn.execute("INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, ?, ?, ?)",
                         (episode.id, episode.monitor_id, episode.rule_id, episode.ordinal, episode.state.value,
                          json.dumps(episode.to_json(), sort_keys=True)))

    def episodes(self, *, monitor_id: str | None = None, states: tuple[str, ...] | None = None,
                 limit: int = 256) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        sql, args = "SELECT body FROM episodes", []
        clauses = []
        if monitor_id is not None:
            clauses.append("monitor_id = ?")
            args.append(monitor_id)
        if states:
            clauses.append(f"state IN ({','.join('?' * len(states))})")
            args.extend(states)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY monitor_id, rule_id, ordinal DESC LIMIT ?"
        args.append(int(limit))
        with self._db() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [json.loads(row[0]) for row in rows]
