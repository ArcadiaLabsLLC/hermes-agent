"""The operator's DECISION on an Episode — the one writer of ``Episode.decision`` — and the open
Episodes the fold shows (row ``RT-LENS-EPISODE-DECIDE-VERB``).

``runtime.lens.episode.decide {episode_id, decision}`` lands here (:func:`decide_episode`). A
decision is ``dismiss`` / ``investigate`` / ``snooze15m`` (``episode.Decision``), stamped with its
time:

* ``snooze15m`` also suppresses the rule for ``episode.SNOOZE`` (``suppressed_until``);
* ``dismiss`` of a ``recovered`` Episode closes it (``closed_recovered``): recovery plus the
  operator's word is the settle ``episode.observe`` makes for an open, dismissed one;
* an Episode already ``closed_recovered`` or ``resolved`` is refused ``episode_settled``;
* a decided Episode is no longer owed its turn (``episode.needs_admission``).

:func:`open_episodes` is the fold's list: every ``active`` / ``recovered`` / ``missed`` Episode
EXCEPT a ``recovered`` or ``missed`` one the operator settled (``dismiss`` / ``snooze15m``) —
so a settled Episode leaves the fold rather than waiting for 32 newer ones to crowd it out. An
``active`` Episode stays while it breaches, whatever was decided.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from .episode import SNOOZE, Decision, Episode, EpisodeState
from .store import LensStore, LensStoreError, StoreRefusal

__layer__ = "stores"

_SETTLED_STATES = frozenset({EpisodeState.CLOSED_RECOVERED, EpisodeState.RESOLVED})
_OPEN = (EpisodeState.ACTIVE.value, EpisodeState.RECOVERED.value, EpisodeState.MISSED.value)
#: A ``recovered`` / ``missed`` Episode with one of these decisions is settled, off the fold.
_SETTLING = (Decision.DISMISS.value, Decision.SNOOZE_15M.value)


def decide_episode(store: LensStore, episode_id: str, decision: Decision, now: datetime) -> dict[str, Any]:
    """Record the operator's ``decision`` on the Episode; returns it as stored."""

    row = None
    if store.exists():
        with store.connection() as conn:
            row = conn.execute("SELECT body FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        raise LensStoreError(StoreRefusal.EPISODE_NOT_FOUND)
    episode = Episode.from_json(json.loads(row[0]))
    if episode.state in _SETTLED_STATES:
        raise LensStoreError(StoreRefusal.EPISODE_SETTLED)
    decided = replace(episode, decision=decision, decided_at=max(now, episode.first_seen))
    if decision is Decision.SNOOZE_15M:
        decided = replace(decided, suppressed_until=now + SNOOZE)
    if decision is Decision.DISMISS and episode.state is EpisodeState.RECOVERED:
        decided = replace(decided, state=EpisodeState.CLOSED_RECOVERED)
    store.save_episode(decided, announce=True)
    return decided.to_json()


def open_episodes(store: LensStore, *, limit: int) -> list[dict[str, Any]]:
    """The fold's open Episodes, newest ordinal first per rule, at most ``limit`` (see the module)."""

    if not store.exists():
        return []
    marks = ",".join("?" * len(_OPEN))
    settling = ",".join("?" * len(_SETTLING))
    with store.connection() as conn:
        rows = conn.execute(
            f"SELECT body FROM episodes WHERE state IN ({marks}) AND NOT (state IN (?, ?) AND "
            f"COALESCE(json_extract(body, '$.decision'), '') IN ({settling})) "
            "ORDER BY monitor_id, rule_id, ordinal DESC LIMIT ?",
            (*_OPEN, EpisodeState.RECOVERED.value, EpisodeState.MISSED.value, *_SETTLING, int(limit))).fetchall()
    return [json.loads(row[0]) for row in rows]
