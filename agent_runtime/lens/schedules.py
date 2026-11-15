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
run's time, so the gap is visible).

First enable waits for the time picked (RT-LENS-FIRST-SCHEDULED-RUN-WAITS-FOR-ITS-TIME): a slot that
began before the schedule was ARMED is never back-filled, so a monitor sealed at 04:35 for a daily
04:36 check runs once, at 04:36 — not once for yesterday's slot at 04:35 and again at 04:36. The arming
time is the poller's clock on the first tick that sees this ``(every_ms, offset_ms)``, kept in the
``schedule_arming`` table this module owns (no seal time is stored, and the store's wall clock is not
the poller's). A reseal that changes the timing re-arms it (a phase moved later does not back-fill
the slot the old phase missed); one that keeps it, and a pause, do not, so catch-up still forges its
one late run. A schedule seen first with runs already recorded (a store from before this table) arms
at its latest run when that run sits on a slot start of the current timing, so nothing changes for
it; a run on another timing means it was re-timed before that first tick, so it arms then
(RT-LENS-RESEAL-BEFORE-FIRST-ARMING-BACK-FILLS-ONCE).

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

_SCHEMA = """CREATE TABLE IF NOT EXISTS schedule_arming (
  monitor_id TEXT PRIMARY KEY, every_ms INTEGER NOT NULL, offset_ms INTEGER NOT NULL, armed_ms INTEGER NOT NULL)"""


def slot_start(now_ms: int, *, every_ms: int, offset_ms: int) -> int:
    """The start (epoch ms) of the slot ``now_ms`` falls in."""

    return (now_ms - offset_ms) // every_ms * every_ms + offset_ms


def scheduled_episode(*, monitor_id: str, schedule: dict[str, Any], now_ms: int,
                      previous: Episode | None, armed_ms: int) -> Episode | None:
    """The run the current slot owes, or None when the rule's latest run already started in it or the
    slot began before the schedule was armed at ``armed_ms``. Pure."""

    start = slot_start(now_ms, every_ms=schedule["every_ms"], offset_ms=schedule["offset_ms"])
    if start < armed_ms or previous is not None and to_ms(previous.first_seen) >= start:
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
    armed_ms = _armed_ms(store, monitor_id, schedule, now_ms=to_ms(now), previous=previous)
    episode = scheduled_episode(monitor_id=monitor_id, schedule=schedule, now_ms=to_ms(now), previous=previous,
                                armed_ms=armed_ms)
    return episode is not None and store.move_episode(previous, episode)


def _armed_ms(store: LensStore, monitor_id: str, schedule: dict[str, Any], *, now_ms: int,
              previous: Episode | None) -> int:
    """When this timing was armed: read, or recorded now on the first tick that sees it."""

    timing = (int(schedule["every_ms"]), int(schedule["offset_ms"]))
    with store.connection() as conn:
        conn.execute(_SCHEMA)
        row = conn.execute("SELECT every_ms, offset_ms, armed_ms FROM schedule_arming WHERE monitor_id = ?",
                           (monitor_id,)).fetchone()
        if row is not None and (row[0], row[1]) == timing:
            return int(row[2])
        # A store from before this table already ran THIS timing (its latest run sits on one of its slot
        # starts): arm at that run, so catch-up is unchanged. A run on another timing means the schedule was
        # re-timed before its first tick here: arm now, like any reseal that changes the timing.
        armed = now_ms
        if row is None and previous is not None:
            last = to_ms(previous.first_seen)
            if slot_start(last, every_ms=timing[0], offset_ms=timing[1]) == last:
                armed = last
        conn.execute("INSERT OR REPLACE INTO schedule_arming (monitor_id, every_ms, offset_ms, armed_ms) "
                     "VALUES (?, ?, ?, ?)", (monitor_id, *timing, armed))
    return armed


def previous_run_ms(store: LensStore, episode: Episode) -> int | None:
    """The slot start (``first_seen``) of the run before ``episode``, or None when none is recorded
    (the first run, or one retention has since folded away)."""

    with store.connection() as conn:
        row = conn.execute("SELECT body FROM episodes WHERE monitor_id = ? AND rule_id = ? AND ordinal < ? "
                           "ORDER BY ordinal DESC LIMIT 1",
                           (episode.monitor_id, SCHEDULE_RULE_ID, episode.ordinal)).fetchone()
    return None if row is None else to_ms(Episode.from_json(json.loads(row[0])).first_seen)
