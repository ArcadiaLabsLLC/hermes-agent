"""Lens retention: 24 h of raw observations, 7 d of minute rollups — fixed, never shortened.

Plan ``eternia-lens-in-hermes.md`` §3 (``retention.py``). A pass first FOLDS every
raw row older than :data:`RAW_RETENTION` into its feed-minute rollup (samples,
gaps, min, max, sum — a gap is counted, never averaged in), then deletes those raw
rows, then deletes rollups older than :data:`ROLLUP_RETENTION`. Folding before
deleting is the order that loses nothing inside the rollup window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .store import LensStore, to_ms

__layer__ = "stores"

RAW_RETENTION = timedelta(hours=24)
ROLLUP_RETENTION = timedelta(days=7)
_MINUTE_MS = 60_000

_FOLD = """
INSERT INTO rollups (monitor_id, feed_id, minute_ms, samples, gaps, minimum, maximum, total)
SELECT monitor_id, feed_id, (observed_ms / 60000) * 60000 AS minute,
       SUM(value IS NOT NULL), SUM(value IS NULL), MIN(value), MAX(value), TOTAL(value)
FROM observations WHERE observed_ms < ? GROUP BY monitor_id, feed_id, minute
ON CONFLICT (monitor_id, feed_id, minute_ms) DO UPDATE SET
  samples = samples + excluded.samples, gaps = gaps + excluded.gaps,
  minimum = CASE WHEN minimum IS NULL THEN excluded.minimum
                 WHEN excluded.minimum IS NULL THEN minimum ELSE MIN(minimum, excluded.minimum) END,
  maximum = CASE WHEN maximum IS NULL THEN excluded.maximum
                 WHEN excluded.maximum IS NULL THEN maximum ELSE MAX(maximum, excluded.maximum) END,
  total = total + excluded.total
"""


@dataclass(frozen=True, slots=True)
class RetentionReceipt:
    raw_folded: int
    rollups_deleted: int


def apply_retention(store: LensStore, now: datetime) -> RetentionReceipt:
    """One pass at ``now``. Idempotent: a second pass at the same instant moves nothing."""

    if not store.exists():
        return RetentionReceipt(0, 0)
    raw_cutoff = to_ms(now - RAW_RETENTION)
    rollup_cutoff = to_ms(now - ROLLUP_RETENTION)
    with store.connection() as conn:
        conn.execute(_FOLD, (raw_cutoff,))
        folded = conn.execute("DELETE FROM observations WHERE observed_ms < ?", (raw_cutoff,)).rowcount
        dropped = conn.execute("DELETE FROM rollups WHERE minute_ms < ?", (rollup_cutoff,)).rowcount
    return RetentionReceipt(raw_folded=folded, rollups_deleted=dropped)
