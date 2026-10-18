"""The work-queue row grammar — the Python twin of the launcher's ``WorkQueueRowParser``.

Grammar home: ``Harness_Brain/30 — Decisions/0011 — One brain per repo, one Mission Control queue
in the launcher.md`` § Row grammar (with its 2026-10-18 Work W1 amendment). The regexes are the
vault lint's (``tests/tooling/test_work_queue_row_grammar.py``) and the two are proven to agree on
the shared fixtures (``tests/fixtures/work_queue/``) by
``tests/agent_runtime/work_store/test_grammar.py::test_the_twin_agrees_with_the_lint_on_every_fixture_row``.

A row is ONE physical line, ``- **`<ID>` — <title>** · <segment> · …``; segments split on `` · ``
outside code spans. :func:`apply` is the pure one-line edit every write-back is (plan
``work-on-markdown-2026-10-18.md`` §5): a row is found by ID and edited alone, never text-merged.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from .reasons import Reason, WorkRefused

__layer__ = "policy"
__all__ = [
    "Assignee",
    "Claim",
    "Op",
    "Row",
    "RowRef",
    "Status",
    "apply",
    "find",
    "is_queue",
    "mint_id",
    "parse_note",
    "parse_row",
    "render_status",
    "row_defects",
    "split_segments",
]

ROW = re.compile(r"^\s*- (?:\[[ xX]\] )?\*\*")
ROW_ID = re.compile(r"^- \*\*`([^`]*)` — ")
ID_SHAPE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
STATUS = re.compile(r"^(READY|BLOCKED|DEFERRED|NEEDS PLAN) (\d{4}-\d{2}-\d{2})(?::\s*(.*))?$", re.DOTALL)
RULED = re.compile(r"^RULED \d{4}-\d{2}-\d{2}\b")
RETIRED = re.compile(r"^(VERDICT|DESIGN|OWNER|PLAN|VERIFY)\b")
ASSIGNEE = re.compile(r"^assignee: persona:([A-Za-z0-9_.-]+)$")
WORK_ID = re.compile(r"^WORK-[A-Z2-7]{6}$")
TAKEN = re.compile(r"\*\*TAKEN (\d{4}-\d{2}-\d{2}) ([^*]+?)\*\*")
RECOMMEND = re.compile(r"^Recommend:\s*(.*)$", re.DOTALL)
TITLE = re.compile(r"^\s*- (?:\[[ xX]\] )?\*\*`[^`]*` — (.*?)\*\*")
CODE_SPAN = re.compile(r"`([^`]+)`")
#: A claim and the separator that set it off, as :func:`apply` removes it.
_CLAIM_SEGMENT = re.compile(r"(?: · | )?\*\*TAKEN \d{4}-\d{2}-\d{2} [^*]+?\*\*")
_WHO = re.compile(r"^[^*\s][^*]*$")

BLOCKED_REASONS = ("owner decision", "owner sitting", "backend", "hermes", "launcher", "upstream", "another lane")
OWNER_DECISION = BLOCKED_REASONS[0]
PERSONA_PREFIX = "persona:"
SEPARATOR = " · "


class Status(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    NEEDS_PLAN = "NEEDS PLAN"


class Op(StrEnum):
    APPEND = "append"
    CLAIM = "claim"
    RELEASE = "release"
    SET_STATUS = "set_status"
    DELETE = "delete"


@dataclass(frozen=True)
class RowRef:
    """A task's key on a board: the slot, the note (repo-relative, posix) and the row ID."""

    slot: str
    note: str
    id: str


@dataclass(frozen=True)
class Claim:
    date: str
    who: str

    @property
    def persona_instance_id(self) -> str | None:
        return self.who[len(PERSONA_PREFIX):] if self.who.startswith(PERSONA_PREFIX) else None


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
    if sum(1 for s in segments[1:] if ASSIGNEE.match(s)) > 1:
        defects.append("2 assignee segments; at most one")
    return defects


def row_defects(line: str) -> list[str]:
    """Every grammar defect of one row line (empty when the row is canonical) — the lint's verdict."""

    segments = [s.strip() for s in split_segments(line)]
    return _lead_defects(line) + _status_defects(segments) + _segment_defects(segments)


# ── parse ────────────────────────────────────────────────────────────────────


def parse_row(line: str, *, slot: str, note: str, line_no: int, heading: str = "") -> Row | None:
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
    taken = TAKEN.search(line)
    return Row(
        ref=RowRef(slot, note, id_match.group(1) if id_match else ""),
        title=title.group(1).strip() if title else "",
        status=Status(status.group(1)) if status else None,
        status_date=status.group(2) if status else None,
        status_body=(status.group(3) or "").strip() if status else "",
        recommend=recommend,
        assignee=assignee,
        taken=Claim(taken.group(1), taken.group(2).strip()) if taken else None,
        rulings=tuple(s for s in segments[1:] if s.startswith("RULED")),
        pointers=tuple(span for s in segments[1:] for span in CODE_SPAN.findall(s)),
        segments=segments,
        heading=heading,
        line_no=line_no,
        raw=line,
        defects=tuple(row_defects(line)),
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


def parse_note(text: str, *, slot: str, note: str) -> list[Row]:
    """Every row of one queue note, each with the ``##``/``###`` heading it sits under."""

    lines = text.split("\n")
    rows: list[Row] = []
    heading = ""
    for i, line in _body_lines(lines):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        row = parse_row(line, slot=slot, note=note, line_no=i + 1, heading=heading)
        if row is None:
            continue
        following = lines[i + 1].rstrip("\r") if i + 1 < len(lines) else ""
        if _continues(following):
            row = _with_defect(row, "the row continues on the next line; a row is one physical line")
        rows.append(row)
    return rows


def _with_defect(row: Row, defect: str) -> Row:
    return replace(row, defects=(*row.defects, defect))


def is_queue(text: str) -> bool:
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return False
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line.rstrip() == "---":
            return False
        if line.startswith("type:") and line[5:].strip() == "queue":
            return True
    return False


def find(rows: Iterable[Row], row_id: str) -> Row | None:
    return next((row for row in rows if row.ref.id == row_id), None)


# ── write: the one-line edit ─────────────────────────────────────────────────


def render_status(status: Status, date: str, body: str = "") -> str:
    return f"{status.value} {date}" + (f": {body}" if body else "")


def mint_id(rand: bytes | None = None) -> str:
    """``WORK-`` + six base32 characters; a collision is the writer's ``id_exists``, never a retry here."""

    return "WORK-" + base64.b32encode(rand or os.urandom(5)).decode()[:6]


def _claim(line: str, *, who: str, date: str, payload: dict) -> str:
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


def _append(line: str, *, who: str, date: str, payload: dict) -> str:
    raise WorkRefused(Reason.INVALID, "APPEND is not a line edit; the caller appends payload.row under the note's last heading")


_EDITS: dict[Op, Callable[..., str | None]] = {
    Op.CLAIM: _claim,
    Op.RELEASE: _release,
    Op.SET_STATUS: _set_status,
    Op.DELETE: _delete,
    Op.APPEND: _append,
}


def apply(line: str, op: Op, *, who: str, date: str, payload: dict) -> str | None:
    """The row line after ``op`` (None for DELETE: the caller drops the line).

    A row that was canonical stays canonical: an edit that would leave a grammar defect is
    refused ``grammar_invalid`` instead of written.
    """

    if not _WHO.match(who):
        raise WorkRefused(Reason.INVALID, "who is a non-empty token with no `*`")
    edited = _EDITS[Op(op)](line, who=who, date=date, payload=payload)
    if edited is not None and not row_defects(line) and row_defects(edited):
        raise WorkRefused(Reason.GRAMMAR_INVALID, "; ".join(row_defects(edited)))
    return edited
