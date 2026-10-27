"""The receipts table's row shape and the receipt transaction's writes (row ``RT-LENS-STORE-AT-CEILING``).

Beside ``store.py`` (that file sat at its ADR 0007 ceiling). ``LensStore.save_receipts`` runs the
transaction and its fold-and-retry; this module owns what one attempt writes inside it: each
receipt row with its Episode (:func:`insert_receipts`), or — still full after a fold — each
Episode settled with no row (:func:`settle_receipts_full`), and the row <-> JSON codec.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace
from typing import Any

from .episode import Episode
from .store_episode_rows import door_owned, episode_state_moves, write_episode

__layer__ = "stores"

logger = logging.getLogger("agent_runtime.lens.store")

RECEIPT_COLUMNS = ("episode_id", "monitor_id", "turn_id", "session_id", "started_ms", "finished_ms", "outcome",
                   "artifact_handles", "files", "tool_admission", "digest_id")
#: The log receipt a fence refusal leaves (observability is a log receipt, never a wire key).
RECEIPTS_FULL_RECEIPT = "[LensReceiptsFull] monitor=%s episode=%s"


def insert_receipts(conn: sqlite3.Connection, rows: list[tuple], pairs: list[tuple[dict[str, Any], Episode | None]]
                    ) -> list[bool]:
    """Insert each receipt row with its Episode; per pair, whether the Episode's state moved."""

    moved: list[bool] = []
    for row, (_, episode) in zip(rows, pairs):
        conn.execute(f"INSERT INTO receipts ({', '.join(RECEIPT_COLUMNS)}) VALUES "
                     f"({', '.join('?' * len(RECEIPT_COLUMNS))})", row)
        moved.append(episode is not None and episode_state_moves(conn, episode))
        if episode is not None:
            write_episode(conn, door_owned(conn, episode))
    return moved


def settle_receipts_full(conn: sqlite3.Connection, rows: list[tuple],
                         pairs: list[tuple[dict[str, Any], Episode | None]], *, turn_id: str) -> None:
    """Still full after a fold: each Episode settles as ``turn_id`` (``receipts_full``) and no receipt row is written."""

    for row, (_, episode) in zip(rows, pairs):
        if episode is not None:
            write_episode(conn, door_owned(conn, replace(episode, turn_id=turn_id)))
        logger.warning(RECEIPTS_FULL_RECEIPT, row[1], row[0])


def receipt_row(receipt: dict[str, Any]) -> tuple[Any, ...]:
    values = dict(receipt)
    values["artifact_handles"] = json.dumps(list(values.get("artifact_handles") or []), sort_keys=True)
    values["files"] = json.dumps(list(values.get("files") or []), sort_keys=True)
    values.setdefault("session_id", None)
    values.setdefault("finished_ms", None)
    values.setdefault("digest_id", None)
    return tuple(values[column] for column in RECEIPT_COLUMNS)


def receipt_json(row: tuple[Any, ...]) -> dict[str, Any]:
    out = dict(zip(RECEIPT_COLUMNS, row))
    out["artifact_handles"] = json.loads(out["artifact_handles"])
    out["files"] = json.loads(out["files"])
    return {"version": 1, **out}
