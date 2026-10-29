"""Reading the event log after a durable cursor (row ``RT-LAUNCHER-EVENT-CURSOR``).

Plan: ``docs/agent-runtime-harness/planned/launcher-event-cursor-2026-10-28.md``.
The event log IS the journal: ``event_rotation`` gives every line a logical
offset that survives rotation, and ``resume_floor_offset`` names the oldest
offset still replayable. This module adds the two things a client that keeps
its own position needs and the log does not have:

* a **journal id** — a UUID minted once into ``paths.events_journal_path()`` —
  so a cursor taken from another store (a reset, another namespace) can never
  be read as an offset into this one;
* a **bounded page read** — at most ``limit`` matches and at most
  ``scan_budget`` bytes scanned, with the next offset always past every byte
  scanned, so a page of zero matches still makes progress.

It answers offsets and events; which kinds a caller may see and what of their
payload leaves is the method's (``serve_rpc/events_after.py``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from agent_runtime import event_rotation, paths
from agent_runtime.events import EventLog
from agent_runtime.locks import events_lock
from agent_runtime.models import Event
from agent_runtime.serde import write_json_atomic

__layer__ = "stores"

__all__ = [
    "JournalRefusal",
    "Page",
    "SCAN_BUDGET_BYTES",
    "UNREADABLE_LINE",
    "SkippedSpan",
    "format_cursor",
    "journal_id",
    "parse_cursor",
    "read_after",
]

#: The most journal one page scans, matched or not.
SCAN_BUDGET_BYTES = 4 * 1024 * 1024


class JournalRefusal(StrEnum):
    """Why a page carries no events from the cursor asked for — each says where to go next."""

    #: The cursor names another journal (a reset store, another namespace).
    JOURNAL_MISMATCH = "journal_mismatch"
    #: The offset is below the oldest replayable offset; the span between is lost.
    JOURNAL_TRUNCATED = "journal_truncated"
    #: The offset is past the tail: the cursor's baseline is not this journal's.
    CURSOR_AHEAD_OF_JOURNAL = "cursor_ahead_of_journal"
    #: The tail cannot be stat'ed or the live slice is gone; keep the cursor and retry.
    JOURNAL_UNREADABLE = "journal_unreadable"


#: The reason a skipped span carries: a whole line (newline-terminated) that does not decode.
UNREADABLE_LINE = "journal_line_unreadable"


@dataclass(frozen=True, slots=True)
class SkippedSpan:
    """One unreadable line a page passed: logical offsets ``[start, end)``."""

    start: int
    end: int
    reason: str = UNREADABLE_LINE


@dataclass(frozen=True, slots=True)
class Page:
    """One bounded read: ``events`` as ``(end offset of the line, event)``, and where to read next."""

    journal: str
    next_offset: int
    at_tail: bool
    events: list[tuple[int, Event]] = field(default_factory=list)
    refused: JournalRefusal | None = None
    #: The offset a refused caller moves to (the tail, or the floor for a truncation).
    resume_offset: int | None = None
    lost_bytes: int | None = None
    #: Unreadable lines the page scanned past, oldest first.
    skipped: list[SkippedSpan] = field(default_factory=list)


def journal_id() -> str:
    """This store's journal id, minted on first ask (under the event-log lock, so two first askers agree)."""

    path = paths.events_journal_path()
    found = _read_journal_id(path)
    if found:
        return found
    with events_lock():
        found = _read_journal_id(path)
        if found:
            return found
        minted = uuid.uuid4().hex
        write_json_atomic(path, {"version": 1, "journal_id": minted})
        return minted


def _read_journal_id(path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = raw.get("journal_id") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value and ":" not in value else None


def format_cursor(journal: str, offset: int) -> str:
    return f"{journal}:{int(offset)}"


def parse_cursor(cursor: str) -> tuple[str, int] | None:
    """``(journal_id, offset)``, or ``None`` for a string that is not a cursor."""

    journal, sep, offset = cursor.rpartition(":")
    if not sep or not journal or not offset.isdigit():
        return None
    return journal, int(offset)


def read_after(
    cursor: tuple[str, int] | None,
    wanted: Callable[[Event], bool],
    *,
    limit: int,
    scan_budget: int | None = None,
) -> Page:
    """The page after ``cursor`` (``None``: no history — the page starts at the tail)."""

    journal = journal_id()
    floor = event_rotation.resume_floor_offset()
    if floor is None:
        return Page(journal, cursor[1] if cursor else 0, False, refused=JournalRefusal.JOURNAL_UNREADABLE)
    tail = event_rotation.log_end_offset()
    if cursor is None:
        return Page(journal, tail, True)
    asked_journal, offset = cursor
    if asked_journal != journal:
        return Page(journal, tail, False, refused=JournalRefusal.JOURNAL_MISMATCH, resume_offset=tail)
    if offset > tail:
        return Page(journal, tail, False, refused=JournalRefusal.CURSOR_AHEAD_OF_JOURNAL, resume_offset=tail)
    if offset < floor:
        return Page(journal, floor, False, refused=JournalRefusal.JOURNAL_TRUNCATED, resume_offset=floor,
                    lost_bytes=floor - offset)
    budget = SCAN_BUDGET_BYTES if scan_budget is None else scan_budget
    events, position, skipped = _scan(offset, wanted, limit=limit, scan_budget=budget)
    return Page(journal, position, position >= event_rotation.log_end_offset(), events, skipped=skipped)


def _scan(offset: int, wanted: Callable[[Event], bool], *, limit: int,
          scan_budget: int) -> tuple[list[tuple[int, Event]], int, list[SkippedSpan]]:
    """Matches from ``offset``, the end of the last line scanned (always at least one line, if
    any), and the unreadable lines passed on the way."""

    events: list[tuple[int, Event]] = []
    skipped: list[SkippedSpan] = []
    position = offset
    lines = EventLog().iter_from_offset(offset)
    while len(events) < limit:
        try:
            end, event = next(lines)
        except StopIteration:
            break
        except ValueError:  # JSON and UTF-8 decode errors alike
            span = _whole_line_at(position)
            if span is None:
                break  # a torn tail, still being appended: the next page reads it whole
            if span[1] - offset > scan_budget and position > offset:
                break
            skipped.append(SkippedSpan(*span))
            position = span[1]
            lines = EventLog().iter_from_offset(position)
            continue
        if end - offset > scan_budget and position > offset:
            break
        position = end
        if wanted(event):
            events.append((end, event))
    return events, position, skipped


def _whole_line_at(offset: int) -> tuple[int, int] | None:
    """The logical span of the first non-blank line at or after ``offset``, or ``None`` when that
    line has no terminating newline yet (a torn tail) or there is none."""

    for slice_path, slice_start, seek_within in event_rotation.offset_reads(offset):
        try:
            handle = open(slice_path, "rb")
        except FileNotFoundError:
            continue
        with handle:
            handle.seek(seek_within)
            for raw in handle:
                if not raw.strip():
                    continue
                end = slice_start + handle.tell()
                if not raw.endswith(b"\n"):
                    return None
                return end - len(raw), end
    return None
