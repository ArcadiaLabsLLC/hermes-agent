"""MISSED deadlines: an ``ends_within`` deadline that passed while the watcher was off (W8(a)).

Plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §4. ``LensPoller.catch_up`` records one
``watcher_offline`` gap per unwatched feed; before it does, :func:`record_missed_deadlines` asks,
per ``ends_within`` rule on that feed, whether the deadline the feed last READ — D, its newest
non-gap value at or before the outage began — fell inside the outage ``(offline_from, now]``. If it
did, ONE ``missed`` Episode opens (``first_seen`` = max(D - lead, offline_from), ``last_seen`` = D,
``count`` 1). Everything is derived from recorded facts: no observation is written for the unwatched
interval beyond the existing gap, and the current value stays unknown until the next read.

Deduplicated (:func:`missed_episode`, pure): nothing when D is still ahead (the normal tick and its
W7 confirming read fire it from a fresh read), or when the rule's latest Episode was seen at or after
D - lead. That one check covers both of the plan's dedup arms: a rule that fired before the outage
was seen inside its lead window, and a ``missed`` Episode for the same D (a second restart) has
``last_seen`` = D — and any later Episode of the rule is later still.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .episode import Episode, EpisodeState
from .rules import RuleForm
from .store import LensStore, from_ms, to_ms

__layer__ = "stores"


def missed_episode(*, monitor_id: str, rule_id: str, lead_ms: int, deadline_ms: int, offline_from_ms: int,
                   now_ms: int, previous: Episode | None) -> Episode | None:
    """The ``missed`` Episode the recorded facts owe, or None. Pure; ``previous`` is the rule's
    latest Episode."""

    if not offline_from_ms < deadline_ms <= now_ms:
        return None
    if previous is not None and to_ms(previous.last_seen) >= deadline_ms - lead_ms:
        return None
    return Episode(monitor_id=monitor_id, rule_id=rule_id, ordinal=(previous.ordinal if previous else 0) + 1,
                   first_seen=from_ms(max(deadline_ms - lead_ms, offline_from_ms)), last_seen=from_ms(deadline_ms),
                   count=1, state=EpisodeState.MISSED, missed_deadline_ms=deadline_ms)


def _recorded_deadline(store: LensStore, monitor_id: str, feed_id: str, at_ms: int) -> int | None:
    with store.connection() as conn:
        row = conn.execute("SELECT value FROM observations WHERE monitor_id = ? AND feed_id = ? AND value IS NOT NULL "
                           "AND observed_ms <= ? ORDER BY observed_ms DESC, sequence DESC LIMIT 1",
                           (monitor_id, feed_id, at_ms)).fetchone()
    return None if row is None else int(row[0])


def record_missed_deadlines(store: LensStore, monitor_id: str, manifest: dict[str, Any], feed: dict[str, Any], *,
                            offline_from: datetime, now: datetime) -> int:
    """Open the ``missed`` Episodes the feed's ``ends_within`` rules are owed. Returns how many."""

    opened = 0
    for rule in manifest["rules"]:
        if RuleForm(rule["form"]) is not RuleForm.ENDS_WITHIN or rule["feed_id"] != feed["id"]:
            continue
        deadline = _recorded_deadline(store, monitor_id, feed["id"], to_ms(offline_from))
        if deadline is None:
            continue
        episode = missed_episode(monitor_id=monitor_id, rule_id=rule["id"], lead_ms=rule["window_ms"],
                                 deadline_ms=deadline, offline_from_ms=to_ms(offline_from), now_ms=to_ms(now),
                                 previous=store.latest_episode(monitor_id, rule["id"]))
        if episode is not None:
            store.save_episode(episode)
            opened += 1
    return opened


def offline_interval(store: LensStore, monitor_id: str, feed_id: str, deadline_ms: int) -> tuple[int, int] | None:
    """``(offline_from_ms, offline_until_ms)`` of the outage a missed ``deadline_ms`` passed in: the
    first ``watcher_offline`` gap at or after it, and the row the watcher recorded before that gap."""

    with store.connection() as conn:
        gap = conn.execute("SELECT observed_ms, sequence FROM observations WHERE monitor_id = ? AND feed_id = ? "
                           "AND reason = 'watcher_offline' AND observed_ms >= ? ORDER BY observed_ms, sequence "
                           "LIMIT 1", (monitor_id, feed_id, deadline_ms)).fetchone()
        if gap is None:
            return None
        before = conn.execute("SELECT observed_ms FROM observations WHERE monitor_id = ? AND feed_id = ? "
                              "AND sequence < ? ORDER BY sequence DESC LIMIT 1",
                              (monitor_id, feed_id, gap[1])).fetchone()
    return None if before is None else (int(before[0]), int(gap[0]))
