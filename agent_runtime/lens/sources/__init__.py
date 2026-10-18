"""Lens poll sources: feed kind -> its reader (the table, not a ladder).

:func:`read_feed_source` is the one door a poll or a preview reads through. It
resolves the feed's ``credential_ref`` from the hermes credential pool FOR THIS
READ (``lens.credentials``) and hands the source only the request headers; a
reference this home does not hold is a ``credential_missing`` read, never an
unauthenticated one.

:func:`typed_result` is the one place a read meets its feed's ``value_type`` and
``plausible`` range (W2): the poller records it and the preview returns it, so a
preview never shows a value the poller would store as a gap.
"""

from __future__ import annotations

from typing import Any, Callable

from ..feed import FeedKind, typed_reading
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


def typed_result(feed: dict[str, Any], result: ReadResult) -> ReadResult:
    """``result`` as a rule would see it: a read the feed's type or range refuses is a gap."""

    value, refusal = typed_reading(feed, result.value)
    if refusal is None:
        return result
    return ReadResult(value=value, reason=ReadReason(refusal.value), http_status=result.http_status)
