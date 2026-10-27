"""One Episode row as the store holds it: its canonical body, a read of the stored body by id, and the
door's ``turn_id``-only write (row ``RT-LENS-EPISODE-WRITE-RACE``), and the receipt transaction's
re-check that the stored Episode is still owed its admission (row ``RT-LENS-DOOR-ADMITS-STALE-EPISODE``).

Beside ``store.py`` (that file sits at its ADR 0007 ceiling). ``LensStore.move_episode`` compares a
writer's read against :func:`episode_body`; the receipt transaction writes through :func:`door_owned`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .episode import Episode, needs_admission

__layer__ = "stores"


def canonical_body(episode: Episode) -> str:
    return json.dumps(episode.to_json(), sort_keys=True)


def episode_body(conn: sqlite3.Connection, episode_id: str) -> str | None:
    row = conn.execute("SELECT body FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    return None if row is None else row[0]


def door_owned(conn: sqlite3.Connection, episode: Episode) -> Episode:
    """The door owns only ``turn_id``: set it on the row as STORED now, never on the copy it admitted."""

    stored = episode_body(conn, episode.id)
    return episode if stored is None else replace(Episode.from_json(json.loads(stored)), turn_id=episode.turn_id)


def stale_pairs(conn: sqlite3.Connection, pairs: list[tuple[dict[str, Any], Episode | None]],
                skipped: str) -> list[tuple[dict[str, Any], Episode]]:
    """The pairs whose STORED Episode is no longer owed its admission, each settled ``skipped``.

    The exit door decides on an Episode it read before its receipt transaction; an operator
    ``dismiss`` / ``snooze15m`` written in between makes that read stale. Empty when every
    stored row still needs admission at the receipt's own ``started_ms`` (the door's clock) —
    the caller then writes the receipts it was handed. Otherwise the caller writes ONLY these
    and runs no turn: the still-owed rest keep no receipt and are admitted afresh next pass."""

    out = []
    for receipt, episode in pairs:
        stored = None if episode is None else episode_body(conn, episode.id)
        if stored is None:
            continue
        now = datetime.fromtimestamp(int(receipt["started_ms"]) / 1000, tz=UTC)
        if needs_admission(Episode.from_json(json.loads(stored)), now):
            continue
        settled = {**receipt, "turn_id": skipped, "outcome": skipped, "finished_ms": receipt["started_ms"],
                   "tool_admission": "none", "digest_id": None}
        out.append((settled, replace(episode, turn_id=skipped)))
    return out
