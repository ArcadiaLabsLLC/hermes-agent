"""Waking the rows a close unblocks (launcher row BRAIN-QUEUE-CLOSE-WAKES-DEPENDENTS, the hermes twin of
``EterniaLauncher/tool/queue/queue_wake.dart``).

A row waits on another when its status is ``BLOCKED <date>: <reason> — `<ID>` …`` and the reason names a brain.
Closing ``<ID>`` here lifts the block for every row of THIS brain that lists it as a hermes row (``hermes`` or
``another lane`` first, or ``hermes `<ID>``` later in the list), so ``scripts/work_row.py close`` puts each back
to ``READY <date>`` with an ``unblocked <date>`` segment naming the close, in the same commit. Rows in the launcher
or backend brains are theirs to wake.

A row may wait on SEVERAL rows: its block opens with a list, ``— `A` then `B`, `C` and `D`: why``. Closing one of
them wakes the row only when no other row of the list is still open; otherwise the row stays BLOCKED, re-pointed at
the ones still open (:func:`wake_dependents`, row RT-QUEUE-CLOSE-WAKES-ROW-STILL-HELD-BY-OTHERS — three closes of
2026-11-12 woke a row five others still held, or left it naming an archived row first, and reddened the queue gate).

A later row of the list may live in another brain and says so with the brain's word before it: ``BLOCKED <date>:
hermes — `RT-A` and backend `BE-B`: why`` (the first row is always the reason's; row
FH-QUEUE-BLOCKED-LIST-NAMES-ROWS-IN-OTHER-BRAINS, the twin of the launcher's
QA-A-ROW-BLOCKED-ON-TWO-REPOS-CAN-ONLY-NAME-ONE, ``EterniaLauncher/tool/queue/queue_wake.dart`` ``blockersOf`` at
5cfeff2093). Each row is resolved in its own brain (:func:`blockers_of`): a hermes close steps every row of this
brain that lists it as a hermes row, whatever the reason, and a row in another brain counts as still open — this
brain cannot see that close, so a row it holds is never woken here, only re-pointed.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from agent_runtime.work_store.grammar import SEPARATOR, STATUS, OutcomeKind, Status, parse_note, split_segments

__layer__ = "policy"

#: This brain's word, as a listed row's brain.
OWN_BRAIN = "hermes"
#: The brain a lane reason's first row lives in.
REASON_BRAINS = {"hermes": OWN_BRAIN, "another lane": OWN_BRAIN, "launcher": "launcher", "backend": "backend"}
_BLOCKER_ID = re.compile(r"^`([A-Z0-9][A-Z0-9._-]*)`")
#: One more row of a block's opening list: a joiner (``,`` / ``then`` / ``and`` / ``&`` / ``+``), the brain the row
#: lives in when it is not the reason's (``launcher`` / ``hermes`` / ``backend``), and a backticked ID.
_NEXT_BLOCKER = re.compile(r"^(?:\s*,\s*(?:(?:and|then)\s+)?|\s+(?:then|and|&|\+)\s+)"
                           r"(?:(launcher|hermes|backend)\s+)?`([A-Z0-9][A-Z0-9._-]*)`")


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


def _opening_list(status_body: str) -> tuple[str, list[str], list[str | None], str] | None:
    """``(head, IDs, brain words, tail)``: :func:`blocker_list` with the brain word each entry carries (None when
    it carries none; always None for the first)."""

    named = blocked_on(status_body)
    if named is None:
        return None
    start = status_body.index(" — ", len(named[0])) + 3
    start += len(status_body[start:]) - len(status_body[start:].lstrip())
    ids, words, at = [named[1]], [None], start + len(named[1]) + 2
    while (more := _NEXT_BLOCKER.match(status_body[at:])) is not None:
        words.append(more.group(1))
        ids.append(more.group(2))
        at += more.end()
    return status_body[:start], ids, words, status_body[at:]


def blocker_list(status_body: str) -> tuple[str, list[str], str] | None:
    """``(head, IDs, tail)`` of a BLOCKED status body whose detail opens with one row or a list of rows: ``head``
    runs through the dash, ``tail`` is what follows the last listed ID (``head + "`A` then backend `B`" + tail`` is
    the body). A backticked name later in the prose is not a blocker. None when the body names no row first."""

    listed = _opening_list(status_body)
    return None if listed is None else (listed[0], listed[1], listed[3])


def blockers_of(status_body: str) -> list[tuple[str, str]]:
    """Every row a BLOCKED status body waits on, each with the brain it lives in (``hermes`` / ``launcher`` /
    ``backend``): the reason's brain unless the entry names its own (`` `A` and backend `B` ``). Empty when the
    body names no row first or its reason is not a lane's."""

    listed = _opening_list(status_body)
    if listed is None or (reason_brain := REASON_BRAINS.get(blocked_on(status_body)[0])) is None:
        return []
    # MUTATION: `reason_brain` for every entry (the word ignored) and test_a_list_names_each_row_in_its_own_brain reds.
    return [(row_id, word or reason_brain) for row_id, word in zip(listed[1], listed[2])]


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
        entries = blockers_of(row.status_body)
        if (closed_id, OWN_BRAIN) not in entries:
            continue
        reason = blocked_on(row.status_body)[0]
        head, _, _, tail = _opening_list(row.status_body)
        brain_of: dict[str, str] = {}
        for blocker, brain in entries:
            brain_of.setdefault(blocker, brain)
        # MUTATION: `still_open = []` and test_a_close_keeps_a_row_other_rows_still_hold_blocked reddens.
        # A row in another brain stays open: its close is that brain's to see (and the grammar check's to name).
        still_open = [blocker for blocker in brain_of
                      if blocker != closed_id and (brain_of[blocker] != OWN_BRAIN or blocker in live_ids)]
        if still_open:
            # The new first row takes the reason: when it lives in another brain, the reason word becomes its brain.
            first_brain = brain_of[still_open[0]]
            if first_brain != REASON_BRAINS[reason]:
                head = first_brain + head[len(reason):]
            rest = ", ".join(f"`{blocker}`" if brain_of[blocker] == first_brain else f"{brain_of[blocker]} `{blocker}`"
                             for blocker in still_open[1:])
            status = [f"BLOCKED {row.status_date}: {head}`{still_open[0]}`{' then ' + rest if rest else ''}{tail}"]
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
