"""Lens EPISODES: one per rule breach, and the pure transition that moves them.

Ported from Companion's ``monitor_episode.dart`` (``Episode``, ``EpisodeDecision``)
and the runtime's ``monitor_incidents.dart`` (``MonitorEpisodes.observe`` /
``needsAdmission``); the oracles are the ported ``observation_corpus.json`` and
``episode_rearm_corpus.json``.

States: ``active`` (breaching) -> ``recovered`` (healthy again, still OPEN — the
operator or the turn has not settled it) -> back to ``active`` on a new breach,
or settled as ``closed_recovered`` / ``resolved``. Recovery is not resolution.

The Companion Work owner is cut (plan §4): an Episode's response is the ONE chat
turn the exit door forges (stage L2), named here by ``turn_id``; ``decision`` is
the operator's settle (dismiss / investigate / snooze15m), recorded with its time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .rules import Verdict
from .wire_value import (
    bounded_int,
    canonical_digest,
    checked_object,
    enum_value,
    format_utc,
    opaque_id,
    optional,
    require,
    utc_time,
)

__layer__ = "policy"

SNOOZE = timedelta(minutes=15)


class EpisodeState(str, Enum):
    ACTIVE = "active"
    RECOVERED = "recovered"
    CLOSED_RECOVERED = "closed_recovered"
    RESOLVED = "resolved"


class Decision(str, Enum):
    DISMISS = "dismiss"
    INVESTIGATE = "investigate"
    SNOOZE_15M = "snooze15m"


#: A decision that settles a RECOVERED episode: the next breach opens a new one.
_SETTLING = frozenset({Decision.DISMISS, Decision.SNOOZE_15M})


def episode_id(monitor_id: str, rule_id: str, ordinal: int) -> str:
    return canonical_digest({
        "monitor_id": opaque_id(monitor_id),
        "rule_id": opaque_id(rule_id),
        "ordinal": bounded_int(ordinal, minimum=1),
    })


@dataclass(frozen=True, slots=True)
class Episode:
    monitor_id: str
    rule_id: str
    ordinal: int
    first_seen: datetime
    last_seen: datetime
    count: int
    state: EpisodeState
    suppressed_until: datetime | None = None
    turn_id: str | None = None
    decision: Decision | None = None
    decided_at: datetime | None = None

    @property
    def id(self) -> str:
        return episode_id(self.monitor_id, self.rule_id, self.ordinal)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "monitor_id": self.monitor_id,
            "rule_id": self.rule_id,
            "ordinal": self.ordinal,
            "first_seen": format_utc(self.first_seen),
            "last_seen": format_utc(self.last_seen),
            "count": self.count,
            "state": self.state.value,
            "suppressed_until": None if self.suppressed_until is None else format_utc(self.suppressed_until),
            "turn_id": self.turn_id,
            "decision": None if self.decision is None else self.decision.value,
            "decided_at": None if self.decided_at is None else format_utc(self.decided_at),
        }

    @classmethod
    def from_json(cls, value: Any) -> Episode:
        m = checked_object(value, {
            "version", "id", "monitor_id", "rule_id", "ordinal", "first_seen", "last_seen",
            "count", "state", "suppressed_until", "turn_id", "decision", "decided_at",
        })
        bounded_int(m["version"], minimum=1, maximum=1)
        episode = cls(
            monitor_id=opaque_id(m["monitor_id"]),
            rule_id=opaque_id(m["rule_id"]),
            ordinal=bounded_int(m["ordinal"], minimum=1),
            first_seen=utc_time(m["first_seen"]),
            last_seen=utc_time(m["last_seen"]),
            count=bounded_int(m["count"], minimum=1),
            state=enum_value(m["state"], EpisodeState),
            suppressed_until=optional(m["suppressed_until"], utc_time),
            turn_id=optional(m["turn_id"], opaque_id),
            decision=optional(m["decision"], lambda v: enum_value(v, Decision)),
            decided_at=optional(m["decided_at"], utc_time),
        )
        require(m["id"] == episode.id, "episode identity")
        require(episode.last_seen >= episode.first_seen, "episode chronology")
        require((episode.decision is None) == (episode.decided_at is None), "decision needs its time")
        return episode


def _is_open(previous: Episode | None) -> bool:
    if previous is None:
        return False
    if previous.state is EpisodeState.ACTIVE:
        return True
    return previous.state is EpisodeState.RECOVERED and previous.decision not in _SETTLING


def observe(
    *,
    monitor_id: str,
    rule_id: str,
    next_ordinal: int,
    verdict: Verdict,
    at: datetime,
    previous: Episode | None = None,
    close_recovered: bool = False,
) -> Episode | None:
    """The episode after one verdict. Pure; the caller commits it with its observations."""

    if previous is not None and (
        previous.monitor_id != monitor_id or previous.rule_id != rule_id or at < previous.last_seen
    ):
        raise ValueError("episode identity or time")
    if verdict is Verdict.UNKNOWN:
        return previous
    if not _is_open(previous):
        if previous is not None and previous.suppressed_until is not None and previous.suppressed_until > at:
            return previous
        if verdict is not Verdict.FIRING:
            return previous
        if previous is not None and next_ordinal <= previous.ordinal:
            raise ValueError("a settled ordinal cannot be reused")
        return Episode(monitor_id=monitor_id, rule_id=rule_id, ordinal=next_ordinal,
                       first_seen=at, last_seen=at, count=1, state=EpisodeState.ACTIVE)
    if at == previous.last_seen:
        return previous
    firing = verdict is Verdict.FIRING
    if firing:
        state = EpisodeState.ACTIVE
    elif previous.decision is Decision.DISMISS or close_recovered:
        state = EpisodeState.CLOSED_RECOVERED
    else:
        state = EpisodeState.RECOVERED
    return replace(previous, last_seen=at, count=previous.count + (1 if firing else 0), state=state)


def needs_admission(episode: Episode, now: datetime) -> bool:
    """True when this Episode is owed its one forged turn (stage L2 reads this)."""

    return (
        episode.state is EpisodeState.ACTIVE
        and episode.turn_id is None
        and episode.decision is None
        and (episode.suppressed_until is None or episode.suppressed_until <= now)
    )
