"""The play-session handback: the observed game records, handed back until the launcher acks them.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §2 and §3 decisions
16–18 (slice P1, row ``RT-PLAY-SESSION-HANDBACK``). The records are the game watch's own files
(``game_watch.GameRecord`` in ``paths.launcher_supervision_games_dir()``); this module only reads them out
in §2's wire shape and deletes the ones the launcher acknowledged.

* **Pending** (:func:`pending`) — every record, oldest receipt first, as ``{session_id, game_id, ended_at,
  last_seen_at, exit_code, outcome}``. Reading deletes nothing, so delivery is AT LEAST ONCE: the
  launcher de-duplicates by ``session_id`` (decision 18). Hermes computes no duration.
* **Ack** (:func:`ack`) — the only delete, and only of a record whose game has ENDED (``exited`` /
  ``lost``): a ``still_running`` record is the live watch's state on disk (decision 15), so an ack of
  one is kept and logged, and its end is handed back later.
* **The cap** (:func:`prune`, decision 17) — at most :data:`MAX_RECORDS` records and none older than
  :data:`MAX_AGE_SECONDS`, oldest ended record dropped first, each drop logged with its session id.
  It runs when a new game is watched and on every pending read. A still-running record is never
  dropped (it is the watch itself).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

from .. import paths
from ..serde import safe_id
from .game_watch import GameRecord, load_records

__layer__ = "lanes"

__all__ = [
    "MAX_AGE_SECONDS",
    "MAX_RECORDS",
    "PLAY_SESSION_RECEIPT",
    "ack",
    "pending",
    "prune",
    "wire_record",
]

logger = logging.getLogger(__name__)

#: Decision 17: the store's ceiling, by count and by age (from the record's receipt).
MAX_RECORDS = 64
MAX_AGE_SECONDS = 30 * 24 * 3600.0
#: One receipt line per drop, ack and kept ack.
PLAY_SESSION_RECEIPT = "launcher_supervision event=%s session_id=%s game_id=%s outcome=%s"


def wire_record(record: GameRecord) -> dict[str, Any]:
    """One record in §2's ``play_sessions_pending`` shape."""

    raw = record.to_json()
    return {key: raw[key] for key in ("session_id", "game_id", "ended_at", "last_seen_at", "exit_code", "outcome")}


def _delete(record: GameRecord) -> bool:
    try:
        (paths.launcher_supervision_games_dir() / f"{record.session_id}.json").unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("launcher_supervision event=play_session_undeleted session_id=%s error=%s",
                       record.session_id, type(exc).__name__)
        return False
    return True


def prune(now: float | None = None) -> list[str]:
    """Drop ended records past :data:`MAX_AGE_SECONDS`, then the oldest ended ones past :data:`MAX_RECORDS`.
    Returns the dropped session ids; each drop is logged (never silent)."""

    now = time.time() if now is None else now
    records = load_records()
    dropped: list[str] = []
    for record in records:
        if not record.active and now - record.received_epoch > MAX_AGE_SECONDS and _delete(record):
            dropped.append(record.session_id)
            logger.info(PLAY_SESSION_RECEIPT, "play_session_dropped_age", record.session_id,
                        record.game_id or "-", record.outcome)
    kept = [record for record in records if record.session_id not in dropped]
    over = len(kept) - MAX_RECORDS
    for record in kept:
        if over <= 0:
            break
        if record.active or not _delete(record):
            continue
        over -= 1
        dropped.append(record.session_id)
        logger.info(PLAY_SESSION_RECEIPT, "play_session_dropped_cap", record.session_id,
                    record.game_id or "-", record.outcome)
    return dropped


def pending(now: float | None = None) -> list[dict[str, Any]]:
    """Every record still held, in the wire shape, oldest receipt first; nothing is deleted but the cap's drops."""

    prune(now)
    return [wire_record(record) for record in load_records()]


def ack(session_ids: Iterable[str]) -> list[str]:
    """Forget the named records whose game has ended; the deleted session ids. An unknown id is a no-op."""

    wanted = {safe_id(sid) for sid in session_ids if isinstance(sid, str) and sid}
    deleted: list[str] = []
    for record in load_records():
        if record.session_id not in wanted:
            continue
        if record.active:
            logger.info(PLAY_SESSION_RECEIPT, "play_session_ack_kept_running", record.session_id,
                        record.game_id or "-", record.outcome)
            continue
        if _delete(record):
            deleted.append(record.session_id)
            logger.info(PLAY_SESSION_RECEIPT, "play_session_acked", record.session_id,
                        record.game_id or "-", record.outcome)
    return deleted
