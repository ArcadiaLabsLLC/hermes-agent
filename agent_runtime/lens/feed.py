"""A Lens FEED (what one source is asked) and an OBSERVATION (what it answered).

Ported from Companion's ``monitor_feed.dart`` / ``monitor_snapshot.dart``, reduced
to the hermes contract (plan ``eternia-lens-in-hermes.md`` §3): a feed names its
kind, its cadence and its kind's source block; nothing else survives the reader.

Feed kinds: the poll door's (L1) ``http_json`` and ``prometheus`` (L4: or through
``kubectl proxy``, ``via: kube_proxy``); the push door's (L3) ``push`` — a feed
nothing polls, written only by an ingress route (``lens.ingress_routes``; its source
block is empty, its ``interval_ms`` the cadence a rule expects); and the pull
door's local sources (L4, plan ``p10-agent-2026-10-19.md`` §5.5 L4.3):

* ``sql_readonly`` — ``{database, query}``: an absolute SQLite path, opened
  read-only, and ONE statement that begins with ``SELECT`` or ``WITH``
  (:data:`READ_ONLY_STATEMENT`); one row, one value.
* ``command_allowlisted`` — ``{argv, allow, extract}``: ``argv`` must be one of
  the ``allow`` lists, and runs only from a SEALED manifest (no shell, 10 s);
  its stdout is JSON and ``extract`` selects the number.

A kind outside :data:`AVAILABLE_FEED_KINDS` is REFUSED with
``feed_kind_unavailable`` — a missing capability is reported, never faked.

A feed's URL never carries a credential: userinfo in the URL is refused at the
reader, because the only place a source secret may live is the home's Lens
credential file, addressed by the feed's opaque ``credential_ref`` (L1, ``lens.credentials``).

A feed may declare what its number IS (``value_type``: count, money with its
currency, an instant in epoch milliseconds) and the range a read must fall in
(``plausible``); :func:`typed_reading` turns a read that breaks either into a
recorded gap with its reason, before any rule sees it (plan §6b W2, W5).

Two more guards stand between a read and a rule (plan §6b W2(c), W5):

* ``outlier_guard: {window, deviations}`` — a fast feed's read more than
  ``deviations`` robust deviations (1.4826 x the median absolute deviation) from
  the median of its last ``window`` reads is a gap ``outlier``
  (:func:`outlier_refused`). The window holds the refused reads too, so a real
  level shift is admitted once it is the median, never refused for ever; a flat
  window (deviation 0) abstains — a price step is a change, not an outlier.
* ``value_type.total_cost: {shipping?, tax_rate?, fx?}`` on a money feed — the
  stored value is the TOTAL cost, ``(price + shipping) x (1 + tax_rate)``,
  converted by a dated exchange-rate feed of the same monitor when the listing's
  currency (``fx.from``) is not the feed's ``currency`` (:func:`total_cost`). A
  rate older than ``fx.max_age_ms`` at the read, or none, is a gap ``fx_stale``:
  a comparison never silently mixes currencies. ``best_of`` compares the total.

``product: {identity, variant, condition}`` (W5, plan
``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §3) labels WHAT a listing is: a
money ``best_of`` seals only over members that share ``condition`` and ``variant``
(``manifest.check_sealable``). Absent is today's canonical bytes.

Observations keep the reference's honesty rules: a gap is a gap (``value`` is
``None`` and ``gap`` is True, never interpolated), and an observation carries
both the source's time and the time it was received.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .wire_value import (
    WireError,
    WireRefusal,
    bounded_int,
    bounded_list,
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
    PUSH = "push"


#: The kinds whose source is built. Every other kind is refused by name.
AVAILABLE_FEED_KINDS = frozenset({FeedKind.HTTP_JSON, FeedKind.PROMETHEUS, FeedKind.SQL_READONLY,
                                  FeedKind.COMMAND_ALLOWLISTED, FeedKind.PUSH})
#: The kinds that run only from a sealed manifest: never in a preview of a draft.
SEALED_ONLY_FEED_KINDS = frozenset({FeedKind.COMMAND_ALLOWLISTED})

#: A ``sql_readonly`` statement begins with SELECT or WITH (case-insensitive); the
#: read-only open and ``PRAGMA query_only`` refuse a write that hides behind a WITH.
READ_ONLY_STATEMENT = re.compile(r"\s*(?:SELECT|WITH)\b", re.IGNORECASE)
#: ``kubectl proxy``'s default listen address: the only base a ``via: kube_proxy`` feed reads.
KUBE_PROXY_BASE = "http://127.0.0.1:8001"
_KUBE_NAME = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
MAXIMUM_ARGV = 32
MAXIMUM_ALLOWED_COMMANDS = 8


def is_push_feed(feed: dict[str, Any]) -> bool:
    """True for a feed only an ingress route writes: the poller never reads it."""

    return feed.get("kind") == FeedKind.PUSH.value


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


class PrometheusVia(str, Enum):
    KUBE_PROXY = "kube_proxy"


def _kube_name(value: Any) -> str:
    text = bounded_string(value, maximum=63)
    require(_KUBE_NAME.fullmatch(text) is not None, "kubernetes name", WireRefusal.INVALID_STRING)
    return text


def _kube_port(value: Any) -> int | str:
    if isinstance(value, int) and not isinstance(value, bool):
        return bounded_int(value, minimum=1, maximum=65535)
    return _kube_name(value)


def _prometheus_source(value: Any) -> dict[str, Any]:
    """``{base_url, query}``, or ``{via: kube_proxy, namespace, service, port, query}`` (L4)."""

    m = checked_object(value, {"query"}, {"base_url", "via", "namespace", "service", "port"})
    query = bounded_string(m["query"], maximum=1024)
    if m.get("via") is None:
        m = checked_object(m, {"base_url", "query"})
        return {"base_url": source_url(m["base_url"]), "query": query}
    m = checked_object(m, {"via", "namespace", "service", "port", "query"})
    return {"via": enum_value(m["via"], PrometheusVia).value, "namespace": _kube_name(m["namespace"]),
            "service": _kube_name(m["service"]), "port": _kube_port(m["port"]), "query": query}


def kube_proxy_base_url(source: dict[str, Any]) -> str:
    """The Prometheus API base behind ``kubectl proxy`` for a ``via: kube_proxy`` source."""

    return (f"{KUBE_PROXY_BASE}/api/v1/namespaces/{source['namespace']}/services/"
            f"{source['service']}:{source['port']}/proxy")


def read_only_statement(value: Any) -> str:
    """A ``sql_readonly`` statement: up to 4 KiB, beginning SELECT / WITH. It may span lines
    (tab, LF and CR are admitted — a pasted query is multi-line); no other control character."""

    text = bounded_string(value, maximum=4096, layout=True)
    require(READ_ONLY_STATEMENT.match(text) is not None, "statement", WireRefusal.INVALID_STRING)
    return text


def _sql_readonly_source(value: Any) -> dict[str, Any]:
    from pathlib import Path

    m = checked_object(value, {"database", "query"})
    database = bounded_string(m["database"], maximum=1024)
    require(Path(database).is_absolute(), "database path", WireRefusal.INVALID_STRING)
    return {"database": database, "query": read_only_statement(m["query"])}


def _argv(value: Any) -> list[str]:
    return bounded_list(value, lambda item: bounded_string(item, maximum=1024), minimum=1, maximum=MAXIMUM_ARGV)


def _command_source(value: Any) -> dict[str, Any]:
    m = checked_object(value, {"argv", "allow", "extract"})
    argv = _argv(m["argv"])
    allow = bounded_list(m["allow"], _argv, minimum=1, maximum=MAXIMUM_ALLOWED_COMMANDS)
    require(argv in allow, "argv not in allow")
    return {"argv": argv, "allow": allow, "extract": extraction_path(m["extract"])}


def _push_source(value: Any) -> dict[str, Any]:
    checked_object(value, ())
    return {}


#: Feed kind -> its source block's reader. A kind absent here is unavailable.
_SOURCE_READERS = {
    FeedKind.HTTP_JSON: _http_json_source,
    FeedKind.PROMETHEUS: _prometheus_source,
    FeedKind.SQL_READONLY: _sql_readonly_source,
    FeedKind.COMMAND_ALLOWLISTED: _command_source,
    FeedKind.PUSH: _push_source,
}

FEED_KEYS_REQUIRED = frozenset({"version", "id", "kind", "interval_ms", "source"})
#: ``credential_ref`` (L1): an opaque reference into the home's Lens credential file
#: (``lens.credentials``), never the bytes. ``allow_private_network`` (L1, W10):
#: the explicit opt-in a loopback / private / link-local source needs.
#: ``value_type`` and ``plausible`` (W2): what the number IS, and the range a read
#: must fall in before any rule may see it.
#: ``outlier_guard`` (W2(c)): the median/deviation guard for a fast feed.
#: ``product`` (W5): the sealed product labels (:func:`read_product`).
FEED_KEYS_OPTIONAL = frozenset({"credential_ref", "allow_private_network", "value_type", "plausible",
                                "outlier_guard", "product"})


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
    OUTLIER = "outlier"
    FX_STALE = "fx_stale"


class ProductCondition(str, Enum):
    """A listing's condition. ``unknown`` is explicit: an absent condition never means ``new``."""

    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    OPEN_BOX = "open_box"
    FOR_PARTS = "for_parts"
    UNKNOWN = "unknown"


PRODUCT_KEYS = frozenset({"identity", "variant", "condition"})


def read_product(value: Any) -> dict[str, Any]:
    """``{identity, variant, condition}``: a GTIN/MPN or normalised model name (<= 128 bytes), the
    variant (<= 64; ``""`` when the product has none) and a :class:`ProductCondition`."""

    m = checked_object(value, PRODUCT_KEYS)
    return {"identity": bounded_string(m["identity"], maximum=128),
            "variant": bounded_string(m["variant"], maximum=64, empty=True),
            "condition": enum_value(m["condition"], ProductCondition).value}


_CURRENCY = re.compile(r"^[A-Z]{3}$")
#: An instant is integral epoch milliseconds inside the safe-integer range.
_MAXIMUM_INSTANT_MS = 9007199254740991


def _currency(value: Any) -> str:
    currency = bounded_string(value, maximum=3)
    require(_CURRENCY.fullmatch(currency) is not None, "currency", WireRefusal.INVALID_STRING)
    return currency


#: The longest a dated exchange rate may be older than the read it converts (7 d).
MAXIMUM_FX_AGE_MS = 7 * 24 * 60 * 60 * 1000


def read_total_cost(value: Any, currency: str) -> dict[str, Any]:
    """``{shipping?, tax_rate?, fx?: {feed_id, from, max_age_ms}}``; a default leaves no key (W5)."""

    m = checked_object(value, (), {"shipping", "tax_rate", "fx"})
    out: dict[str, Any] = {}
    if m.get("shipping") is not None:
        shipping = finite_number(m["shipping"])
        require(shipping >= 0, "shipping")
        if shipping:
            out["shipping"] = shipping
    if m.get("tax_rate") is not None:
        rate = finite_number(m["tax_rate"])
        require(0 <= rate <= 1, "tax_rate")
        if rate:
            out["tax_rate"] = rate
    if m.get("fx") is not None:
        fx = checked_object(m["fx"], {"feed_id", "from", "max_age_ms"})
        source = _currency(fx["from"])
        require(source != currency, "fx converts between two currencies")
        out["fx"] = {"feed_id": opaque_id(fx["feed_id"]), "from": source,
                     "max_age_ms": bounded_int(fx["max_age_ms"], minimum=MINIMUM_INTERVAL_MS,
                                               maximum=MAXIMUM_FX_AGE_MS)}
    return out


def read_value_type(value: Any) -> dict[str, Any]:
    """``{kind}``, plus ``currency`` (ISO 4217) exactly when the kind is money, and a
    money feed's optional ``total_cost``."""

    m = checked_object(value, {"kind"}, {"currency", "total_cost"})
    kind = enum_value(m["kind"], ValueKind)
    out: dict[str, Any] = {"kind": kind.value}
    if kind is ValueKind.MONEY:
        out["currency"] = _currency(m.get("currency"))
        if m.get("total_cost") is not None:
            cost = read_total_cost(m["total_cost"], out["currency"])
            if cost:
                out["total_cost"] = cost
    else:
        require(m.get("currency") is None, "currency only for money")
        require(m.get("total_cost") is None, "total_cost only for money")
    return out


def read_plausible(value: Any) -> dict[str, float]:
    m = checked_object(value, {"minimum", "maximum"})
    low, high = finite_number(m["minimum"]), finite_number(m["maximum"])
    require(low < high, "plausible range")
    return {"minimum": low, "maximum": high}


def value_type_of(feed: dict[str, Any]) -> dict[str, Any]:
    """The feed's value type; an untyped feed is a plain number."""

    return feed.get("value_type") or {"kind": ValueKind.NUMBER.value}


def comparable_type(feed: dict[str, Any]) -> dict[str, Any]:
    """What two feeds must share to be compared: the kind and the stored currency.

    A listing's shipping, tax and source currency fold into its total, so they may
    differ inside one ``best_of`` group (W5)."""

    value_type = value_type_of(feed)
    return {key: value_type[key] for key in ("kind", "currency") if key in value_type}


def fx_feed_id(feed: dict[str, Any]) -> str | None:
    """The exchange-rate feed this feed's total converts through, if any."""

    fx = (value_type_of(feed).get("total_cost") or {}).get("fx")
    return None if fx is None else fx["feed_id"]


MINIMUM_OUTLIER_WINDOW = 5
MAXIMUM_OUTLIER_WINDOW = 64
#: The median absolute deviation's consistency constant for a normal spread.
_MAD_SCALE = 1.4826


def read_outlier_guard(value: Any) -> dict[str, Any]:
    m = checked_object(value, {"window", "deviations"})
    deviations = finite_number(m["deviations"])
    require(0 < deviations <= 100, "outlier deviations")
    return {"window": bounded_int(m["window"], minimum=MINIMUM_OUTLIER_WINDOW, maximum=MAXIMUM_OUTLIER_WINDOW),
            "deviations": deviations}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def outlier_refused(feed: dict[str, Any], history: list[float], value: float) -> bool:
    """True when ``value`` is an outlier against the feed's last ``window`` reads (W2(c)).

    The guard abstains until it holds a full window, and over a flat window."""

    guard = feed.get("outlier_guard")
    if guard is None or len(history) < guard["window"]:
        return False
    window = history[-guard["window"]:]
    median = _median(window)
    spread = _median([abs(x - median) for x in window]) * _MAD_SCALE
    return spread > 0 and abs(value - median) > guard["deviations"] * spread


def total_cost(feed: dict[str, Any], price: float, fx_rate: float | None) -> tuple[float | None, ReadingRefusal | None]:
    """The stored value of a money read: its total cost in the feed's currency (W5).

    ``fx_rate`` is units of the feed's ``currency`` per one ``fx.from``, from a
    current dated rate; None when there is none, which is a gap ``fx_stale``."""

    cost = value_type_of(feed).get("total_cost")
    if not cost:
        return price, None
    total = (price + cost.get("shipping", 0.0)) * (1.0 + cost.get("tax_rate", 0.0))
    if "fx" in cost:
        if fx_rate is None or not fx_rate > 0:
            return None, ReadingRefusal.FX_STALE
        total *= fx_rate
    return round(total, 6), None


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
    if m.get("outlier_guard") is not None:
        feed["outlier_guard"] = read_outlier_guard(m["outlier_guard"])
    if m.get("product") is not None:
        feed["product"] = read_product(m["product"])
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
    #: The row's typed read reason when the caller has it (the store does). Read only by the
    #: ``missing_data`` rule; never on the wire (:meth:`to_json`) and never part of equality.
    reason: str | None = field(default=None, compare=False)

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
