"""Lens retention: 24 h of raw observations, 7 d of minute rollups — fixed, never shortened.

Plan ``eternia-lens-in-hermes.md`` §3 (``retention.py``). A pass first FOLDS every
raw row older than :data:`RAW_RETENTION` into its feed-minute rollup (samples,
gaps, min, max, sum — a gap is counted, never averaged in), then deletes those raw
rows, then deletes rollups older than :data:`ROLLUP_RETENTION`. Folding before
deleting is the order that loses nothing inside the rollup window.

Receipts (RT-LENS-RECEIPT-RETENTION, plan ``lens-receipt-retention-2026-10-21.md`` L1)
age out after :data:`RECEIPT_RETENTION`: :func:`fold_receipts` folds them into a count
per (monitor, UTC day, outcome) in ``receipt_rollups``, deletes them and their settled
Episodes, and only after that transaction commits removes the Episodes' artifact folders —
a crash between the two leaves an orphan folder, never a live receipt whose folder is gone.
Deleting an old receipt cannot re-forge its Episode: the Episode's ``turn_id`` is the
durable "settled" mark, and the newest Episode of each rule is always kept, so an ordinal
is never reused.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .store import LensStore, to_ms

__layer__ = "stores"

RAW_RETENTION = timedelta(hours=24)
ROLLUP_RETENTION = timedelta(days=7)
#: Every receipt reader looks at "today" or the newest 32; a month keeps a month of history.
RECEIPT_RETENTION = timedelta(days=30)
#: Orphan folders one pass removes at most (bounded; a later pass continues).
ORPHAN_SWEEP_NAMES = 256
#: A folder younger than this is never an orphan: ``_forge`` makes it just before its receipt.
ORPHAN_MINIMUM_AGE = timedelta(days=1)
#: The log receipt a fold leaves (observability is a log receipt, never a wire key).
RECEIPTS_FOLDED_RECEIPT = "[LensReceiptsFolded] receipts=%d episodes=%d folders=%d"
_MINUTE_MS = 60_000
logger = logging.getLogger(__name__)

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


_FOLD_RECEIPTS = """
INSERT INTO receipt_rollups (monitor_id, day_ms, outcome, count)
SELECT monitor_id, (started_ms / 86400000) * 86400000 AS day, outcome, COUNT(*)
FROM receipts WHERE started_ms < ? GROUP BY monitor_id, day, outcome
ON CONFLICT (monitor_id, day_ms, outcome) DO UPDATE SET count = count + excluded.count
"""
#: Settled Episodes of the folded receipts; never ``active``, never the newest of its rule.
_DELETE_EPISODES = """
DELETE FROM episodes WHERE state != 'active'
  AND id IN (SELECT episode_id FROM receipts WHERE started_ms < ?)
  AND ordinal < (SELECT MAX(newest.ordinal) FROM episodes AS newest
                 WHERE newest.monitor_id = episodes.monitor_id AND newest.rule_id = episodes.rule_id)
"""


@dataclass(frozen=True, slots=True)
class ReceiptFoldReceipt:
    receipts_folded: int
    episodes_deleted: int
    folders_removed: int


@dataclass(frozen=True, slots=True)
class RetentionReceipt:
    raw_folded: int
    rollups_deleted: int
    receipts: ReceiptFoldReceipt = field(default_factory=lambda: ReceiptFoldReceipt(0, 0, 0))


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
    return RetentionReceipt(raw_folded=folded, rollups_deleted=dropped, receipts=fold_receipts(store, now))


def fold_receipts(store: LensStore, now: datetime) -> ReceiptFoldReceipt:
    """Fold receipts older than :data:`RECEIPT_RETENTION`, then remove their Episodes' folders.

    Idempotent: a second pass at the same instant moves nothing."""

    if not store.exists():
        return ReceiptFoldReceipt(0, 0, 0)
    cutoff = to_ms(now - RECEIPT_RETENTION)
    with store.connection() as conn:
        ids = [row[0] for row in conn.execute("SELECT episode_id FROM receipts WHERE started_ms < ?", (cutoff,))]
        if ids:
            conn.execute(_FOLD_RECEIPTS, (cutoff,))
            episodes = conn.execute(_DELETE_EPISODES, (cutoff,)).rowcount
            folded = conn.execute("DELETE FROM receipts WHERE started_ms < ?", (cutoff,)).rowcount
        else:
            episodes = folded = 0
        live = {row[0] for row in conn.execute("SELECT episode_id FROM receipts")}
    removed = sum(_remove_folder(episode_id) for episode_id in ids)
    removed += _sweep_orphans(live, now)
    receipt = ReceiptFoldReceipt(receipts_folded=folded, episodes_deleted=episodes, folders_removed=removed)
    if folded or removed:
        logger.info(RECEIPTS_FOLDED_RECEIPT, folded, episodes, removed)
    return receipt


def _remove_folder(episode_id: str) -> bool:
    from .artifacts import episode_folder

    try:
        folder = episode_folder(episode_id)
    except ValueError:  # not an Episode digest: there is no folder to name
        return False
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


def _sweep_orphans(live: set[str], now: datetime) -> int:
    """Folders under the episodes root whose id has no receipt (a crash between commit and removal)."""

    from .artifacts import episodes_root

    root = episodes_root()
    if not root.is_dir():
        return 0
    oldest = (now - ORPHAN_MINIMUM_AGE).timestamp()
    removed = 0
    for entry in root.iterdir():
        if removed >= ORPHAN_SWEEP_NAMES:
            break
        if entry.name in live or not entry.is_dir() or entry.stat().st_mtime >= oldest:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    return removed
