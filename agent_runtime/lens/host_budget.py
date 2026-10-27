"""W3: one read budget per HOST, shared by every monitor that reads it.

Plan ``LENS_EXTENSIONS_2026-10-27.md`` §2 decisions 1–3. A feed's own pacing
(``poller._FeedClock.period``) cannot see that four monitors read one host; this can.

* The host key is the lowercase hostname and effective port of the URL a pulled HTTP
  source reads (``http_json``'s ``url``, ``prometheus``'s ``base_url`` or its
  ``via: kube_proxy`` base). ``sql_readonly``, ``command_allowlisted`` and ``push`` read
  no host and spend no budget (:func:`host_key` answers None).
* Each host has a token bucket, in memory, process-wide (one poller per serve owns every
  read): a public host refills at ``host_reads_per_minute_public`` (burst
  :data:`PUBLIC_BURST`), a host a feed reaches through ``allow_private_network`` — or the
  loopback ``kubectl proxy`` — at ``host_reads_per_minute_private`` (burst
  :data:`PRIVATE_BURST`): an operator's own Prometheus is not a third party.
* A refused take is the poller's to DEFER, never to drop (``poller.LensPoller._read_due``).

No manifest key: a manifest describes a monitor, the budget describes a host shared by
monitors. The rates are root-config knobs (``lens/settings.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit

from .feed import FeedKind, kube_proxy_base_url

__layer__ = "policy"

PUBLIC_BURST = 5
PRIVATE_BURST = 20
_DEFAULT_PORTS = {"http": 80, "https": 443}


#: The URL each pulled HTTP kind reads, by kind (a kind not here reads no host).
_SOURCE_URL: dict[FeedKind, Callable[[dict[str, Any]], str]] = {
    FeedKind.HTTP_JSON: lambda source: source["url"],
    FeedKind.PROMETHEUS: lambda source: kube_proxy_base_url(source) if "via" in source else source["base_url"],
}


def host_key(feed: dict[str, Any]) -> str | None:
    """``"<host>:<port>"`` for a pulled HTTP feed, else None (no host, no budget)."""

    reader = _SOURCE_URL.get(FeedKind(feed["kind"]))
    if reader is None:
        return None
    parts = urlsplit(reader(feed["source"]))
    host = (parts.hostname or "").lower()
    port = parts.port or _DEFAULT_PORTS.get(parts.scheme.lower(), 0)
    return f"{host}:{port}"


def is_private_reader(feed: dict[str, Any]) -> bool:
    """True when the feed reads its host as the operator's own (the private rate applies)."""

    return bool(feed.get("allow_private_network")) or "via" in feed["source"]


@dataclass
class _Bucket:
    tokens: float
    at: datetime


@dataclass
class HostBudget:
    """Token buckets keyed by host. ``take`` spends one read or answers False."""

    public_per_minute: int
    private_per_minute: int
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    def take(self, key: str, now: datetime, *, private: bool) -> bool:
        rate = (self.private_per_minute if private else self.public_per_minute) / 60.0
        burst = float(PRIVATE_BURST if private else PUBLIC_BURST)
        bucket = self._buckets.setdefault(key, _Bucket(tokens=burst, at=now))
        elapsed = max(0.0, (now - bucket.at).total_seconds())
        bucket.tokens, bucket.at = min(burst, bucket.tokens + elapsed * rate), now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True
