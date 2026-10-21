"""Lens EVIDENCE: the bounded window an Episode's turn carries.

Ported from Companion's ``monitor_evidence.dart`` (``EvidenceWindow``) and the
runtime's ``MonitorEvidenceReader`` / ``NumericEvidenceWindowBuilder``; the oracle
is the ported ``evidence_corpus.json``.

* The range is HALF-OPEN: ``start <= observed_at < end``.
* At most four feeds and seven days; at most ``maximum_bytes`` canonical bytes
  (default 32 KiB). An over-budget window is REFUSED whole — silently dropping
  observations would change the evidence.
* Only typed observations travel (a number, or a recorded gap). No free text is
  admitted into a window, so nothing a source said can reach the turn as prose.
* ``gap_count`` counts recorded gaps; an empty range is one gap (no coverage is
  not "healthy").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

from .feed import Observation
from .wire_value import canonical_bytes, canonical_digest, format_utc, opaque_id

__layer__ = "policy"

DEFAULT_MAXIMUM_BYTES = 32 * 1024
MAXIMUM_FEEDS = 4
MAXIMUM_SPAN = timedelta(days=7)
#: Names the redaction policy the window was built under (typed numbers only).
REDACTION_POLICY = "lens-numeric-evidence-v1"


class EvidenceRefused(ValueError):
    """The window cannot be built inside its bounds. ``code`` is typed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    monitor_id: str
    feed_ids: tuple[str, ...]
    requested_start: datetime
    requested_end: datetime
    observations: tuple[Observation, ...]
    gap_count: int
    maximum_bytes: int = DEFAULT_MAXIMUM_BYTES

    @property
    def covered_start(self) -> datetime | None:
        return self.observations[0].observed_at if self.observations else None

    @property
    def covered_end(self) -> datetime | None:
        return self.observations[-1].observed_at if self.observations else None

    def to_json(self) -> dict[str, Any]:
        def _at(moment: datetime | None) -> str | None:
            return None if moment is None else format_utc(moment)

        return {
            "version": 1,
            "monitor_id": self.monitor_id,
            "feed_ids": list(self.feed_ids),
            "requested_start": format_utc(self.requested_start),
            "requested_end": format_utc(self.requested_end),
            "covered_start": _at(self.covered_start),
            "covered_end": _at(self.covered_end),
            "observations": [obs.to_json() for obs in self.observations],
            "gap_count": self.gap_count,
            "redaction_policy_digest": canonical_digest(REDACTION_POLICY),
            "maximum_bytes": self.maximum_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_json())


def build_evidence(
    observations: Sequence[Observation],
    *,
    monitor_id: str,
    feed_ids: Sequence[str],
    start: datetime,
    end: datetime,
    maximum_bytes: int = DEFAULT_MAXIMUM_BYTES,
) -> EvidenceWindow:
    """The window over ``[start, end)`` for ``feed_ids``, or :class:`EvidenceRefused`."""

    feeds = tuple(opaque_id(feed) for feed in feed_ids)
    if not 1 <= len(feeds) <= MAXIMUM_FEEDS or len(set(feeds)) != len(feeds):
        raise EvidenceRefused("feed_bound")
    if not start < end or end - start > MAXIMUM_SPAN:
        raise EvidenceRefused("range_bound")
    selected = tuple(sorted(
        (obs for obs in observations
         if obs.monitor_id == monitor_id and obs.feed_id in feeds and start <= obs.observed_at < end),
        key=lambda obs: (obs.observed_at, obs.feed_id, obs.sequence),
    ))
    gaps = sum(1 for obs in selected if obs.gap)
    window = EvidenceWindow(
        monitor_id=opaque_id(monitor_id),
        feed_ids=feeds,
        requested_start=start,
        requested_end=end,
        observations=selected,
        gap_count=gaps if selected else 1,
        maximum_bytes=maximum_bytes,
    )
    if len(window.canonical_bytes) > maximum_bytes:
        raise EvidenceRefused("byte_budget")
    return window
