"""One Episode row as the store holds it: its canonical body, a read of the stored body by id, and the
door's ``turn_id``-only write (row ``RT-LENS-EPISODE-WRITE-RACE``).

Beside ``store.py`` (that file sits at its ADR 0007 ceiling). ``LensStore.move_episode`` compares a
writer's read against :func:`episode_body`; the receipt transaction writes through :func:`door_owned`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from .episode import Episode

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
