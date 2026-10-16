"""A Lens FEED (what one source is asked) and an OBSERVATION (what it answered).

Ported from Companion's ``monitor_feed.dart`` / ``monitor_snapshot.dart``, reduced
to the hermes contract (plan ``eternia-lens-in-hermes.md`` §3): a feed names its
kind, its cadence and its kind's source block; nothing else survives the reader.

Feed kinds admitted today are the poll door's two (L1): ``http_json`` and
``prometheus``. ``sql_readonly`` and ``command_allowlisted`` are stage L4; until
they land a manifest naming one is REFUSED with ``feed_kind_unavailable`` — a
missing capability is reported, never faked.

A feed's URL never carries a credential: userinfo in the URL is refused at the
reader, because the only place a source secret may live is the hermes credential
pool, addressed by an opaque reference (L1).

Observations keep the reference's honesty rules: a gap is a gap (``value`` is
``None`` and ``gap`` is True, never interpolated), and an observation carries
both the source's time and the time it was received.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .wire_value import (
    WireError,
    WireRefusal,
    bounded_int,
    bounded_string,
    boolean_value,
    checked_object,
    enum_value,
    finite_number,
    format_utc,
    opaque_id,
    require,
    utc_time,
)

__layer__ = "models"

#: The reference's cadence floor and ceiling (1 s .. 7 d).
MINIMUM_INTERVAL_MS = 1000
MAXIMUM_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000

_SELECTOR_SEGMENT_MAX = 256


class FeedKind(str, Enum):
    HTTP_JSON = "http_json"
    PROMETHEUS = "prometheus"
    SQL_READONLY = "sql_readonly"
    COMMAND_ALLOWLISTED = "command_allowlisted"


#: The kinds whose source is built. Every other kind is refused by name.
AVAILABLE_FEED_KINDS = frozenset({FeedKind.HTTP_JSON, FeedKind.PROMETHEUS})


def source_url(value: Any) -> str:
    """An absolute http(s) URL with a host, no userinfo and no fragment."""

    text = bounded_string(value, maximum=2048)
    parts = urlsplit(text)
    require(parts.scheme in ("http", "https") and bool(parts.hostname), "source url", WireRefusal.INVALID_STRING)
    require(parts.username is None and parts.password is None, "credential in url", WireRefusal.INVALID_STRING)
    require(not parts.fragment, "fragment in url", WireRefusal.INVALID_STRING)
    return text


def extraction_path(value: Any) -> str:
    """``$`` followed by ``.name`` / ``[index]`` segments — the reference's selector."""

    text = bounded_string(value, maximum=_SELECTOR_SEGMENT_MAX)
    require(
        re.fullmatch(r"\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]{1,4}\])*", text) is not None,
        "extraction path",
        WireRefusal.INVALID_STRING,
    )
    return text


def _http_json_source(value: Any) -> dict[str, Any]:
    m = checked_object(value, {"url", "selector"})
    return {"url": source_url(m["url"]), "selector": extraction_path(m["selector"])}


def _prometheus_source(value: Any) -> dict[str, Any]:
    m = checked_object(value, {"base_url", "query"})
    return {"base_url": source_url(m["base_url"]), "query": bounded_string(m["query"], maximum=1024)}


#: Feed kind -> its source block's reader. A kind absent here is unavailable.
_SOURCE_READERS = {
    FeedKind.HTTP_JSON: _http_json_source,
    FeedKind.PROMETHEUS: _prometheus_source,
}

FEED_KEYS_REQUIRED = frozenset({"version", "id", "kind", "interval_ms", "source"})
FEED_KEYS_OPTIONAL: frozenset[str] = frozenset()


def read_feed(value: Any) -> dict[str, Any]:
    """The canonical feed dict, or :class:`WireError`."""

    m = checked_object(value, FEED_KEYS_REQUIRED, FEED_KEYS_OPTIONAL)
    kind = enum_value(m["kind"], FeedKind)
    if kind not in AVAILABLE_FEED_KINDS:
        raise WireError(WireRefusal.INVALID_VALUE, "feed_kind_unavailable")
    return {
        "version": bounded_int(m["version"], minimum=1, maximum=1),
        "id": opaque_id(m["id"]),
        "kind": kind.value,
        "interval_ms": bounded_int(m["interval_ms"], minimum=MINIMUM_INTERVAL_MS, maximum=MAXIMUM_INTERVAL_MS),
        "source": _SOURCE_READERS[kind](m["source"]),
    }


# --- observations -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One answer from one feed. ``value`` None with ``gap`` True is a recorded gap."""

    monitor_id: str
    feed_id: str
    sequence: int
    observed_at: datetime
    received_at: datetime
    value: float | None
    gap: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "feed_id": self.feed_id,
            "sequence": self.sequence,
            "observed_at": format_utc(self.observed_at),
            "received_at": format_utc(self.received_at),
            "value": self.value,
            "gap": self.gap,
        }

    @classmethod
    def from_json(cls, value: Any) -> Observation:
        m = checked_object(value, {"monitor_id", "feed_id", "sequence", "observed_at", "received_at", "value", "gap"})
        gap = boolean_value(m["gap"])
        number = None if m["value"] is None else finite_number(m["value"])
        require(gap == (number is None), "a gap carries no value, a value is no gap")
        return cls(
            monitor_id=opaque_id(m["monitor_id"]),
            feed_id=opaque_id(m["feed_id"]),
            sequence=bounded_int(m["sequence"], minimum=1),
            observed_at=utc_time(m["observed_at"]),
            received_at=utc_time(m["received_at"]),
            value=number,
            gap=gap,
        )
