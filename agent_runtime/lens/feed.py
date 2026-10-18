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
pool, addressed by the feed's opaque ``credential_ref`` (L1, ``lens.credentials``).

A feed may declare what its number IS (``value_type``: count, money with its
currency, an instant in epoch milliseconds) and the range a read must fall in
(``plausible``); :func:`typed_reading` turns a read that breaks either into a
recorded gap with its reason, before any rule sees it (plan §6b W2, W5).

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
#: ``credential_ref`` (L1): an opaque reference into the hermes credential pool
#: (``lens.credentials``), never the bytes. ``allow_private_network`` (L1, W10):
#: the explicit opt-in a loopback / private / link-local source needs.
#: ``value_type`` and ``plausible`` (W2): what the number IS, and the range a read
#: must fall in before any rule may see it.
FEED_KEYS_OPTIONAL = frozenset({"credential_ref", "allow_private_network", "value_type", "plausible"})


# --- typed values (W2(c), W5) --------------------------------------------------


class ValueKind(str, Enum):
    """What a feed's number means. A bare float is ``number``; the rest are typed."""

    NUMBER = "number"
    COUNT = "count"
    MONEY = "money"
    INSTANT = "instant"


class ReadingRefusal(str, Enum):
    """Why a read the source answered is recorded as a gap instead of a value."""

    TYPE_MISMATCH = "type_mismatch"
    IMPLAUSIBLE = "implausible"


_CURRENCY = re.compile(r"^[A-Z]{3}$")
#: An instant is integral epoch milliseconds inside the safe-integer range.
_MAXIMUM_INSTANT_MS = 9007199254740991


def read_value_type(value: Any) -> dict[str, Any]:
    """``{kind}``, plus ``currency`` (ISO 4217) exactly when the kind is money."""

    m = checked_object(value, {"kind"}, {"currency"})
    kind = enum_value(m["kind"], ValueKind)
    out: dict[str, Any] = {"kind": kind.value}
    if kind is ValueKind.MONEY:
        currency = bounded_string(m.get("currency"), maximum=3)
        require(_CURRENCY.fullmatch(currency) is not None, "currency", WireRefusal.INVALID_STRING)
        out["currency"] = currency
    else:
        require(m.get("currency") is None, "currency only for money")
    return out


def read_plausible(value: Any) -> dict[str, float]:
    m = checked_object(value, {"minimum", "maximum"})
    low, high = finite_number(m["minimum"]), finite_number(m["maximum"])
    require(low < high, "plausible range")
    return {"minimum": low, "maximum": high}


def value_type_of(feed: dict[str, Any]) -> dict[str, Any]:
    """The feed's value type; an untyped feed is a plain number."""

    return feed.get("value_type") or {"kind": ValueKind.NUMBER.value}


def typed_reading(feed: dict[str, Any], value: float | None) -> tuple[float | None, ReadingRefusal | None]:
    """The value a rule may see, or (None, why) when the read must be a gap.

    A count or an instant that is not integral, a negative count, and any value
    outside the feed's declared plausible range are refused: a bad parse is a
    recorded gap with its reason, never an alert (W2)."""

    if value is None:
        return None, None
    kind = ValueKind(value_type_of(feed)["kind"])
    if kind in (ValueKind.COUNT, ValueKind.INSTANT) and (value != int(value) or value < 0):
        return None, ReadingRefusal.TYPE_MISMATCH
    if kind is ValueKind.INSTANT and value > _MAXIMUM_INSTANT_MS:
        return None, ReadingRefusal.TYPE_MISMATCH
    plausible = feed.get("plausible")
    if plausible is not None and not plausible["minimum"] <= value <= plausible["maximum"]:
        return None, ReadingRefusal.IMPLAUSIBLE
    return value, None


def read_feed(value: Any) -> dict[str, Any]:
    """The canonical feed dict, or :class:`WireError`."""

    m = checked_object(value, FEED_KEYS_REQUIRED, FEED_KEYS_OPTIONAL)
    kind = enum_value(m["kind"], FeedKind)
    if kind not in AVAILABLE_FEED_KINDS:
        raise WireError(WireRefusal.INVALID_VALUE, "feed_kind_unavailable")
    feed = {
        "version": bounded_int(m["version"], minimum=1, maximum=1),
        "id": opaque_id(m["id"]),
        "kind": kind.value,
        "interval_ms": bounded_int(m["interval_ms"], minimum=MINIMUM_INTERVAL_MS, maximum=MAXIMUM_INTERVAL_MS),
        "source": _SOURCE_READERS[kind](m["source"]),
    }
    if m.get("credential_ref") is not None:
        feed["credential_ref"] = opaque_id(m["credential_ref"])
    # Absence and an explicit False are one canonical form (no key).
    if m.get("allow_private_network") is not None and boolean_value(m["allow_private_network"]):
        feed["allow_private_network"] = True
    if m.get("value_type") is not None:
        value_type = read_value_type(m["value_type"])
        if value_type["kind"] != ValueKind.NUMBER.value:
            feed["value_type"] = value_type
    if m.get("plausible") is not None:
        feed["plausible"] = read_plausible(m["plausible"])
    return feed


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
