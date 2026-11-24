"""Decode persisted Hermes journal records; replay callers must see gaps."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from functools import lru_cache

from .models import Event
from .serde import from_jsonable

__layer__ = "stores"

# Byte-preserving reads isolate invalid UTF-8 to the affected line.
_BAD_UTF8 = re.compile("[\udc80-\udcff]")


class UnreadableEvent(ValueError):
    """Replay across this record needs an authoritative snapshot."""


@lru_cache(maxsize=128)
def _warn_damage(digest: str, disposition: str) -> None:
    logging.getLogger(__name__).warning("event_journal_damage record=%s disposition=%s", digest, disposition)


def _report(line: str, disposition: str) -> None:
    raw = line.rstrip("\r\n").encode("utf-8", "surrogateescape")
    _warn_damage(hashlib.sha256(raw).hexdigest()[:16], disposition)


def decode_event_record(line: str) -> Event:
    clean = line.lstrip("\x00")
    try:
        if _BAD_UTF8.search(clean):
            raise ValueError("invalid UTF-8")
        raw = json.loads(clean)
        if not isinstance(raw, dict):
            raise ValueError("expected event object")
        event = from_jsonable(Event, raw)
        if (event.ts is None or event.ts.tzinfo is None or not isinstance(event.type, str)
                or not isinstance(event.payload, dict)):
            raise ValueError("invalid event fields")
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        _report(line, "unreadable")
        raise UnreadableEvent("unreadable event journal record") from exc
    if len(clean) != len(line):
        _report(line, "recovered_nul_prefix")
    return event


def history_event(line: str) -> Event | None:
    """History can omit an unreadable entry; replay must re-establish state."""
    try:
        return decode_event_record(line)
    except UnreadableEvent:
        return None


def recent_history(newest_first: Iterable[str], limit: int) -> list[Event]:
    selected: list[Event] = []
    for line in newest_first:
        if line.strip() and (event := history_event(line)) is not None:
            selected.append(event)
            if len(selected) == limit:
                break
    selected.reverse()
    return selected
