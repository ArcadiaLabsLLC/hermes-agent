"""Lens poll sources: feed kind -> its reader (the table, not a ladder).

:func:`read_feed_source` is the one door a poll or a preview reads through. It
resolves the feed's ``credential_ref`` from the hermes credential pool FOR THIS
READ (``lens.credentials``) and hands the source only the request headers; a
reference this home does not hold is a ``credential_missing`` read, never an
unauthenticated one.

:func:`typed_result` is the one place a read meets its feed's ``value_type``,
``plausible`` range, outlier guard and total cost (W2, W5): the poller records it
and the preview returns it, so a preview never shows a value the poller would
store as a gap.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ..feed import FeedKind, ReadingRefusal, fx_feed_id, outlier_refused, total_cost, typed_reading
from . import http_json, prometheus
from .transport import ReadReason, ReadResult, unavailable

__layer__ = "lanes"

SOURCE_READERS: dict[FeedKind, Callable[..., ReadResult]] = {
    FeedKind.HTTP_JSON: http_json.read,
    FeedKind.PROMETHEUS: prometheus.read,
}


def read_feed_source(feed: dict[str, Any], *, client: Any = None, resolver: Any = None) -> ReadResult:
    from ..credentials import resolve_credential

    reader = SOURCE_READERS.get(FeedKind(feed["kind"]))
    if reader is None:
        return unavailable(ReadReason.SOURCE_FAILED)
    headers = {"Accept": "application/json"}
    ref = feed.get("credential_ref")
    if ref is not None:
        credential = resolve_credential(ref)
        if credential is None:
            return unavailable(ReadReason.CREDENTIAL_MISSING)
        headers.update(credential.headers())
    try:
        return reader(feed, headers=headers, client=client, resolver=resolver)
    except Exception:
        return unavailable(ReadReason.SOURCE_FAILED)


def typed_result(feed: dict[str, Any], result: ReadResult, *, history: Sequence[float] = (),
                 fx_rate: float | None = None) -> ReadResult:
    """``result`` as a rule would see it: a read the feed's type, range or outlier guard
    refuses is a gap; a money read with a ``total_cost`` is its total.

    ``history`` is the feed's recent raw reads (the outlier window); ``fx_rate`` the
    current dated exchange rate when the feed converts, else None."""

    value, refusal = typed_reading(feed, result.value)
    if value is not None and outlier_refused(feed, list(history), value):
        value, refusal = None, ReadingRefusal.OUTLIER
    if value is not None:
        value, refusal = total_cost(feed, value, fx_rate)
    if refusal is None:
        return ReadResult(value=value, reason=result.reason, http_status=result.http_status)
    return ReadResult(value=None, reason=ReadReason(refusal.value), http_status=result.http_status)


def preview_reads(manifest: dict[str, Any], *, client: Any = None, resolver: Any = None) -> dict[str, ReadResult]:
    """One read per feed, typed as the poller would store it, in manifest order.

    A converting feed's rate is this preview's own read of its rate feed (W5); the
    outlier guard has no history in a preview, so it abstains."""

    raw = {feed["id"]: read_feed_source(feed, client=client, resolver=resolver) for feed in manifest["feeds"]}
    feeds = {feed["id"]: feed for feed in manifest["feeds"]}
    out: dict[str, ReadResult] = {}
    for feed_id, feed in feeds.items():
        rate_id = fx_feed_id(feed)
        rate = None if rate_id is None else typed_result(feeds[rate_id], raw[rate_id]).value
        out[feed_id] = typed_result(feed, raw[feed_id], fx_rate=rate)
    return out
