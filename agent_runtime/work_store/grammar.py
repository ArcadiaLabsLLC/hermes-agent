"""The work-queue row grammar — the Python twin of the launcher's ``WorkQueueRowParser``.

Grammar home: ``Harness_Brain/30 — Decisions/0011 — One brain per repo, one Mission Control queue
in the launcher.md`` § Row grammar (with its 2026-10-18 Work W1, 2026-10-19 p10-work S1 ``skills:``
and 2026-11-02 ``group:`` amendments). The regexes are the
vault lint's (``tests/tooling/test_work_queue_row_grammar.py``) and the two are proven to agree on
the shared fixtures (``tests/fixtures/work_queue/``) by
``tests/agent_runtime/work_store/test_grammar.py::test_the_twin_agrees_with_the_lint_on_every_fixture_row``.

A row is ONE physical line, ``- **`<ID>` — <title>** · <segment> · …``; segments split on `` · ``
outside code spans. :func:`apply` is the pure one-line edit every write-back is (plan
``work-on-markdown-2026-10-18.md`` §5): a row is found by ID and edited alone, never text-merged.

Closed rows are ARCHIVED, not deleted (RT-QUEUE-ARCHIVE-GRAMMAR; launcher plan
``EterniaLauncher/docs/mission_control/planned/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md`` D1–D3): a
``type: queue-archive`` note (:func:`is_queue_archive`) under ``<brain>/80 — Archive/Queues/<queue stem>-<YYYY-MM>.md``
holds rows whose status was replaced by ONE outcome segment — ``DONE <date> <commit>``,
``REFUTED <date> <commit>`` (``<commit>`` 7–40 lowercase hex, or ``here``) or ``CLOSED <date>: owner — <words>``
— with optional ``result: <line>`` (≤ 300) and ``review: <words>`` records after it. ``Op.CLOSE`` renders
the archived line (:func:`_close_line`); :func:`archive_note_for` names its month file.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from .models import PERSONA_PREFIX, Domain
from .reasons import Reason, WorkRefused

__layer__ = "policy"
__all__ = [
    "ARCHIVE_DIR",
    "Assignee",
    "Claim",
    "Op",
    "Outcome",
    "OutcomeKind",
    "Row",
    "RowRef",
    "Status",
    "apply",
    "archive_note_for",
    "archive_note_text",
    "domain_of",
    "find",
    "is_queue",
    "is_queue_archive",
    "mint_id",
    "parse_note",
    "parse_outcome",
    "parse_row",
    "render_status",
    "requires_hosts",
    "row_defects",
    "segment_text",
    "split_segments",
]

ROW = re.compile(r"^\s*- (?:\[[ xX]\] )?\*\*")
ROW_ID = re.compile(r"^- \*\*`([^`]*)` — ")
ID_SHAPE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
STATUS = re.compile(r"^(READY|BLOCKED|DEFERRED|NEEDS PLAN) (\d{4}-\d{2}-\d{2})(?::\s*(.*))?$", re.DOTALL)
RULED = re.compile(r"^RULED \d{4}-\d{2}-\d{2}\b")
RETIRED = re.compile(r"^(VERDICT|DESIGN|OWNER|PLAN|VERIFY)\b")
ASSIGNEE = re.compile(r"^assignee: persona:([A-Za-z0-9_.-]+)$")
SKILLS = re.compile(r"^skills: `[A-Za-z0-9_./-]+`(?:, `[A-Za-z0-9_./-]+`)*$")
SKILL_SLUG = re.compile(r"^[A-Za-z0-9_./-]+$")
#: ``group: <slug>`` — the feature a row belongs to (launcher plan QUEUE_ROW_GROUPS_2026-11-01 D1): one bare
#: lowercase slug, so it is never an ID and never a pointer.
GROUP = re.compile(r"^group: ([a-z0-9][a-z0-9.-]*)$")
GROUP_SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
WORK_ID = re.compile(r"^WORK-[A-Z2-7]{6}$")
TAKEN = re.compile(r"\*\*TAKEN (\d{4}-\d{2}-\d{2}) ([^*]+?)\*\*")
#: A lane claim's ``<who>``: ``<lane>[ on <machine>][ as <git account>][ in <worktree>]``.
CLAIM_WHO = re.compile(r"^(.+?)(?: on (\S+))?(?: as (\S+))?(?: in (\S+))?$")
#: The first claim date that must name its machine (launcher ADR 0025's 2026-10-26 amendment).
PLACE_REQUIRED_FROM = "2026-10-27"
#: ``REQUIRES <host>[, <host>…]`` — the OS a row must be worked on; a record, never a status.
REQUIRES = re.compile(r"^REQUIRES(?:\s+(.*))?$", re.DOTALL)
HOSTS = ("windows", "macos", "linux")
RECOMMEND = re.compile(r"^Recommend:\s*(.*)$", re.DOTALL)
TITLE = re.compile(r"^\s*- (?:\[[ xX]\] )?\*\*`[^`]*` — (.*?)\*\*")
CODE_SPAN = re.compile(r"`([^`]+)`")
#: A claim and the separator that set it off, as :func:`apply` removes it.
_CLAIM_SEGMENT = re.compile(r"(?: · | )?\*\*TAKEN \d{4}-\d{2}-\d{2} [^*]+?\*\*")
_WHO = re.compile(r"^[^*\s][^*]*$")
_SEGMENT_FORBIDDEN = re.compile(r"[`*·]")

#: A segment opening an outcome word and a date — the outcome FAMILY, well-formed or not.
OUTCOME_OPEN = re.compile(r"^(?:DONE|REFUTED|CLOSED) \d{4}-\d{2}-\d{2}\b")
OUTCOME = re.compile(r"^(DONE|REFUTED) (\d{4}-\d{2}-\d{2}) ([0-9a-f]{7,40}|here)$")
CLOSED_OUTCOME = re.compile(r"^CLOSED (\d{4}-\d{2}-\d{2}):\s*owner — (.+)$", re.DOTALL)
#: The longest ``result:`` record an archived row carries.
RESULT_LIMIT = 300
#: Where a brain's closed rows live, beside its queue directory (plan D1).
ARCHIVE_DIR = "80 — Archive/Queues"
BLOCKED_REASONS = ("owner decision", "owner sitting", "backend", "hermes", "launcher", "upstream", "another lane")
OWNER_DECISION = BLOCKED_REASONS[0]
SEPARATOR = " · "


class Status(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    NEEDS_PLAN = "NEEDS PLAN"


class OutcomeKind(StrEnum):
    DONE = "DONE"
    REFUTED = "REFUTED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class Outcome:
    """An archived row's one outcome: ``DONE`` / ``REFUTED`` with a commit (or ``here``), ``CLOSED`` with words."""

    kind: OutcomeKind
    date: str
    commit: str | None = None
    words: str | None = None

    def render(self) -> str:
        if self.kind is OutcomeKind.CLOSED:
            return f"CLOSED {self.date}: owner — {self.words}"
        return f"{self.kind.value} {self.date} {self.commit}"


def parse_outcome(segment: str) -> Outcome | None:
    """``segment`` as an outcome, or None when it is not one or is malformed (a bad sha, no ``owner —``)."""

    closed = CLOSED_OUTCOME.match(segment)
    if closed is not None:
        return Outcome(OutcomeKind.CLOSED, closed.group(1), words=closed.group(2).strip())
    match = OUTCOME.match(segment)
    return Outcome(OutcomeKind(match.group(1)), match.group(2), commit=match.group(3)) if match else None


class Op(StrEnum):
    APPEND = "append"
    CLAIM = "claim"
    RELEASE = "release"
    SET_STATUS = "set_status"
    EDIT = "edit"
    DELETE = "delete"
    ASSIGN = "assign"
    SET_SKILLS = "set_skills"
    SET_GROUP = "set_group"
    #: The close: the row moves to its archive month file with ONE outcome segment (RT-QUEUE-ARCHIVE-GRAMMAR).
    CLOSE = "close"
    #: Not a row edit: a Project's machine-written chat logs (plan project-slots-and-shared-chats §5) —
    #: appended lines, whole files and removed folders under the writer's root, one commit.
    CHAT_TURNS_APPENDED = "chat_turns_appended"


@dataclass(frozen=True)
class RowRef:
    """A task's key on a board: the slot, the note (repo-relative, posix), the row ID and the slot's owner.

    ``project_id`` is the Project that declares the slot (RT-WORK-BOARD-PER-PROJECT-SLOT): None for the
    workspace's own slot, and for a ref saved before boards were keyed by ``(project, slot)`` — such a
    ref resolves through the owner rule (``board.pick``), and two Projects answering it refuse
    ``slot_ambiguous``. Defaulted, so every persisted three-field ref still loads.
    """

    slot: str
    note: str
    id: str
    project_id: str | None = None

    @property
    def key(self) -> str:
        """The board key the ref addresses: ``<project>/<slot>``, or the bare slot (``workspace_slots.slot_key``)."""
        return f"{self.project_id}/{self.slot}" if self.project_id else self.slot

    def items(self) -> list[str]:
        """The persisted list form: ``[slot, note, id]``, plus ``project_id`` when it is set."""
        return [self.slot, self.note, self.id, *([self.project_id] if self.project_id else [])]

    @classmethod
    def of(cls, item: Any) -> RowRef | None:
        """A ref from its list form (three or four strings); None for anything else."""
        if not isinstance(item, (list, tuple)) or len(item) not in (3, 4):
            return None
        return cls(*(str(part) for part in item))


@dataclass(frozen=True)
class Claim:
    date: str
    who: str

    @property
    def persona_instance_id(self) -> str | None:
        return self.who[len(PERSONA_PREFIX):] if self.who.startswith(PERSONA_PREFIX) else None

    @property
    def machine(self) -> str | None:
        """The ``on <machine>`` part of a lane claim, or None when the mark leaves it out."""
        match = CLAIM_WHO.match(self.who)
        return match.group(2) if match else None

    @property
    def missing_place(self) -> bool:
        """A lane claim from :data:`PLACE_REQUIRED_FROM` on with no ``on <machine>`` (persona claims exempt)."""
        return self.persona_instance_id is None and self.machine is None and self.date >= PLACE_REQUIRED_FROM


@dataclass(frozen=True)
class Assignee:
    """``assignee: persona:<token>`` — a persona instance id or a persona id (resolved by W2)."""

    token: str


@dataclass(frozen=True)
class Row:
    ref: RowRef
    title: str
    status: Status | None
    status_date: str | None
    status_body: str
    recommend: str | None
    assignee: Assignee | None
    taken: Claim | None
    rulings: tuple[str, ...]
    pointers: tuple[str, ...]
    segments: tuple[str, ...]
    heading: str
    line_no: int
    raw: str
    defects: tuple[str, ...] = ()
    #: The skills the row lends whoever works it (``skills:`` segment); never a pointer.
    skills: tuple[str, ...] = ()
    #: The hosts the row's ``REQUIRES`` segment names, in order; empty when it runs anywhere.
    requires: tuple[str, ...] = ()
    #: The feature the row belongs to (``group:`` segment); None when it names none.
    group: str | None = None
    #: An archived row's one outcome (None on a live row, or when it has none or several).
    outcome: Outcome | None = None
    #: An archived row's ``result:`` / ``review:`` records.
    result: str | None = None
    review: str | None = None


def domain_of(row: Row) -> Domain:
    """The row's batching key (dispatcher plan §3.1): its slot, note and queue heading."""
    return Domain(row.ref.slot, row.ref.note, row.heading)


def split_segments(line: str) -> list[str]:
    """The `` · ``-separated segments of ``line``, never splitting inside a code span."""
    out: list[str] = []
    current: list[str] = []
    in_code = False
    i = 0
    while i < len(line):
        char = line[i]
        if char == "`":
            in_code = not in_code
        if not in_code and line.startswith(SEPARATOR, i):
            out.append("".join(current))
            current = []
            i += 3
            continue
        current.append(char)
        i += 1
    out.append("".join(current))
    return out


def requires_hosts(segment: str) -> tuple[str, ...] | None:
    """The hosts of a ``REQUIRES`` segment, or None when it names none, an unknown one, or one twice."""
    match = REQUIRES.match(segment)
    if match is None:
        return None
    hosts = [part.strip() for part in (match.group(1) or "").split(",")]
    if any(host not in HOSTS for host in hosts) or len(set(hosts)) != len(hosts):
        return None
    return tuple(hosts)


def blocked_reason(body: str) -> str | None:
    for reason in BLOCKED_REASONS:
        if body == reason or any(body.startswith(reason + c) for c in " :(,"):
            return reason
    return None


# ── defects (the lint's checks, the lint's words) ───────────────────────────


def _lead_defects(line: str) -> list[str]:
    defects: list[str] = []
    if re.match(r"^\s*- \[[ xX]\] ", line):
        defects.append("checkbox prefix (`- [ ] `); a row opens `- **`")
    match = ROW_ID.match(line.lstrip())
    if match is None:
        defects.append("no ID: the bold lead must open with `` `<ID>` — ``")
    elif not ID_SHAPE.match(match.group(1)):
        defects.append(f"ID `{match.group(1)}` is not ^[A-Z0-9][A-Z0-9._-]*$")
    elif match.group(1).startswith("WORK-") and not WORK_ID.match(match.group(1)):
        defects.append(f"ID `{match.group(1)}` opens WORK- but is not WORK-<6> (six base32 characters)")
    lead = line.index("**")
    if line.find("**", lead + 2) == -1:
        defects.append("the bold lead does not close on this line")
    return defects


def _status_defects(segments: list[str]) -> list[str]:
    statuses = [(i, STATUS.match(s)) for i, s in enumerate(segments) if STATUS.match(s)]
    defects: list[str] = []
    if len(statuses) != 1:
        defects.append(f"{len(statuses)} status segments; exactly one of READY / BLOCKED / DEFERRED / NEEDS PLAN <date>")
    for index, status in statuses:
        if Status(status.group(1)) is not Status.BLOCKED:
            continue
        reason = blocked_reason((status.group(3) or "").strip())
        if reason is None:
            defects.append(f"BLOCKED reason not in {BLOCKED_REASONS}: {segments[index][:60]!r}")
        elif reason == OWNER_DECISION and not any(s.startswith("Recommend:") for s in segments[index + 1:]):
            defects.append("owner decision with no `Recommend: …` segment after it")
    return defects


def _segment_defects(segments: list[str]) -> list[str]:
    defects: list[str] = []
    for segment in segments[1:]:
        if RETIRED.match(segment):
            defects.append(f"retired status word opens a segment: {segment[:40]!r}")
        if segment.startswith("RULED") and not RULED.match(segment):
            defects.append(f"undated RULED record: {segment[:40]!r}")
        if segment.startswith("assignee:") and not ASSIGNEE.match(segment):
            defects.append(f"assignee shape: {segment[:40]!r}; the segment is `assignee: persona:<token>`")
        if segment.startswith("skills:") and not SKILLS.match(segment):
            defects.append(f"skills shape: {segment[:40]!r}; the segment is `skills: `<slug>`[, `<slug>`]`")
        if segment.startswith("group:") and not GROUP.match(segment):
            defects.append(f"group shape: {segment[:40]!r}; the segment is `group: <slug>`, slug [a-z0-9][a-z0-9.-]*")
        if REQUIRES.match(segment) and requires_hosts(segment) is None:
            defects.append(f"REQUIRES shape: {segment[:40]!r}; the segment is `REQUIRES <host>[, <host>]`, "
                           f"each host once, from {HOSTS}")
    if sum(1 for s in segments[1:] if ASSIGNEE.match(s)) > 1:
        defects.append("2 assignee segments; at most one")
    if sum(1 for s in segments[1:] if SKILLS.match(s)) > 1:
        defects.append("2 skills segments; at most one")
    if sum(1 for s in segments[1:] if REQUIRES.match(s)) > 1:
        defects.append("2 REQUIRES segments; at most one")
    if sum(1 for s in segments[1:] if s.startswith("group:")) > 1:
        defects.append("2 group segments; at most one")
    return defects


def _claim_defects(line: str) -> list[str]:
    taken = TAKEN.search(line)
    if taken is None or not Claim(taken.group(1), taken.group(2).strip()).missing_place:
        return []
    return [f"claim dated {taken.group(1)} names no machine; a lane claim is "
            "`**TAKEN <date> <lane> on <machine> as <git account> in <worktree>**`"]


def _outcome_defects(segments: list[str], line: str, *, archived: bool) -> list[str]:
    """A live row carries no outcome (``CLOSED ROW LIVE``); an archived row carries exactly one well-formed
    outcome, at most one ``result:`` (≤ 300) and one ``review:``, and no status or claim — the launcher's words."""

    outcomes = [s for s in segments[1:] if OUTCOME_OPEN.match(s)]
    if not archived:
        return ["CLOSED ROW LIVE: an outcome segment on a live row; a closed row moves to the archive"] if outcomes else []
    defects: list[str] = []
    if any(STATUS.match(s) for s in segments[1:]) or TAKEN.search(line):
        defects.append("ARCHIVE ROW OPEN: an archived row carries no live status and no claim")
    results = [s[len("result:"):].strip() for s in segments[1:] if s.startswith("result:")]
    reviews = [s[len("review:"):].strip() for s in segments[1:] if s.startswith("review:")]
    if (len(outcomes) != 1 or parse_outcome(outcomes[0]) is None or len(results) > 1 or len(reviews) > 1
            or any(not r or len(r) > RESULT_LIMIT for r in results) or any(not r for r in reviews)):
        defects.append("BAD OUTCOME: exactly one DONE|REFUTED <date> <sha|here> or CLOSED <date>: owner — <words>, "
                       f"at most one result: (≤ {RESULT_LIMIT}) and one review:")
    return defects


def row_defects(line: str, *, archived: bool = False) -> list[str]:
    """Every grammar defect of one row line (empty when the row is canonical) — the lint's verdict.

    ``archived``: the line is from a ``type: queue-archive`` note, so an outcome replaces the status.
    """

    segments = [s.strip() for s in split_segments(line)]
    status = [] if archived else _status_defects(segments)
    return (_lead_defects(line) + status + _segment_defects(segments) + _outcome_defects(segments, line, archived=archived)
            + _claim_defects(line))


# ── parse ────────────────────────────────────────────────────────────────────


def parse_row(line: str, *, slot: str, note: str, line_no: int, heading: str = "",
              project_id: str | None = None, archived: bool = False) -> Row | None:
    """The row on ``line``, or None when the line is not a row. A defective row still parses."""

    if not ROW.match(line):
        return None
    segments = tuple(s.strip() for s in split_segments(line))
    id_match = re.search(r"\*\*`([^`]*)` — ", line)
    title = TITLE.match(line)
    statuses = [m for m in map(STATUS.match, segments[1:]) if m]
    status = statuses[0] if statuses else None
    recommend = next((m.group(1).strip() for m in map(RECOMMEND.match, segments[1:]) if m), None)
    assignee = next((Assignee(m.group(1)) for m in map(ASSIGNEE.match, segments[1:]) if m), None)
    lent = next((s for s in segments[1:] if SKILLS.match(s)), None)
    hosts = next((h for h in map(requires_hosts, segments[1:]) if h is not None), ())
    group = next((m.group(1) for m in map(GROUP.match, segments[1:]) if m), None)
    taken = TAKEN.search(line)
    outcomes = [o for o in map(parse_outcome, (s for s in segments[1:] if OUTCOME_OPEN.match(s)))]
    result = next((s[len("result:"):].strip() for s in segments[1:] if s.startswith("result:")), None)
    review = next((s[len("review:"):].strip() for s in segments[1:] if s.startswith("review:")), None)
    return Row(
        ref=RowRef(slot, note, id_match.group(1) if id_match else "", project_id),
        title=title.group(1).strip() if title else "",
        status=Status(status.group(1)) if status else None,
        status_date=status.group(2) if status else None,
        status_body=(status.group(3) or "").strip() if status else "",
        recommend=recommend,
        assignee=assignee,
        taken=Claim(taken.group(1), taken.group(2).strip()) if taken else None,
        rulings=tuple(s for s in segments[1:] if s.startswith("RULED")),
        pointers=tuple(span for s in segments[1:] if not s.startswith("skills:") for span in CODE_SPAN.findall(s)),
        segments=segments,
        heading=heading,
        line_no=line_no,
        raw=line,
        defects=tuple(row_defects(line, archived=archived)),
        skills=tuple(CODE_SPAN.findall(lent)) if lent else (),
        requires=hosts,
        group=group,
        outcome=outcomes[0] if len(outcomes) == 1 else None,
        result=result[:RESULT_LIMIT] if result is not None else None,
        review=review,
    )


def _continues(following: str) -> bool:
    return bool(following.strip()) and following[:1].isspace() and not following.lstrip().startswith(("- ", "#"))


def _body_lines(lines: list[str]) -> Iterable[tuple[int, str]]:
    """(index, line) of every line outside the frontmatter and outside code fences."""

    in_frontmatter = bool(lines) and lines[0].rstrip() == "---"
    in_fence = False
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r")
        if in_frontmatter:
            in_frontmatter = not (i > 0 and line.rstrip() == "---")
            continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield i, line


def parse_note(text: str, *, slot: str, note: str, project_id: str | None = None,
               archived: bool | None = None) -> list[Row]:
    """Every row of one queue note, each with the ``##``/``###`` heading it sits under (refs owned by ``project_id``).

    ``archived`` (default: read off the note's frontmatter) parses the rows under the archive grammar.
    """

    if archived is None:
        archived = is_queue_archive(text)
    lines = text.split("\n")
    rows: list[Row] = []
    heading = ""
    for i, line in _body_lines(lines):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        row = parse_row(line, slot=slot, note=note, line_no=i + 1, heading=heading, project_id=project_id,
                        archived=archived)
        if row is None:
            continue
        following = lines[i + 1].rstrip("\r") if i + 1 < len(lines) else ""
        if _continues(following):
            row = _with_defect(row, "the row continues on the next line; a row is one physical line")
        rows.append(row)
    return rows


def _with_defect(row: Row, defect: str) -> Row:
    return replace(row, defects=(*row.defects, defect))


def _note_type(text: str) -> str | None:
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line.rstrip() == "---":
            return None
        if line.startswith("type:"):
            return line[5:].strip()
    return None


def is_queue(text: str) -> bool:
    return _note_type(text) == "queue"


def is_queue_archive(text: str) -> bool:
    """``type: queue-archive`` — one queue's closed rows for one month (plan D2)."""
    return _note_type(text) == "queue-archive"


def archive_note_for(note: str, date: str) -> str:
    """The month file a row of queue ``note`` (repo-relative, posix) closed on ``date`` is archived in:
    ``<parent of the queue dir>/80 — Archive/Queues/<note stem>-<YYYY-MM>.md`` (plan D1)."""

    parts = note.split("/")
    stem = parts[-1].removesuffix(".md")
    return "/".join([*parts[:-2], ARCHIVE_DIR, f"{stem}-{date[:7]}.md"])


def archive_note_text(queue: str, program: str | None, month: str) -> str:
    """A new month file's head: D2's frontmatter and banner (rows are appended after it)."""

    return (f"---\ntype: queue-archive\nqueue: {queue}\nprogram: {program or 'work'}\nmonth: {month}\n---\n\n"
            f"Closed rows of `{queue}` for {month}; appended by the close commits, never edited.\n\n")


def find(rows: Iterable[Row], row_id: str) -> Row | None:
    return next((row for row in rows if row.ref.id == row_id), None)


# ── write: the one-line edit ─────────────────────────────────────────────────


def render_status(status: Status, date: str, body: str = "") -> str:
    return f"{status.value} {date}" + (f": {body}" if body else "")


def segment_text(value: str, limit: int = 300) -> str:
    """One grammar-safe segment text: no code span, bold or separator can leak into the row."""

    return " ".join(_SEGMENT_FORBIDDEN.sub("-", str(value or "")).split())[:limit]


def mint_id(rand: bytes | None = None) -> str:
    """``WORK-`` + six base32 characters; a collision is the writer's ``id_exists``, never a retry here."""

    return "WORK-" + base64.b32encode(rand or os.urandom(5)).decode()[:6]


def _claim_line(line: str, *, who: str, date: str, payload: dict) -> str:
    held = TAKEN.search(line)
    if held:
        raise WorkRefused(Reason.ALREADY_TAKEN, held.group(2))
    return f"{line.rstrip()}{SEPARATOR}**TAKEN {date} {who}**"


def _release(line: str, *, who: str, date: str, payload: dict) -> str:
    return _CLAIM_SEGMENT.sub("", line, count=1).rstrip()


def _set_status(line: str, *, who: str, date: str, payload: dict) -> str:
    wanted = [s.strip() for s in split_segments(str(payload.get("status") or ""))]
    new = STATUS.match(wanted[0])
    if new is None:
        raise WorkRefused(Reason.INVALID, "payload.status is not a READY / BLOCKED / DEFERRED / NEEDS PLAN <date> segment")
    claim = TAKEN.search(line)
    segments = split_segments(_release(line, who=who, date=date, payload={}))
    at = next((i for i, s in enumerate(segments) if i and STATUS.match(s.strip())), None)
    if at is None:
        raise WorkRefused(Reason.GRAMMAR_INVALID, "the row has no status segment to replace")
    asks = Status(new.group(1)) is Status.BLOCKED and blocked_reason((new.group(3) or "").strip()) == OWNER_DECISION
    keep_recommend = asks and len(wanted) == 1
    edited: list[str] = []
    for i, segment in enumerate(segments):
        if i == at:
            edited.extend(wanted)
        elif keep_recommend or not RECOMMEND.match(segment.strip()):
            edited.append(segment)
    return SEPARATOR.join(edited).rstrip() + (f"{SEPARATOR}{claim.group(0)}" if claim else "")


def _delete(line: str, *, who: str, date: str, payload: dict) -> None:
    return None


def _edit_task(line: str, *, who: str, date: str, payload: dict) -> str:
    """Change title and brief pointer, preserving identity, status and all other metadata."""
    match = TITLE.match(line)
    if match is None:
        raise WorkRefused(Reason.GRAMMAR_INVALID, "the row has no title")
    title = str(payload["title"])
    edited = line[:match.start(1)] + title + line[match.end(1):]
    segments = [part for part in split_segments(edited) if not part.strip().startswith("brief:")]
    segments.insert(1, f"brief: `{payload['brief']}`")
    return SEPARATOR.join(segments)


def _assign(line: str, *, who: str, date: str, payload: dict) -> str:
    """Drop any ``assignee:`` segment; with ``payload["assignee"]`` (a token), set one before the status."""

    token = payload.get("assignee")
    if token is not None and not ASSIGNEE.match(f"assignee: persona:{token}"):
        raise WorkRefused(Reason.INVALID, "payload.assignee is a persona token [A-Za-z0-9_.-]+")
    segments = [s for s in split_segments(line) if not s.strip().startswith("assignee:")]
    if token is not None:
        at = next((i for i, s in enumerate(segments) if i and STATUS.match(s.strip())), len(segments))
        segments.insert(at, f"assignee: persona:{token}")
    return SEPARATOR.join(segments).rstrip()


def _set_skills(line: str, *, who: str, date: str, payload: dict) -> str:
    """Drop any ``skills:`` segment; with a non-empty ``payload["skills"]``, set one after ``assignee:``
    (else right after the title)."""

    skills = list(dict.fromkeys(str(s) for s in payload.get("skills") or ()))
    if any(not SKILL_SLUG.match(skill) for skill in skills):
        raise WorkRefused(Reason.INVALID, "payload.skills are slugs [A-Za-z0-9_./-]+")
    segments = [s for s in split_segments(line) if not s.strip().startswith("skills:")]
    if skills:
        at = next((i + 1 for i, s in enumerate(segments) if i and ASSIGNEE.match(s.strip())), 1)
        segments.insert(at, "skills: " + ", ".join(f"`{skill}`" for skill in skills))
    return SEPARATOR.join(segments).rstrip()


def _set_group(line: str, *, who: str, date: str, payload: dict) -> str:
    """Drop any ``group:`` segment; with ``payload["group"]`` (a slug), set one first after the bold lead."""

    group = payload.get("group")
    if group is not None and not GROUP_SLUG.match(str(group)):
        raise WorkRefused(Reason.INVALID, "payload.group is a slug [a-z0-9][a-z0-9.-]*")
    segments = [s for i, s in enumerate(split_segments(line)) if not (i and s.strip().startswith("group:"))]
    if group is not None:
        segments.insert(1, f"group: {group}")
    return SEPARATOR.join(segments).rstrip()


def _append(line: str, *, who: str, date: str, payload: dict) -> str:
    raise WorkRefused(Reason.INVALID, "APPEND is not a line edit; the caller appends payload.row under the note's last heading")


def _close_line(line: str, *, who: str, date: str, payload: dict) -> str:
    """The archived line: the claim mark removed, the status (and any ``Recommend:`` after it) replaced in place
    by ONE outcome segment, an optional ``result:`` record appended (plan D3).

    ``payload``: ``outcome`` (``DONE`` / ``REFUTED`` / ``CLOSED``), ``commit`` (7–40 hex or ``here``; DONE /
    REFUTED), ``words`` (CLOSED: the owner's words), ``result`` (one line, ≤ 300 after :func:`segment_text`),
    ``date`` (the close date; default today).
    """

    kind = str(payload.get("outcome") or "")
    if kind not in OutcomeKind.__members__:
        raise WorkRefused(Reason.INVALID, "payload.outcome is DONE | REFUTED | CLOSED")
    when = str(payload.get("date") or date)
    outcome = (Outcome(OutcomeKind.CLOSED, when, words=str(payload.get("words") or "").strip())
               if kind == OutcomeKind.CLOSED.name else Outcome(OutcomeKind(kind), when, commit=str(payload.get("commit") or "")))
    if parse_outcome(outcome.render()) != outcome:
        raise WorkRefused(Reason.INVALID, f"not an outcome: {outcome.render()!r}")
    segments = split_segments(_release(line, who=who, date=date, payload={}))
    at = next((i for i, s in enumerate(segments) if i and STATUS.match(s.strip())), None)
    if at is None:
        raise WorkRefused(Reason.GRAMMAR_INVALID, "the row has no status segment to replace")
    kept = [outcome.render() if i == at else s for i, s in enumerate(segments)
            if i == at or not (i > at and RECOMMEND.match(s.strip()))]
    result = segment_text(str(payload.get("result") or ""), limit=RESULT_LIMIT)
    return SEPARATOR.join(kept).rstrip() + (f"{SEPARATOR}result: {result}" if result else "")


def _not_a_line_edit(line: str, *, who: str, date: str, payload: dict) -> str:
    raise WorkRefused(Reason.INVALID, "chat_turns_appended edits no row; the writer appends the chat logs")


_EDITS: dict[Op, Callable[..., str | None]] = {
    Op.CLAIM: _claim_line,
    Op.RELEASE: _release,
    Op.SET_STATUS: _set_status,
    Op.EDIT: _edit_task,
    Op.DELETE: _delete,
    Op.APPEND: _append,
    Op.ASSIGN: _assign,
    Op.SET_SKILLS: _set_skills,
    Op.SET_GROUP: _set_group,
    Op.CLOSE: _close_line,
    Op.CHAT_TURNS_APPENDED: _not_a_line_edit,
}


def apply(line: str, op: Op, *, who: str, date: str, payload: dict) -> str | None:
    """The row line after ``op`` (None for DELETE: the caller drops the line).

    A row that was canonical stays canonical: an edit that would leave a grammar defect is
    refused ``grammar_invalid`` instead of written.
    """

    if not _WHO.match(who):
        raise WorkRefused(Reason.INVALID, "who is a non-empty token with no `*`")
    edited = _EDITS[Op(op)](line, who=who, date=date, payload=payload)
    archived = Op(op) is Op.CLOSE
    if edited is not None and not row_defects(line) and row_defects(edited, archived=archived):
        raise WorkRefused(Reason.GRAMMAR_INVALID, "; ".join(row_defects(edited, archived=archived)))
    return edited
