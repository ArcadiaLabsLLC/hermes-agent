"""The ``waits:`` field (row FH-QUEUE-WAITS-FIELD, task TASK-WAITS-ARE-A-FIELD; the hermes twin of
``EterniaLauncher/tool/queue/queue_waits.dart``, which sets the shape).

A DEFERRED or BLOCKED row names what it waits for in ONE machine-read segment, ``waits: <entry>[, <entry>…]``
(entries also joined by `` and ``), each entry a backticked row ID — in the row's own brain, or with a brain word
first (``launcher `BRAIN-A``` / ``backend `OPS-B``` / ``hermes `RT-C```) — or an event of :data:`WAIT_EVENTS`.

A close LISTS the DEFERRED (and BLOCKED) rows whose field names the closed row, for review; it never re-statuses
them, because an owner deferral stays the owner's. A BLOCKED row's `` — `ID` `` list keeps its own wake
(:mod:`agent_runtime.work_store.wake`), and a row that list already names is left to it. The launcher's
``dart tool/queue/wake.dart`` lists, across all three brains, every row whose wait has fired (``--event`` for an
event, ``--missing`` for the rows that name none). The Windows box and the teammate file and close rows with the
same tools.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from agent_runtime.work_store.grammar import WAIT_EVENTS, WAITS_PREFIX, Row, Status, WaitTarget, parse_waits
from agent_runtime.work_store.wake import blockers_of

__layer__ = "policy"

__all__ = ["WAIT_EVENTS", "WaitTarget", "field_waiters_of", "has_machine_wait", "is_waiting", "listing_line",
           "missing_waits", "parse_waits", "waits_of"]


def waits_of(row: Row, own: str) -> list[WaitTarget] | None:
    """The targets of ``row``'s ``waits:`` field read for brain ``own``; None when it carries none (or an unreadable
    one, which the grammar names)."""

    for segment in row.segments[1:]:
        if segment.startswith(WAITS_PREFIX):
            targets, problem = parse_waits(segment[len(WAITS_PREFIX):], own)
            return None if problem else targets
    return None


def is_waiting(row: Row) -> bool:
    """DEFERRED or BLOCKED: the rows a fired wait lists."""

    return row.status in (Status.DEFERRED, Status.BLOCKED)


def has_machine_wait(row: Row, own: str) -> bool:
    """A ``waits:`` field, or (BLOCKED only) a `` — `ID` `` list in its status."""

    if any(s.startswith(WAITS_PREFIX) for s in row.segments[1:]):
        return True
    return row.status is Status.BLOCKED and bool(blockers_of(row.status_body))


def missing_waits(rows: Iterable[Row], own: str) -> list[Row]:
    """The DEFERRED and BLOCKED rows of ``rows`` (living in ``own``) that name no machine-read wait — a WARNING for
    one wave, until the backfill (launcher row BRAIN-QUEUE-WAITS-BACKFILL) makes it required."""

    return [row for row in rows if is_waiting(row) and not has_machine_wait(row, own)]


def field_waiters_of(rows_by_brain: Mapping[str, Iterable[Row]], closed_id: str, closed_brain: str) -> list[tuple[str, Row]]:
    """``(brain, row)`` for every DEFERRED or BLOCKED row whose ``waits:`` field names ``closed_id`` of
    ``closed_brain`` — what a close lists for review. A BLOCKED row whose status list already names it is the
    wake's (:func:`agent_runtime.work_store.wake.wake_dependents`), not listed twice."""

    found: list[tuple[str, Row]] = []
    for brain, rows in rows_by_brain.items():
        for row in rows:
            # MUTATION: drop `is_waiting(row) and` (or narrow it to BLOCKED) and
            # test_a_close_lists_the_deferred_row_whose_waits_field_names_it reds.
            if not (is_waiting(row) and row.ref.id):
                continue
            targets = waits_of(row, brain) or []
            if not any(t.row_id == closed_id and t.brain == closed_brain for t in targets):
                continue
            if row.status is Status.BLOCKED and brain == "hermes" and (closed_id, closed_brain) in blockers_of(
                    row.status_body):
                continue
            found.append((brain, row))
    return found


def listing_line(brain: str, row: Row, closed_id: str, closed_brain: str) -> str:
    """The line a close prints for a row its ``waits:`` field woke: listed for review, never re-statused."""

    status = row.status.value if row.status else "live"
    keep = ("an owner deferral stays the owner's, never re-statused by a tool" if row.status is Status.DEFERRED
            else "re-status it by hand")
    return (f"waited on it: `{row.ref.id}` ({status}, {brain} / {row.ref.note.rsplit('/', 1)[-1] or '?'}): `{closed_id}` "
            f"({closed_brain}) is closed — for review; {keep}")
