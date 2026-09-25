"""The one database and everything that only reads it: the path, connect,
schema + migrations, the always-close transaction, the read-only query and the
six projections, and the process identity a row is stamped with (plus the
store's event append).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import (
    _SELECT,
    _TABLE,
    DELIVERY_DROPPED,
    DELIVERY_PENDING,
    STATE_COMPLETED,
    STATE_ERROR,
    STATE_RUNNING,
    STATE_UNKNOWN,
    _row_to_dict,
    _text,
)

__layer__ = "stores"

logger = logging.getLogger(__name__)


_DB_LOCK = threading.Lock()


def dispatch_db_path() -> Path:
    """The store's database — ONE authority, resolved through ONE resolver.

    Deliberately the same ``state.db`` the delegation lane writes: one
    background-work database per home, two tables. A second file would need its
    own fingerprint entry in the serve read-model cache and its own backup
    story, for no isolation this lane actually needs.
    """

    from agent_runtime.profile_home import get_hermes_background_work_home

    return Path(get_hermes_background_work_home()) / "state.db"


def _connect() -> sqlite3.Connection:
    path = dispatch_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        _initialize_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _initialize_schema(conn: sqlite3.Connection) -> None:
    from hermes_state import apply_wal_with_fallback

    apply_wal_with_fallback(conn, db_label="state.db (mission_chat_dispatches)")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
            dispatch_id TEXT PRIMARY KEY,
            sender_session_id TEXT NOT NULL DEFAULT '',
            sender_persona_id TEXT NOT NULL DEFAULT '',
            target_persona TEXT NOT NULL DEFAULT '',
            target_instance_id TEXT NOT NULL DEFAULT '',
            target_session_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            ask TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,
            notify_operator INTEGER NOT NULL DEFAULT 0,
            dispatched_at REAL NOT NULL,
            completed_at REAL,
            updated_at REAL NOT NULL,
            result_json TEXT,
            delivery_state TEXT NOT NULL DEFAULT 'pending',
            delivery_attempts INTEGER NOT NULL DEFAULT 0,
            delivered_at REAL,
            delivery_claim TEXT,
            delivery_claimed_at REAL,
            owner_pid INTEGER,
            owner_started_at INTEGER,
            relay_chain_json TEXT,
            delivery_error TEXT,
            remote_install_id TEXT NOT NULL DEFAULT ''
        )"""
    )
    # CREATE TABLE IF NOT EXISTS does nothing to a store that already exists, so
    # a column added after the first release needs an explicit migration — or it
    # is absent on every machine that ever ran the older build, and the reads
    # below raise there while a fresh install stays green. That is the worst
    # possible place to discover a schema change.
    _add_missing_column(conn, "delivery_error", "TEXT")
    # Gateway Stage 7. A column and not a key inside ``result_json``, because
    # this fact is true from the moment the row is WRITTEN and the result blob
    # is not written until the turn ends: an operator watching Activity has to
    # be able to see that a dispatch left this machine while it is still
    # running, which is precisely the window in which they would otherwise
    # wonder why nothing is happening. Empty string means local, which is what
    # every row that predates this line already means.
    _add_missing_column(conn, "remote_install_id", "TEXT NOT NULL DEFAULT ''")


def _add_missing_column(conn: sqlite3.Connection, name: str, decl: str) -> None:
    try:
        existing = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({_TABLE})")
        }
    except Exception:  # pragma: no cover - defensive
        return
    if name in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {decl}")
    except sqlite3.OperationalError:  # pragma: no cover - lost a concurrent race
        pass


class _transaction:
    """Open, commit/rollback, and ALWAYS close.

    ``sqlite3.Connection.__exit__`` commits the transaction but does NOT close
    the connection, so ``with _connect()`` leaks a handle — and its WAL/SHM file
    descriptors — on every write, deferring the close to the garbage collector.
    On a long-running serve process that eventually exhausts the fd limit; the
    delegation lane learned this the expensive way (#69567).
    """

    def __enter__(self) -> sqlite3.Connection:
        self._conn = _connect()
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._conn.__exit__(exc_type, exc, tb)
        finally:
            self._conn.close()


def _supervised_here() -> set[str]:
    """Dispatch ids a live supervisor in THIS process is still answering for.

    Read through the tools lane's own registry rather than duplicated here, so
    "who owns this row right now" has exactly one answer. Imported lazily and
    fails open to an empty set: a store that cannot see the registry sweeps
    exactly as it did before, which is the previous behaviour rather than a new
    hazard.
    """

    try:
        from tools.agent_chat_dispatch import supervised_dispatch_ids

        return supervised_dispatch_ids()
    except Exception:  # pragma: no cover - defensive
        return set()


def _owner_identity() -> tuple[int, int | None]:
    """``(pid, start_ticks)`` for THIS process.

    The start time is what turns a PID into an identity. A ``None`` here is an
    unreadable probe, not a claim of any kind, and every consumer treats it as
    "cannot prove" rather than "not ours".
    """

    try:
        from gateway.status import get_process_start_time

        return os.getpid(), get_process_start_time(os.getpid())
    except Exception:  # pragma: no cover - defensive
        return os.getpid(), None


def _emit(event_type: str, **payload: Any) -> None:
    """Append the store event for a mutation. Best effort, never silent.

    Mirrors ``agent_runtime.store._append_store_event``: the EventLog is the
    change feed every watermark-gated consumer reads, so a mutation without one
    is invisible; but a broken event log must not fail the durable write that
    already happened.
    """

    try:
        from hermes_time import now

        from ..events import EventLog
        from ..models import Event

        body = {key: value for key, value in payload.items() if value is not None}
        EventLog().append(Event(now(), event_type, None, None, None, body))
    except Exception:
        logger.warning("dispatch store event append failed: %s", event_type, exc_info=True)


def _query(where: str, params: tuple) -> list[dict[str, Any]]:
    path = dispatch_db_path()
    if not path.exists():
        # Read-only by contract: a projection asking "what is running" must
        # never CREATE the background-work database as a side effect.
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except Exception:
        return []
    try:
        rows = conn.execute(f"{_SELECT} {where}", params).fetchall()
    except sqlite3.OperationalError as exc:
        # A state.db that predates this table is a store with no dispatches, not
        # an unreadable store.
        if "no such table" not in str(exc).lower():
            raise
        rows = []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return [_row_to_dict(row) for row in rows]


def running_dispatches(limit: int = 200) -> list[dict[str, Any]]:
    """In-flight dispatches — the ``running_work`` kind=dispatch lane."""

    return _query(
        "WHERE state=? ORDER BY dispatched_at LIMIT ?", (STATE_RUNNING, int(limit))
    )


def undeliverable_dispatches(
    limit: int = 50, *, since: float | None = None
) -> list[dict[str, Any]]:
    """Completions the sender will NEVER be told about, newest first.

    Three paths reach here and none of them forges a delivery turn: no sender
    session, an unresolvable sender, and the attempt cap. Each is an answer that
    was produced and then abandoned — the single worst outcome this lane can
    have, and until now its only trace was an EventLog row nothing reads.

    Surfaced so the Activity projection can show it. ``since`` bounds the window
    (the operator cares that work died, not that it died last week); the drop
    reason travels on the row rather than only in the event, so what is rendered
    can say WHY.
    """

    cutoff = float(since) if since is not None else 0.0
    return _query(
        "WHERE delivery_state = ? AND updated_at >= ? ORDER BY updated_at DESC LIMIT ?",
        (DELIVERY_DROPPED, cutoff, int(limit)),
    )


def pending_deliveries(limit: int = 50) -> list[dict[str, Any]]:
    """Completed dispatches the sender has NOT yet been told about."""

    return _query(
        "WHERE state != ? AND delivery_state = ? ORDER BY completed_at, dispatch_id LIMIT ?",
        (STATE_RUNNING, DELIVERY_PENDING, int(limit)),
    )


def get_dispatch(dispatch_id: str) -> dict[str, Any] | None:
    rows = _query("WHERE dispatch_id=?", (str(dispatch_id),))
    return rows[0] if rows else None


def list_dispatches(
    *, sender_session_id: str = "", limit: int = 25
) -> list[dict[str, Any]]:
    """The CALLER's dispatches, newest first.

    Scoped by the sender's chat-root session id — the same identity the delivery
    lane routes on — so ``agent_chat_dispatches`` can only ever list work the
    caller actually dispatched. An empty scope lists nothing rather than
    everything: a missing caller identity is a reason to show less, never more.
    """

    scope = _text(sender_session_id, 240)
    if not scope:
        return []
    bounded = max(1, min(int(limit or 25), 100))
    return _query(
        "WHERE sender_session_id=? ORDER BY dispatched_at DESC LIMIT ?",
        (scope, bounded),
    )


def remote_media_completions(*, limit: int = 128) -> list[dict[str, Any]]:
    """Every stored cross-install completion that carried a media map.

    Stage P4. The source ``media_handles.build_media_scope`` folds into the
    REMOTE half of this install's media scope — and it is a DERIVATION from the
    store that already knows the answer, never a registry, for exactly the
    reason the local half is derived from the chat mirror: a second copy of "what
    pictures exist" drifts, and drifts toward promising bytes nobody can produce.

    Unscoped by sender, unlike :func:`list_dispatches`, and the asymmetry is
    deliberate. That verb answers an AGENT asking about its own work, where a
    missing caller identity is a reason to show less. This one answers the
    install's own media scope, whose reachability rule is one layer out and
    already stated: a console caller may read this install's chats, the forged
    replies are in them, and the pictures those replies declare are therefore in
    scope. Scoping by sender here would hide a picture from the operator looking
    at the very message that declares it.

    Newest first, so a truncating fold keeps what a client is most likely
    rendering — ``build_media_scope``'s ordering rule, applied to the second
    source.
    """

    bounded = max(1, min(int(limit or 128), 500))
    rows = _query(
        "WHERE remote_install_id != '' AND state IN (?, ?, ?) "
        "ORDER BY completed_at DESC LIMIT ?",
        (STATE_COMPLETED, STATE_ERROR, STATE_UNKNOWN, bounded),
    )
    completions: list[dict[str, Any]] = []
    for row in rows:
        result = row.get("result") or {}
        if not isinstance(result, dict):
            continue
        media = result.get("media")
        if not isinstance(media, list) or not media:
            continue
        completions.append(
            {
                "dispatch_id": row.get("dispatch_id"),
                "peer_install_id": row.get("remote_install_id") or "",
                "media": media,
            }
        )
    return completions
