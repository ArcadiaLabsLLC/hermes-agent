"""Waking the rows a close unblocks (launcher row BRAIN-QUEUE-CLOSE-WAKES-DEPENDENTS, the hermes twin of
``EterniaLauncher/tool/queue/queue_wake.dart``).

A row waits on another when its status is ``BLOCKED <date>: <reason> — `<ID>` …`` and the reason names a brain.
Closing ``<ID>`` here lifts the block for every row of THIS brain that names it with ``hermes`` or ``another lane``,
so ``scripts/work_row.py close`` puts each back to ``READY <date>`` with an ``unblocked <date>`` segment naming the
close, in the same commit. Rows in the launcher or backend brains are theirs to wake.
"""

from __future__ import annotations

import re

from agent_runtime.work_store.grammar import SEPARATOR, STATUS, Status, parse_note, split_segments

#: The reasons whose blocker ID resolves in this brain.
OWN_BRAIN_REASONS = ("hermes", "another lane")
_BLOCKER_ID = re.compile(r"^`([A-Z0-9][A-Z0-9._-]*)`")


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


def unblocked_segment(closed_id: str, close_date: str, how: str) -> str:
    """The record a wake leaves beside the new READY status; ``how`` is ``DONE <sha>`` / ``REFUTED <sha>`` /
    ``CLOSED``."""

    said = "closed by the owner" if how == "CLOSED" else f"closed {how}"
    return f"unblocked {close_date}: `{closed_id}` {said}"


def wake_dependents(text: str, closed_id: str, close_date: str, how: str) -> tuple[str, list[str]]:
    """``text`` with every row of this brain BLOCKED on ``closed_id`` put back to READY, and the woken IDs.

    The claim, rulings and every other segment are kept; a line's own ``\\r`` is kept.
    """

    lines = text.split("\n")
    woken: list[str] = []
    for row in parse_note(text, slot="", note=""):
        if row.status is not Status.BLOCKED:
            continue
        named = blocked_on(row.status_body)
        if named is None or named[0] not in OWN_BRAIN_REASONS or named[1] != closed_id:
            continue
        raw = lines[row.line_no - 1]
        carriage = "\r" if raw.endswith("\r") else ""
        line = raw[:-1] if carriage else raw
        segments = split_segments(line)
        kept: list[str] = []
        replaced = False
        for index, segment in enumerate(segments):
            if index > 0 and not replaced and STATUS.match(segment.strip()):
                kept += [f"READY {close_date}", unblocked_segment(closed_id, close_date, how)]
                replaced = True
                continue
            kept.append(segment)
        if not replaced:
            continue
        lines[row.line_no - 1] = SEPARATOR.join(kept) + carriage
        woken.append(row.ref.id)
    return "\n".join(lines), woken
