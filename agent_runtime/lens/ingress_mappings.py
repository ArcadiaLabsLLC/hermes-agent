"""Lens push-door MAPPINGS: one POSTed body -> readings on a route's ``push`` feeds.

Plan ``p10-agent-2026-10-19.md`` §5.4 L3.2. The body kind is the route's
(``ingress_routes.IngressKind``) and the reader is a table, not a ladder
(:data:`BODY_READERS`):

* ``alertmanager`` (webhook ``version: "4"``) and ``grafana`` (unified alerting) —
  every alert lands on the feed its ``labels.alertname`` maps to (else the route's
  default feed). A feed's reading is the COUNT of its alerts this body says are
  ``firing``: a body that only resolves writes ``0`` — a recovery read, which a
  rule above zero never opens on. A firing reading is observed at its receipt (the
  notification is the source's "now"); an all-resolved reading at the newest
  ``endsAt`` it carries, never later than its receipt.
* ``generic`` — each mapped selector takes one number (the poll door's
  ``http_json.select`` / ``number_of``: a missing key or a non-number is a recorded
  gap with its typed reason, never a guessed value); ``observed_at`` names the
  source's time (epoch ms, or an RFC 3339 string), never later than the receipt.

The tree has no ``source_alert.py`` and no ``jmespath`` in the core closure (it is
the ``bedrock`` extra's), so a reading is :class:`IngressReading` and a path is the
poll door's bounded selector.

:func:`ingest` is the one write: each reading goes through the poller's own record
step (``LensPoller.record_pushed``: typed, stored, the feed's rules evaluated), so a
pushed Episode opens exactly as a polled one would. Alert labels and annotations are
NEVER stored: a reading is a number, a time and a typed reason (W9: free text from a
source reaches a turn only fenced, and this door keeps none).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable

from .feed import is_push_feed
from .ingress_routes import IngressKind
from .sources.http_json import number_of, select
from .sources.transport import ReadReason
from .store import LensStore, MonitorState, from_ms

__layer__ = "lanes"

#: The most alerts one alert body may carry (Alertmanager's own group cap is far lower).
MAXIMUM_ALERTS = 1024
_ALERTMANAGER_VERSION = "4"


class IngressRefusal(str, Enum):
    """Why a POST wrote no reading. The listener answers each as a 4xx with no detail."""

    BAD_BODY = "bad_body"
    NOT_ENABLED = "monitor_not_enabled"
    #: The listener's own (L3.3).
    UNKNOWN_ROUTE = "unknown_route"
    OVERSIZE = "oversize"
    BAD_SIGNATURE = "bad_signature"
    REPLAY = "replay"


class IngressError(ValueError):
    def __init__(self, code: IngressRefusal) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class IngressReading:
    feed_id: str
    value: float | None
    reason: ReadReason
    observed_at: datetime


def _source_time(value: Any) -> datetime | None:
    """An RFC 3339 instant (Go's nanoseconds truncated to micro) or epoch ms; None otherwise."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return from_ms(int(value))
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value or value.startswith("0001-"):
        return None
    text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    head, dot, rest = text.partition(".")
    if dot:
        digits = len(rest) - len(rest.lstrip("0123456789"))
        text = f"{head}.{rest[:min(digits, 6)]}{rest[digits:]}"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo is not None else None


def _not_after(moment: datetime | None, received: datetime) -> datetime:
    return received if moment is None or moment > received else moment


def _alerts(body: Any, kind: IngressKind) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("alerts"), list):
        raise IngressError(IngressRefusal.BAD_BODY)
    if kind is IngressKind.ALERTMANAGER and str(body.get("version")) != _ALERTMANAGER_VERSION:
        raise IngressError(IngressRefusal.BAD_BODY)
    alerts = body["alerts"]
    if len(alerts) > MAXIMUM_ALERTS or not all(isinstance(alert, dict) for alert in alerts):
        raise IngressError(IngressRefusal.BAD_BODY)
    return alerts


def alert_readings(body: Any, mapping: dict[str, Any], received: datetime, *,
                   kind: IngressKind = IngressKind.ALERTMANAGER) -> list[IngressReading]:
    """One reading per mapped feed the body names: its firing count, observed as above."""

    firing: dict[str, int] = {}
    resolved_at: dict[str, datetime | None] = {}
    for alert in _alerts(body, kind):
        status = alert.get("status")
        if status not in ("firing", "resolved"):
            raise IngressError(IngressRefusal.BAD_BODY)
        labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
        feed_id = mapping["alerts"].get(labels.get("alertname"), mapping["feed_id"])
        firing[feed_id] = firing.get(feed_id, 0) + (status == "firing")
        if status == "resolved":
            ended = _source_time(alert.get("endsAt"))
            known = resolved_at.get(feed_id)
            resolved_at[feed_id] = ended if known is None or (ended is not None and ended > known) else known
    return [IngressReading(feed_id=feed_id, value=float(count), reason=ReadReason.OK,
                           observed_at=received if count else _not_after(resolved_at.get(feed_id), received))
            for feed_id, count in sorted(firing.items())]


def generic_readings(body: Any, mapping: dict[str, Any], received: datetime) -> list[IngressReading]:
    observed = received
    if mapping.get("observed_at"):
        found, value = select(body, mapping["observed_at"])
        observed = _not_after(_source_time(value) if found else None, received)
    out = []
    for path, feed_id in sorted(mapping["values"].items()):
        found, value = select(body, path)
        number = number_of(value) if found else None
        reason = (ReadReason.OK if number is not None
                  else ReadReason.NOT_A_NUMBER if found else ReadReason.SELECTOR_MISSING)
        out.append(IngressReading(feed_id=feed_id, value=number, reason=reason, observed_at=observed))
    return out


BODY_READERS: dict[IngressKind, Callable[[Any, dict[str, Any], datetime], list[IngressReading]]] = {
    IngressKind.ALERTMANAGER: lambda body, mapping, at: alert_readings(body, mapping, at,
                                                                       kind=IngressKind.ALERTMANAGER),
    IngressKind.GRAFANA: lambda body, mapping, at: alert_readings(body, mapping, at, kind=IngressKind.GRAFANA),
    IngressKind.GENERIC: generic_readings,
}


def ingest(route: dict[str, Any], raw: bytes, *, received: datetime, store: LensStore | None = None,
           poller: Any = None) -> list[IngressReading]:
    """Map ``raw`` through ``route`` and record every reading (rules evaluated). Returns them.

    Refused whole (nothing written) when the body is not JSON or not its kind's shape,
    when the monitor is not ENABLED, or when a mapped feed is no longer a ``push`` feed
    of the sealed revision."""

    from .poller import LensPoller

    store = store or LensStore()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise IngressError(IngressRefusal.BAD_BODY) from None
    monitor = store.get(route["monitor_id"])
    if monitor["state"] != MonitorState.ENABLED.value or monitor["sealed"] is None:
        raise IngressError(IngressRefusal.NOT_ENABLED)
    manifest = monitor["sealed"]["manifest"]
    feeds = {feed["id"]: feed for feed in manifest["feeds"] if is_push_feed(feed)}
    readings = BODY_READERS[IngressKind(route["kind"])](body, route["mapping"], received)
    if any(reading.feed_id not in feeds for reading in readings):
        raise IngressError(IngressRefusal.BAD_BODY)
    poller = poller or LensPoller(store_factory=lambda: store, clock=lambda: received)
    for reading in readings:
        poller.record_pushed(store, route["monitor_id"], manifest, feeds[reading.feed_id], value=reading.value,
                             reason=reading.reason, observed=reading.observed_at, received=received)
    return readings
