"""W6 digest windows: Episodes of one monitor owed inside one window share ONE turn.

Plan ``LENS_EXTENSIONS_2026-10-27.md`` §3 decision 3. A monitor with
``automation.digest_window_ms > 0`` opens a window when its first owed Episode reaches the
exit door; every Episode of that monitor owed before the window ends waits; at the end the
door settles them together (``trigger.LensForge._digest``).

One open window per monitor, in its own table (``digest_windows``), opened through
``LensStore.connection()``. It is CLOSED inside the same transaction that writes every
member's receipt (``LensStore.save_receipts(..., also=close_window)``), so a restart
mid-window finds the window still open and nothing settled, and a restart after the settle
finds every receipt — never a half.
"""

from __future__ import annotations

import sqlite3

from .store import LensStore
from .wire_value import canonical_digest, opaque_id

__layer__ = "stores"

_SCHEMA = ("CREATE TABLE IF NOT EXISTS digest_windows ("
           "monitor_id TEXT PRIMARY KEY, window_start_ms INTEGER NOT NULL)")


def digest_id(monitor_id: str, window_start_ms: int) -> str:
    """The digest's identity: one per monitor per window."""

    return canonical_digest({"monitor_id": opaque_id(monitor_id), "window_start_ms": int(window_start_ms)})


def open_window(store: LensStore, monitor_id: str, now_ms: int) -> int:
    """The monitor's open window's start; opened at ``now_ms`` when it has none."""

    with store.connection() as conn:
        conn.execute(_SCHEMA)
        conn.execute("INSERT OR IGNORE INTO digest_windows VALUES (?, ?)", (monitor_id, int(now_ms)))
        return int(conn.execute("SELECT window_start_ms FROM digest_windows WHERE monitor_id = ?",
                                (monitor_id,)).fetchone()[0])


def close_window(monitor_id: str):
    """The ``also`` step that closes the monitor's window inside the receipts' transaction."""

    def _close(conn: sqlite3.Connection) -> None:
        conn.execute(_SCHEMA)
        conn.execute("DELETE FROM digest_windows WHERE monitor_id = ?", (monitor_id,))

    return _close


def drop_window(store: LensStore, monitor_id: str) -> None:
    """Close a window none of whose Episodes is still owed (the next one opens afresh)."""

    with store.connection() as conn:
        close_window(monitor_id)(conn)
