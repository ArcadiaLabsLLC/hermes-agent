"""The ``feed_shapes`` table: per feed, the last KNOWN-GOOD skeleton and the newest DIFFERENT one (W1).

Plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §1 decisions 1 and 3. A new module beside
``store.py`` (that file sits under its ADR 0007 ceiling), opened through
:meth:`~agent_runtime.lens.store.LensStore.connection` so it shares the store's lock and file.

One row per ``(monitor_id, feed_id)``:

* ``good_fingerprint`` / ``good_skeleton`` — the newest read that produced a value;
* ``other_fingerprint`` / ``other_skeleton`` — the newest skeleton that differs from it (NULL once a
  good read answers in that same shape), so a repair turn sees what changed;
* ``last_fingerprint`` — the newest read's own fingerprint (NULL when that read had no skeleton:
  a body that is not JSON).

Skeletons are canonical JSON of at most ``shapes.MAXIMUM_SKELETON_BYTES``; they carry key names and
types, never a value. :func:`feed_broken` is decision 3 over the stored facts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .shapes import SHAPE_REASONS, BROKEN_AFTER_READS, Skeleton, canonical_skeleton, fingerprint, source_broken
from .store import LensStore, to_ms

__layer__ = "stores"

_SCHEMA = """CREATE TABLE IF NOT EXISTS feed_shapes (
  monitor_id TEXT NOT NULL, feed_id TEXT NOT NULL, good_fingerprint TEXT, good_skeleton TEXT,
  other_fingerprint TEXT, other_skeleton TEXT, last_fingerprint TEXT, updated_ms INTEGER NOT NULL,
  PRIMARY KEY (monitor_id, feed_id))"""
_COLUMNS = ("good_fingerprint", "good_skeleton", "other_fingerprint", "other_skeleton", "last_fingerprint",
            "updated_ms")
#: Rows that are not a read of the source (the watcher could not ask), skipped by the consecutive count.
UNREAD_REASONS = frozenset({"watcher_offline"})


def record_shape(store: LensStore, monitor_id: str, feed_id: str, *, shape: Skeleton | None, answered: bool,
                 reason: str, at: datetime) -> bool:
    """Fold one typed read into the feed's row. A read with no skeleton and no shape reason (a
    timeout, a refused address) tells nothing about shape and writes nothing. True when written."""

    if shape is None and reason not in SHAPE_REASONS:
        return False
    current = feed_shape(store, monitor_id, feed_id) or dict.fromkeys(_COLUMNS)
    latest = None if shape is None else fingerprint(shape)
    row = {**current, "last_fingerprint": latest, "updated_ms": to_ms(at)}
    if answered and shape is not None:
        row.update(good_fingerprint=latest, good_skeleton=canonical_skeleton(shape))
        if row["other_fingerprint"] == latest:
            row.update(other_fingerprint=None, other_skeleton=None)
    elif shape is not None and latest != row["good_fingerprint"]:
        row.update(other_fingerprint=latest, other_skeleton=canonical_skeleton(shape))
    with store.connection() as conn:
        conn.execute(_SCHEMA)
        conn.execute(f"INSERT OR REPLACE INTO feed_shapes (monitor_id, feed_id, {', '.join(_COLUMNS)}) "
                     f"VALUES (?, ?, {', '.join('?' * len(_COLUMNS))})",
                     (monitor_id, feed_id, *(row[column] for column in _COLUMNS)))
    return True


def feed_shape(store: LensStore, monitor_id: str, feed_id: str) -> dict[str, Any] | None:
    """The feed's row, or None when no read has told its shape."""

    if not store.exists():
        return None
    with store.connection() as conn:
        conn.execute(_SCHEMA)
        row = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM feed_shapes WHERE monitor_id = ? AND feed_id = ?",
                           (monitor_id, feed_id)).fetchone()
    return None if row is None else dict(zip(_COLUMNS, row))


def feed_broken(store: LensStore, monitor_id: str, feed_id: str) -> bool:
    """Decision 3 over the feed's newest :data:`~agent_runtime.lens.shapes.BROKEN_AFTER_READS` reads."""

    if not store.exists():
        return False
    unread = sorted(UNREAD_REASONS)
    with store.connection() as conn:
        rows = conn.execute(
            f"SELECT reason FROM observations WHERE monitor_id = ? AND feed_id = ? "
            f"AND reason NOT IN ({', '.join('?' * len(unread))}) ORDER BY sequence DESC LIMIT ?",
            (monitor_id, feed_id, *unread, BROKEN_AFTER_READS)).fetchall()
    shape = feed_shape(store, monitor_id, feed_id) or {}
    return source_broken([row[0] for row in reversed(rows)], latest_fingerprint=shape.get("last_fingerprint"),
                         known_good_fingerprint=shape.get("good_fingerprint"))
