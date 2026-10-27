"""SCHEDULED runs: a monitor's ``schedule`` produces one ``schedule:run`` Episode per due slot.

Plan ``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §2 (decisions 3-6). A sealed
``schedule: {every_ms, offset_ms, brief}`` divides UTC time into slots starting at
``S = floor((now - offset) / every) * every + offset``. A run is due iff the rule's latest Episode is
None or its ``first_seen`` is before the current ``S``: the run opens with ``first_seen`` = S,
``last_seen`` = now (its lateness is the difference) and state ``scheduled``, admitted through the
exit door like any Episode. Keyed on the slot START, not a slot index, so a reseal that changes
``every_ms`` stays correct.

Catch-up is one late run, never a storm: after an outage or a pause spanning several slots only the
CURRENT slot is due; the skipped ones are not materialised (the opening block names the previous
run's time, so the gap is visible). First enable: the current slot is due at once.

``LensPoller.tick`` calls :func:`record_due_schedule` once per ENABLED monitor, so a paused monitor
accrues nothing.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .episode import Episode, EpisodeState
from .rules import SCHEDULE_RULE_ID
from .store import LensStore, from_ms, to_ms

__layer__ = "stores"


def slot_start(now_ms: int, *, every_ms: int, offset_ms: int) -> int:
    """The start (epoch ms) of the slot ``now_ms`` falls in."""

    return (now_ms - offset_ms) // every_ms * every_ms + offset_ms


def scheduled_episode(*, monitor_id: str, schedule: dict[str, Any], now_ms: int,
                      previous: Episode | None) -> Episode | None:
    """The run the current slot owes, or None when the rule's latest run already started in it. Pure."""

    start = slot_start(now_ms, every_ms=schedule["every_ms"], offset_ms=schedule["offset_ms"])
    if previous is not None and to_ms(previous.first_seen) >= start:
        return None
    return Episode(monitor_id=monitor_id, rule_id=SCHEDULE_RULE_ID,
                   ordinal=(previous.ordinal if previous else 0) + 1, first_seen=from_ms(start),
                   last_seen=from_ms(now_ms), count=1, state=EpisodeState.SCHEDULED)


def record_due_schedule(store: LensStore, monitor_id: str, manifest: dict[str, Any], now: datetime) -> bool:
    """Open the monitor's due run, if any (compare-and-set: a lost race opens nothing this tick).
    True when one was opened."""

    schedule = manifest.get("schedule")
    if schedule is None:
        return False
    previous = store.latest_episode(monitor_id, SCHEDULE_RULE_ID)
    episode = scheduled_episode(monitor_id=monitor_id, schedule=schedule, now_ms=to_ms(now), previous=previous)
    return episode is not None and store.move_episode(previous, episode)


def previous_run_ms(store: LensStore, episode: Episode) -> int | None:
    """The slot start (``first_seen``) of the run before ``episode``, or None when none is recorded
    (the first run, or one retention has since folded away)."""

    with store.connection() as conn:
        row = conn.execute("SELECT body FROM episodes WHERE monitor_id = ? AND rule_id = ? AND ordinal < ? "
                           "ORDER BY ordinal DESC LIMIT 1",
                           (episode.monitor_id, SCHEDULE_RULE_ID, episode.ordinal)).fetchone()
    return None if row is None else to_ms(Episode.from_json(json.loads(row[0])).first_seen)
