"""Waking the rows a close unblocks (launcher row BRAIN-QUEUE-CLOSE-WAKES-DEPENDENTS, the hermes twin of
``EterniaLauncher/tool/queue/queue_wake.dart``).

A row waits on another when its status is ``BLOCKED <date>: <reason> — `<ID>` …`` and the reason names a brain.
Closing ``<ID>`` here lifts the block for every row of THIS brain that names it with ``hermes`` or ``another lane``,
so ``scripts/work_row.py close`` puts each back to ``READY <date>`` with an ``unblocked <date>`` segment naming the
close, in the same commit. Rows in the launcher or backend brains are theirs to wake.

A row may wait on SEVERAL rows: its block opens with a list, ``— `A` then `B`, `C` and `D`: why``. Closing one of
them wakes the row only when no other row of the list is still open; otherwise the row stays BLOCKED, re-pointed at
the ones still open (:func:`wake_dependents`, row RT-QUEUE-CLOSE-WAKES-ROW-STILL-HELD-BY-OTHERS — three closes of
2026-11-12 woke a row five others still held, or left it naming an archived row first, and reddened the queue gate).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from agent_runtime.work_store.grammar import SEPARATOR, STATUS, OutcomeKind, Status, parse_note, split_segments

__layer__ = "policy"

#: The reasons whose blocker ID resolves in this brain.
OWN_BRAIN_REASONS = ("hermes", "another lane")
_BLOCKER_ID = re.compile(r"^`([A-Z0-9][A-Z0-9._-]*)`")
#: One more row of a block's opening list: a joiner (``,`` / ``then`` / ``and`` / ``&`` / ``+``) and a backticked ID.
_NEXT_BLOCKER = re.compile(r"^(?:\s*,\s*(?:(?:and|then)\s+)?|\s+(?:then|and|&|\+)\s+)`([A-Z0-9][A-Z0-9._-]*)`")


def blocked_on(status_body: str) -> tuple[str, str] | None:
    """``(reason, ID)`` of a BLOCKED status body that names a row first after its dash, else None."""

    for reason in ("owner decision", "owner sitting", "backend", "hermes", "launcher", "upstream", "another lane"):
        if status_body == reason or any(status_body.startswith(reason + c) for c in " :(,"):
            rest = status_body[len(reason):]
            dash = rest.find(" — ")
            if dash < 0:
                return None
            match = _BLOCKER_ID.match(rest[dash + 3:].strip())
            return (reason, match.group(1)) if match else None
    return None


def blocker_list(status_body: str) -> tuple[str, list[str], str] | None:
    """``(head, IDs, tail)`` of a BLOCKED status body whose detail opens with one row or a list of rows: ``head``
    runs through the dash, ``tail`` is what follows the last listed ID (``head + "`A` then `B`" + tail`` is the
    body). A backticked name later in the prose is not a blocker. None when the body names no row first."""

    named = blocked_on(status_body)
    if named is None:
        return None
    start = status_body.index(" — ", len(named[0])) + 3
    start += len(status_body[start:]) - len(status_body[start:].lstrip())
    ids, at = [named[1]], start + len(named[1]) + 2
    while (more := _NEXT_BLOCKER.match(status_body[at:])) is not None:
        ids.append(more.group(1))
        at += more.end()
    return status_body[:start], ids, status_body[at:]


def unblocked_segment(closed_id: str, close_date: str, how: str) -> str:
    """The record a wake leaves beside the new READY status; ``how`` is ``DONE <sha>`` / ``REFUTED <sha>`` /
    ``CLOSED``."""

    said = "closed by the owner" if how == OutcomeKind.CLOSED else f"closed {how}"
    return f"unblocked {close_date}: `{closed_id}` {said}"


@dataclass(frozen=True)
class Stepped:
    """What a close did to the rows that waited on the closed row, in one note."""

    text: str
    #: Put back to READY: no other row of their list is still open.
    woken: list[str] = field(default_factory=list)
    #: Still BLOCKED, re-pointed: the row's ID -> the rows of its list that are still open, in order.
    held: dict[str, list[str]] = field(default_factory=dict)
    #: Left BLOCKED naming only the closed row (``wake=False``): the caller's to re-status.
    stranded: list[str] = field(default_factory=list)


def wake_dependents(text: str, closed_id: str, close_date: str, how: str, *, live_ids: Collection[str],
                    wake: bool = True) -> Stepped:
    """``text`` after ``closed_id`` closed, for every row of this brain whose block lists it.

    A row whose list still names a row in ``live_ids`` (the IDs open after the close, in every brain read) stays
    BLOCKED with its date and its words, the list cut to the rows still open — never woken while another row holds
    it, and never left naming the archived row. A row nothing else holds is woken — back to READY with an
    ``unblocked`` segment — unless ``wake`` is false, when it is left as it stands and reported ``stranded``.
    The claim, rulings and every other segment are kept; a line's own ``\\r`` is kept.
    """

    lines = text.split("\n")
    stepped = Stepped(text)
    for row in parse_note(text, slot="", note=""):
        if row.status is not Status.BLOCKED:
            continue
        listed = blocker_list(row.status_body)
        named = blocked_on(row.status_body)
        if listed is None or named[0] not in OWN_BRAIN_REASONS or closed_id not in listed[1]:
            continue
        head, ids, tail = listed
        # MUTATION: `still_open = []` and test_a_close_keeps_a_row_other_rows_still_hold_blocked reddens.
        still_open = [blocker for blocker in dict.fromkeys(ids) if blocker != closed_id and blocker in live_ids]
        if still_open:
            first, rest = f"`{still_open[0]}`", ", ".join(f"`{blocker}`" for blocker in still_open[1:])
            status = [f"BLOCKED {row.status_date}: {head}{first}{' then ' + rest if rest else ''}{tail}"]
        elif wake:
            status = [f"READY {close_date}", unblocked_segment(closed_id, close_date, how)]
        else:
            stepped.stranded.append(row.ref.id)
            continue
        raw = lines[row.line_no - 1]
        carriage = "\r" if raw.endswith("\r") else ""
        line = raw[:-1] if carriage else raw
        segments = split_segments(line)
        kept: list[str] = []
        replaced = False
        for index, segment in enumerate(segments):
            if index > 0 and not replaced and STATUS.match(segment.strip()):
                kept += status
                replaced = True
                continue
            kept.append(segment)
        if not replaced:
            continue
        lines[row.line_no - 1] = SEPARATOR.join(kept) + carriage
        if still_open:
            stepped.held[row.ref.id] = still_open
        else:
            stepped.woken.append(row.ref.id)
    return Stepped("\n".join(lines), stepped.woken, stepped.held, stepped.stranded)
