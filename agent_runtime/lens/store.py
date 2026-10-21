"""The Lens store: one SQLite file per home, ``HERMES_HOME/lens/lens.sqlite3`` (WAL).

Plan ``eternia-lens-in-hermes.md`` §3 (``store.py``). One writer: the serve that
owns the home (the poller starts only on the socket owner), plus the RPC verbs in
that same process.

Tables: ``monitors`` (state, the sealed body + digest + revision, the open draft),
``observations`` (raw; a recorded gap is a row with ``value`` NULL and a typed
``reason``), ``rollups`` (one row per feed-minute, written by retention),
``episodes`` (the Episode JSON by id), ``receipts`` (one per Episode the exit
door admitted: the forged turn's identity, outcome and artifacts; stage L2),
``ingress_routes`` (one per push-door route: the monitor it writes, its body kind,
its mapping, its auth mode (``hmac`` | ``bearer``) and the credential reference of its
secret — never the secret; L3).

Monitor lifecycle: ``create`` writes a DRAFT (a validated manifest, not yet
running); ``seal`` freezes the draft as the next revision; ``drop_draft`` forgets a
sealed monitor's pending next revision (the sealed one keeps running); ``enable`` /
``pause`` switch polling of the sealed revision; ``retire`` stops it for good (its data
stays). Capacity is refused, never made by eviction (W13): at most
:data:`MAXIMUM_MONITORS` monitors that are not retired.

``HERMES_HOME`` is resolved when a store is constructed, never at import.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone, UTC
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .episode import Episode
from .feed import Observation
from .manifest import read_manifest
from .seal import SealedManifest, seal_manifest
from .wire_value import WireError, WireRefusal, canonical_bytes

__layer__ = "stores"

MAXIMUM_MONITORS = 64
#: Receipts are refused past this many, never made room for by eviction (W13).
MAXIMUM_RECEIPTS = 50_000
#: Push-door routes are refused past this many (W13).
MAXIMUM_ROUTES = 64
#: The longest range one series read may span (the raw window is 24 h; rollups cover 7 d).
MAXIMUM_RANGE_MS = 7 * 24 * 60 * 60 * 1000
#: The most raw rows one series read answers (``runtime.lens.range``; ``lens_read`` asks fewer).
MAXIMUM_RANGE_ROWS = 10_000
SERIES_SCHEMA = "lens-range-v1"
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
CREATE TABLE IF NOT EXISTS receipts (
  episode_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, turn_id TEXT NOT NULL, session_id TEXT,
  started_ms INTEGER NOT NULL, finished_ms INTEGER, outcome TEXT NOT NULL,
  artifact_handles TEXT NOT NULL DEFAULT '[]', files TEXT NOT NULL DEFAULT '[]', tool_admission TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS receipts_by_monitor ON receipts (monitor_id, started_ms);
CREATE TABLE IF NOT EXISTS ingress_routes (
  route_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, kind TEXT NOT NULL, secret_ref TEXT NOT NULL,
  mapping TEXT NOT NULL, created_ms INTEGER NOT NULL, auth TEXT NOT NULL DEFAULT 'hmac');
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
    RECEIPT_NOT_FOUND = "receipt_not_found"
    RECEIPTS_FULL = "receipts_full"
    ROUTE_NOT_FOUND = "route_not_found"
    ROUTES_FULL = "routes_full"
    #: ``lens_propose`` never writes over a monitor that already exists (L4.2).
    EXISTS = "monitor_exists"


#: The refusals a reader answers as "not found" (the rest are conflicts).
NOT_FOUND_REFUSALS = frozenset({StoreRefusal.NOT_FOUND, StoreRefusal.RECEIPT_NOT_FOUND,
                                StoreRefusal.ROUTE_NOT_FOUND})


class ReceiptOutcome(str, Enum):
    """How the exit door settled one Episode (plan p10-agent §5.2 decision 6).

    ``forging`` is the receipt written BEFORE the turn runs; the turn's end moves it
    to ``forged`` or ``forge_failed:<reason>`` (:data:`FORGE_FAILED_PREFIX`)."""

    FORGING = "forging"
    FORGED = "forged"
    NOTIFIED = "notified"
    SKIPPED_SEVERITY = "skipped_severity"
    CAPPED = "capped"


FORGE_FAILED_PREFIX = "forge_failed:"
#: The outcomes ``daily_turn_cap`` counts: a turn run, running, or a notification sent.
CAPPED_OUTCOMES = (ReceiptOutcome.FORGING.value, ReceiptOutcome.FORGED.value, ReceiptOutcome.NOTIFIED.value)
_RECEIPT_COLUMNS = ("episode_id", "monitor_id", "turn_id", "session_id", "started_ms", "finished_ms", "outcome",
                    "artifact_handles", "files", "tool_admission")


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
                _add_route_auth(conn)
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

    def drop_draft(self, monitor_id: str) -> dict[str, Any]:
        """Forget a SEALED monitor's pending next-revision draft; the sealed revision and its
        state stand (``runtime.lens.draft.drop``). A monitor never sealed has nothing to fall
        back to and is refused ``not_sealed`` — ``retire`` discards that proposal."""

        with self._db() as conn:
            row = self._required(conn, monitor_id)
            if row["state"] == MonitorState.RETIRED.value:
                raise LensStoreError(StoreRefusal.RETIRED)
            if row["draft"] is None:
                raise LensStoreError(StoreRefusal.NO_DRAFT)
            if row["body"] is None:
                raise LensStoreError(StoreRefusal.NOT_SEALED)
            conn.execute("UPDATE monitors SET draft = NULL, updated_ms = ? WHERE monitor_id = ?",
                         (_now_ms(), monitor_id))
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

    def latest_reads(self, monitor_id: str) -> dict[str, Any]:
        """The newest row of each feed of the monitor's SEALED manifest (``runtime.lens.latest``,
        ``lens_read``); a feed never read is None."""

        monitor = self.get(monitor_id)
        manifest = (monitor["sealed"] or {}).get("manifest") or {"feeds": []}
        return {"monitor_id": monitor_id, "latest": [self.latest(monitor_id, feed["id"]) for feed in manifest["feeds"]]}

    def series(self, monitor_id: str, feed_id: str, *, start_ms: int, end_ms: int,
               limit: int = MAXIMUM_RANGE_ROWS, rollup_limit: int | None = None) -> dict[str, Any]:
        """A bounded series over ``[start_ms, end_ms)`` with EXPLICIT gaps (``runtime.lens.range``,
        ``lens_read``): raw rows oldest first, at most ``limit`` (``truncated`` says so), and the
        feed-minute rollups in range — at most ``rollup_limit`` when one is given."""

        if not start_ms < end_ms or end_ms - start_ms > MAXIMUM_RANGE_MS:
            raise WireError(WireRefusal.INVALID_VALUE, "range_bound")
        self.get(monitor_id)
        rows = self.observations(monitor_id, feed_id, start=from_ms(start_ms), end=from_ms(end_ms), limit=limit + 1)
        rollups = [r for r in self.rollups(monitor_id, feed_id) if start_ms <= r["minute_ms"] < end_ms]
        out = {"series": SERIES_SCHEMA, "monitor_id": monitor_id, "feed_id": feed_id, "start_ms": start_ms,
               "end_ms": end_ms, "observations": rows[:limit], "truncated": len(rows) > limit, "rollups": rollups}
        if rollup_limit is not None:
            out["rollups"], out["rollups_truncated"] = rollups[-rollup_limit:], len(rollups) > rollup_limit
        return out

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

    # --- receipts -------------------------------------------------------------

    def save_receipt(self, receipt: dict[str, Any], *, episode: Episode | None = None) -> bool:
        """Insert ``receipt`` (and ``episode``, in the SAME transaction). False when the
        Episode already has one: a receipt is written once, so a turn is forged once."""

        row = _receipt_row(receipt)
        with self._db() as conn:
            if conn.execute("SELECT 1 FROM receipts WHERE episode_id = ?", (row[0],)).fetchone() is not None:
                return False
            if conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] >= MAXIMUM_RECEIPTS:
                raise LensStoreError(StoreRefusal.RECEIPTS_FULL)
            conn.execute(f"INSERT INTO receipts ({', '.join(_RECEIPT_COLUMNS)}) VALUES "
                         f"({', '.join('?' * len(_RECEIPT_COLUMNS))})", row)
            if episode is not None:
                conn.execute("INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, ?, ?, ?)",
                             (episode.id, episode.monitor_id, episode.rule_id, episode.ordinal, episode.state.value,
                              json.dumps(episode.to_json(), sort_keys=True)))
        return True

    def finish_receipt(self, episode_id: str, *, outcome: str, finished_ms: int, session_id: str | None = None,
                       artifact_handles: list[dict[str, Any]] = (), files: list[dict[str, Any]] = ()) -> dict[str, Any]:
        """Settle a ``forging`` receipt with what the turn left."""

        with self._db() as conn:
            updated = conn.execute(
                "UPDATE receipts SET outcome = ?, finished_ms = ?, session_id = ?, artifact_handles = ?, files = ? "
                "WHERE episode_id = ?",
                (str(outcome), int(finished_ms), session_id, json.dumps(list(artifact_handles), sort_keys=True),
                 json.dumps(list(files), sort_keys=True), episode_id)).rowcount
        if not updated:
            raise LensStoreError(StoreRefusal.RECEIPT_NOT_FOUND)
        return self.receipt(episode_id)

    def receipt(self, episode_id: str) -> dict[str, Any]:
        with self._db() as conn:
            row = conn.execute(f"SELECT {', '.join(_RECEIPT_COLUMNS)} FROM receipts WHERE episode_id = ?",
                               (episode_id,)).fetchone()
        if row is None:
            raise LensStoreError(StoreRefusal.RECEIPT_NOT_FOUND)
        return _receipt_json(row)

    def has_receipt(self, episode_id: str) -> bool:
        if not self.exists():
            return False
        with self._db() as conn:
            return conn.execute("SELECT 1 FROM receipts WHERE episode_id = ?", (episode_id,)).fetchone() is not None

    def receipts(self, *, monitor_id: str | None = None, limit: int = 32) -> list[dict[str, Any]]:
        """Newest first."""

        if not self.exists():
            return []
        sql, args = f"SELECT {', '.join(_RECEIPT_COLUMNS)} FROM receipts", []
        if monitor_id is not None:
            sql, args = sql + " WHERE monitor_id = ?", [monitor_id]
        with self._db() as conn:
            rows = conn.execute(sql + " ORDER BY started_ms DESC, episode_id LIMIT ?", [*args, int(limit)]).fetchall()
        return [_receipt_json(row) for row in rows]

    def receipts_today(self, monitor_id: str, now: datetime) -> int:
        """Receipts that spent this monitor's ``daily_turn_cap`` on ``now``'s UTC day."""

        if not self.exists():
            return 0
        day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = to_ms(day), to_ms(day + timedelta(days=1))
        with self._db() as conn:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM receipts WHERE monitor_id = ? AND started_ms >= ? AND started_ms < ? "
                f"AND outcome IN ({', '.join('?' * len(CAPPED_OUTCOMES))})",
                (monitor_id, start, end, *CAPPED_OUTCOMES)).fetchone()[0])

    # --- ingress routes (L3) --------------------------------------------------

    def save_route(self, route: dict[str, Any]) -> None:
        with self._db() as conn:
            if conn.execute("SELECT COUNT(*) FROM ingress_routes").fetchone()[0] >= MAXIMUM_ROUTES:
                raise LensStoreError(StoreRefusal.ROUTES_FULL)
            conn.execute(f"INSERT INTO ingress_routes ({', '.join(_ROUTE_COLUMNS)}) VALUES "
                         f"({', '.join('?' * len(_ROUTE_COLUMNS))})",
                         tuple(json.dumps(route[c], sort_keys=True) if c == "mapping" else route[c]
                               for c in _ROUTE_COLUMNS))

    def route(self, route_id: str) -> dict[str, Any]:
        with self._db() as conn:
            row = conn.execute(f"SELECT {', '.join(_ROUTE_COLUMNS)} FROM ingress_routes WHERE route_id = ?",
                               (route_id,)).fetchone()
        if row is None:
            raise LensStoreError(StoreRefusal.ROUTE_NOT_FOUND)
        return _route_json(row)

    def routes(self, *, monitor_id: str | None = None) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        sql, args = f"SELECT {', '.join(_ROUTE_COLUMNS)} FROM ingress_routes", []
        if monitor_id is not None:
            sql, args = sql + " WHERE monitor_id = ?", [monitor_id]
        with self._db() as conn:
            rows = conn.execute(sql + " ORDER BY created_ms, route_id", args).fetchall()
        return [_route_json(row) for row in rows]

    def delete_route(self, route_id: str) -> dict[str, Any]:
        route = self.route(route_id)
        with self._db() as conn:
            conn.execute("DELETE FROM ingress_routes WHERE route_id = ?", (route_id,))
        return route


_ROUTE_COLUMNS = ("route_id", "monitor_id", "kind", "secret_ref", "mapping", "created_ms", "auth")


def _add_route_auth(conn: sqlite3.Connection) -> None:
    """A store written before routes carried ``auth`` gains the column; its routes read ``hmac``."""

    if "auth" not in {row[1] for row in conn.execute("PRAGMA table_info(ingress_routes)")}:
        conn.execute("ALTER TABLE ingress_routes ADD COLUMN auth TEXT NOT NULL DEFAULT 'hmac'")


def _route_json(row: tuple[Any, ...]) -> dict[str, Any]:
    out = dict(zip(_ROUTE_COLUMNS, row))
    out["mapping"] = json.loads(out["mapping"])
    return out


def _receipt_row(receipt: dict[str, Any]) -> tuple[Any, ...]:
    values = dict(receipt)
    values["artifact_handles"] = json.dumps(list(values.get("artifact_handles") or []), sort_keys=True)
    values["files"] = json.dumps(list(values.get("files") or []), sort_keys=True)
    values.setdefault("session_id", None)
    values.setdefault("finished_ms", None)
    return tuple(values[column] for column in _RECEIPT_COLUMNS)


def _receipt_json(row: tuple[Any, ...]) -> dict[str, Any]:
    out = dict(zip(_RECEIPT_COLUMNS, row))
    out["artifact_handles"] = json.loads(out["artifact_handles"])
    out["files"] = json.loads(out["files"])
    return {"version": 1, **out}
