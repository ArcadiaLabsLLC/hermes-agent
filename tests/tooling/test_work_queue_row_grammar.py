"""Every work-queue row in this vault is one the Mission Control board can read.

The launcher's Mission Control Queues tab reads each repo's ``type: queue`` notes
straight from the git checkout, so a row is either in the canonical grammar or it
is invisible (or mis-filed) on the owner's board. The grammar has one home in this
repo — ``Harness_Brain/30 — Decisions/0011 — One brain per repo, one Mission Control queue in the launcher.md`` § Row grammar
— and is the launcher's parser
(``EterniaLauncher/lib/features/mission_control/work_queue/policy/work_queue_row_parser.dart``);
the regexes below are that parser's, restated because the two repos share no code.

A row is ``- **`<ID>` — <title>** · <segment> · …``, on ONE physical line, with:

* an ID (``^[A-Z0-9][A-Z0-9._-]*$``) unique across every queue note in the vault;
* EXACTLY one status segment — ``READY <date>``, ``BLOCKED <date>: <reason> — …``,
  ``DEFERRED <date>: …`` or ``NEEDS PLAN <date>: …``;
* a BLOCKED reason from the closed set below, and a ``Recommend: …`` segment after an
  ``owner decision``;
* for the lane reasons (``backend``, ``hermes``, ``launcher``, ``another lane``) the text after `` — ``
  opens with the blocking row's ID in backticks; a same-repo ``another lane`` ID must be a
  row in this vault, and a cross-repo one names the repo (``launcher`` / ``backend``) right
  after it. Rows still missing a blocker ID are a RATCHET (``BLOCKER_ID_CEILING``) that may
  only fall;
* no retired status word (``VERDICT``, ``DESIGN``, ``OWNER``, ``PLAN``, ``VERIFY``)
  opening a segment, and every ``RULED`` record dated;
* at most one ``assignee: persona:<token>`` segment (token ``[A-Za-z0-9_.-]+``), and no
  ``assignee:`` segment in any other shape (amendment 2026-10-18, Work W1);
* at most one ``skills: `<slug>`[, `<slug>`]`` segment (slug ``[A-Za-z0-9_./-]+``), and no ``skills:``
  segment in any other shape (amendment 2026-10-19, p10-work S1);
* an ID opening ``WORK-`` is an engine-minted ``WORK-<6>``: six base32 characters ``[A-Z2-7]``;
* at most one ``group: <slug>`` segment (slug ``[a-z0-9][a-z0-9.-]*``, bare: lowercase so it is never an ID,
  no code span so no pointer read sees it), and no ``group:`` segment in any other shape (amendment
  2026-11-02, twin of launcher ADR 0025's 2026-11-01 amendment); a row citing a ``planned/`` doc names its
  group — the rows that predate the rule are a RATCHET (``GROUP_MISSING_CEILING``) that may only fall;
* at most one ``REQUIRES <host>[, <host>…]`` segment (host ``windows`` | ``macos`` | ``linux``, each once) —
  a record like RULED, never a status (launcher ADR 0025's 2026-10-26 amendment);
* a lane claim dated 2026-10-27 or later names its machine:
  ``**TAKEN <date> <lane> on <machine> as <git account> in <worktree>**`` (persona claims exempt).

Segments split on `` · `` outside code spans. ``**TAKEN <date> <who>**`` is a claim,
never a status.

Closed rows are ARCHIVED (RT-QUEUE-ARCHIVE-GRAMMAR; launcher plan
``EterniaLauncher/docs/mission_control/planned/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md`` D1–D3, D6): a
``type: queue-archive`` note under ``Harness_Brain/80 — Archive/Queues/<queue stem>-<YYYY-MM>.md`` holds rows whose
status is replaced by ONE outcome — ``DONE|REFUTED <date> <7–40 hex|here>`` or ``CLOSED <date>: owner — <words>`` —
with at most one ``result:`` (≤ 300) and one ``review:``, and no claim. An outcome on a LIVE row is
``CLOSED ROW LIVE``; a live status or claim on an archived row ``ARCHIVE ROW OPEN``; zero, two or a malformed
outcome ``BAD OUTCOME``; an ID both live and archived ``ARCHIVED ROW LIVE``. The walk parses the CURRENT and
PREVIOUS month in full and ID-scans every month (D8: the gate never re-parses every month); a
``type: queue-archive`` note outside the archive directory, or a ``type: queue`` note inside it, is a defect.
The archive fixtures are the launcher's, byte-identical.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

REPO = Path(__file__).resolve().parents[2]
BRAIN = REPO / "Harness_Brain"

ROW = re.compile(r"^\s*- (?:\[[ xX]\] )?\*\*")
ROW_ID = re.compile(r"^- \*\*`([^`]*)` — ")
ID_SHAPE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
STATUS = re.compile(r"^(READY|BLOCKED|DEFERRED|NEEDS PLAN) (\d{4}-\d{2}-\d{2})(?::\s*(.*))?$", re.DOTALL)
RULED = re.compile(r"^RULED \d{4}-\d{2}-\d{2}\b")
ASSIGNEE = re.compile(r"^assignee: persona:[A-Za-z0-9_.-]+$")
SKILLS = re.compile(r"^skills: `[A-Za-z0-9_./-]+`(?:, `[A-Za-z0-9_./-]+`)*$")
GROUP = re.compile(r"^group: [a-z0-9][a-z0-9.-]*$")
CODE_SPAN = re.compile(r"`([^`]+)`")
WORK_ID = re.compile(r"^WORK-[A-Z2-7]{6}$")
RETIRED = re.compile(r"^(VERDICT|DESIGN|OWNER|PLAN|VERIFY)\b")
REQUIRES = re.compile(r"^REQUIRES(?:\s+(.*))?$", re.DOTALL)
HOSTS = ("windows", "macos", "linux")
TAKEN = re.compile(r"\*\*TAKEN (\d{4}-\d{2}-\d{2}) ([^*]+?)\*\*")
CLAIM_WHO = re.compile(r"^(.+?)(?: on (\S+))?(?: as (.+?))?(?: in (\S+))?$")  # a git account may contain spaces
PLACE_REQUIRED_FROM = "2026-10-27"
OUTCOME_OPEN = re.compile(r"^(?:DONE|REFUTED|CLOSED) \d{4}-\d{2}-\d{2}\b")
OUTCOME = re.compile(r"^(DONE|REFUTED) (\d{4}-\d{2}-\d{2}) ([0-9a-f]{7,40}|here)$")
CLOSED_OUTCOME = re.compile(r"^CLOSED (\d{4}-\d{2}-\d{2}):\s*owner — (.+)$", re.DOTALL)
RESULT_LIMIT = 300
ARCHIVE = BRAIN / "80 — Archive" / "Queues"
ARCHIVE_NAME = re.compile(r"^(.+)-(\d{4}-\d{2})\.md$")
BLOCKED_REASONS = ("owner decision", "owner sitting", "backend", "hermes", "launcher", "upstream", "another lane")
LANE_REASONS = ("backend", "hermes", "launcher", "another lane")
BLOCKER = re.compile(r"^`([A-Z0-9][A-Z0-9._-]*)`(.*)$", re.DOTALL)
CROSS_REPO = re.compile(r"^\s*\(?(launcher|backend|EterniaLauncher|eternia-backend)\b")

#: Lane-blocked rows with no blocker ID when the rule landed (2026-10-18). Shrink-only:
#: lower it in the commit that fills an ID; never raise it.
BLOCKER_ID_CEILING = 0

#: Rows citing a ``planned/`` doc with no ``group:`` segment when the rule landed (2026-11-02).
#: Shrink-only; ``RT-QUEUE-ROW-GROUP-BACKFILL`` took it to 0 (2026-11-02): every plan row now names its group.
GROUP_MISSING_CEILING = 0


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
        if not in_code and line.startswith(" · ", i):
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


def blocker_of(line: str) -> tuple[str, str | None, str] | None:
    """(reason, blocker ID or None, rest) for a lane-blocked row; None for any other row."""
    for segment in split_segments(line):
        status = STATUS.match(segment.strip())
        if status is None or status.group(1) != "BLOCKED":
            continue
        body = (status.group(3) or "").strip()
        reason = blocked_reason(body)
        if reason not in LANE_REASONS:
            return None
        detail = body[len(reason):].lstrip(" :")
        detail = detail[2:].lstrip() if detail.startswith("— ") else detail
        match = BLOCKER.match(detail)
        return (reason, match.group(1), match.group(2)) if match else (reason, None, detail)
    return None


def row_defects(line: str, *, archived: bool = False) -> list[str]:
    """Every grammar defect of one row line (empty when the row is canonical); ``archived``: an archive note's row."""
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
    segments = [s.strip() for s in split_segments(line)]
    statuses = [(i, STATUS.match(s)) for i, s in enumerate(segments) if STATUS.match(s)]
    outcomes = [s for s in segments[1:] if OUTCOME_OPEN.match(s)]
    if archived:
        if statuses or TAKEN.search(line):
            defects.append("ARCHIVE ROW OPEN: an archived row carries no live status and no claim")
        results = [s[len("result:"):].strip() for s in segments[1:] if s.startswith("result:")]
        reviews = [s[len("review:"):].strip() for s in segments[1:] if s.startswith("review:")]
        if (len(outcomes) != 1 or not (OUTCOME.match(outcomes[0]) or CLOSED_OUTCOME.match(outcomes[0]))
                or len(results) > 1 or len(reviews) > 1 or any(not r or len(r) > RESULT_LIMIT for r in results)
                or any(not r for r in reviews)):
            defects.append("BAD OUTCOME: exactly one DONE|REFUTED <date> <sha|here> or CLOSED <date>: owner — "
                           f"<words>, at most one result: (≤ {RESULT_LIMIT}) and one review:")
        statuses = []
    elif outcomes:
        defects.append("CLOSED ROW LIVE: an outcome segment on a live row; a closed row moves to the archive")
    if not archived and len(statuses) != 1:
        defects.append(f"{len(statuses)} status segments; exactly one of READY / BLOCKED / DEFERRED / NEEDS PLAN <date>")
    for index, status in statuses:
        if status.group(1) != "BLOCKED":
            continue
        reason = blocked_reason((status.group(3) or "").strip())
        if reason is None:
            defects.append(f"BLOCKED reason not in {BLOCKED_REASONS}: {segments[index][:60]!r}")
        elif reason == "owner decision" and not any(s.startswith("Recommend:") for s in segments[index + 1:]):
            defects.append("owner decision with no `Recommend: …` segment after it")
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
        if (requires := REQUIRES.match(segment)) is not None:
            hosts = [part.strip() for part in (requires.group(1) or "").split(",")]
            if any(host not in HOSTS for host in hosts) or len(set(hosts)) != len(hosts):
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
    taken = TAKEN.search(line)
    if taken is not None and taken.group(1) >= PLACE_REQUIRED_FROM:
        who = taken.group(2).strip()
        place = CLAIM_WHO.match(who)
        if not who.startswith("persona:") and (place is None or place.group(2) is None):
            defects.append(f"claim dated {taken.group(1)} names no machine; a lane claim is "
                           "`**TAKEN <date> <lane> on <machine> as <git account> in <worktree>**`")
    return defects


def cites_plan(line: str) -> bool:
    """True when a code span on the row names a ``planned/`` doc, any repo's (the launcher's ``citesPlan``)."""

    return any(span.startswith("planned/") or "/planned/" in span for span in CODE_SPAN.findall(line))


def queue_rows(text: str, *, archived: bool = False) -> list[tuple[int, str, list[str]]]:
    """(line number, row line, defects) for every row of one queue note (``archived``: an archive note)."""
    lines = text.split("\n")
    rows: list[tuple[int, str, list[str]]] = []
    in_frontmatter = bool(lines) and lines[0].rstrip() == "---"
    in_fence = False
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r")
        if in_frontmatter:
            if i > 0 and line.rstrip() == "---":
                in_frontmatter = False
            continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not ROW.match(line):
            continue
        defects = row_defects(line, archived=archived)
        following = lines[i + 1].rstrip("\r") if i + 1 < len(lines) else ""
        if following.strip() and following[:1].isspace() and not following.lstrip().startswith(("- ", "#")):
            defects.append("the row continues on the next line; a row is one physical line")
        rows.append((i + 1, line, defects))
    return rows


def note_type(text: str) -> str | None:
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
    return note_type(text) == "queue"


def is_queue_archive(text: str) -> bool:
    return note_type(text) == "queue-archive"


def _queue_notes() -> dict[str, str]:
    return {
        path.relative_to(REPO).as_posix(): text
        for path in sorted(BRAIN.rglob("*.md"))
        if is_queue(text := path.read_text(encoding="utf-8"))
    }


def months_to_parse(today: str) -> tuple[str, str]:
    """The CURRENT and PREVIOUS ``YYYY-MM`` of ``today`` (``YYYY-MM-DD``): the months parsed in full (D8)."""

    year, month = int(today[:4]), int(today[5:7])
    previous = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    return today[:7], previous


def archive_ids(text: str) -> list[str]:
    """Every row ID of an archive note — the cheap line scan run over EVERY month (D8)."""
    return [m.group(1) for line in text.split("\n") if (m := ROW_ID.match(line.lstrip()))]


# --- positive controls: each defect class is caught, the canonical shapes pass ---

VALID = [
    "- **`RT-A` — a ready row** · fork / x · READY 2026-10-18",
    "- **`RT-B` — claimed** · `agent_runtime/x.py::f` · READY 2026-10-18 · **TAKEN 2026-10-18 r-x**",
    "- **`RT-C` — sitting** · BLOCKED 2026-10-18: owner sitting — the Windows box",
    "- **`RT-D` — ruling** · BLOCKED 2026-10-18: owner decision — A or B? · Recommend: A",
    "- **`RT-E` — parked** · RULED 2026-10-10: parked · DEFERRED 2026-10-18: owner said not now",
    "- **`FORK-F.1` — unscoped** · NEEDS PLAN 2026-10-18: the shape of `a · b` **TAKEN 2026-10-18 q**",
    "- **`FORK-G` — other lane** · BLOCKED 2026-10-18: another lane — the next landing",
    "- **`FORK-H` — launcher** · BLOCKED 2026-10-18: launcher — `MC-ROW` lands the painter first",
    "- **`RT-I` — assigned** · assignee: persona:pi_alice_01 · READY 2026-10-18",
    "- **`WORK-A2B3C4` — minted** · assignee: persona:alice · READY 2026-10-18 · **TAKEN 2026-10-18 persona:pi_alice_01**",
    "- **`RT-J` — lent** · assignee: persona:alice · skills: `git-workflow`, `eternia/qa` · READY 2026-10-19",
    "- **`RT-K` — host-bound** · READY 2026-10-26 · REQUIRES windows, macos · regenerate the golden there",
    "- **`RT-L` — placed claim** · READY 2026-10-27 · **TAKEN 2026-10-27 w1027a-x on box-1 as nekwo in w1027a-x**",
    # A git account (`user.name`) may contain spaces; mutation: `as (\S+)` back in CLAIM_WHO -> red.
    "- **`RT-L2` — placed claim, spaced account** · READY 2026-10-27 · **TAKEN 2026-10-27 next-prompt on MUltiversalLabsInc as Maximus Shaban in next-prompt-20261027**",
    "- **`RT-M` — earlier bare claim** · READY 2026-10-26 · **TAKEN 2026-10-26 w1026a-x**",
    "- **`RT-N` — persona claim** · READY 2026-10-27 · **TAKEN 2026-10-27 persona:pi_alice_01**",
    "- **`RT-O` — grouped** · group: companion-templates.tags · plan `docs/x/planned/p.md` · READY 2026-11-02",
]
DEFECTS = {
    "- [ ] **`RT-A` — checkbox** · READY 2026-10-18": "checkbox",
    "- **no id** · READY 2026-10-18": "no ID",
    "- **`rt-lower` — lower** · READY 2026-10-18": "is not",
    "- **`RT-A` — no status** · fork": "0 status",
    "- **`RT-A` — undated** · READY **TAKEN 2026-10-18 x**": "0 status",
    "- **`RT-A` — two** · READY 2026-10-18 · DEFERRED 2026-10-18: x": "2 status",
    "- **`RT-A` — reason** · BLOCKED 2026-10-18: quiet box": "BLOCKED reason",
    "- **`RT-A` — outside** · BLOCKED 2026-10-18: the launcher — row": "BLOCKED reason",
    "- **`RT-A` — ask** · BLOCKED 2026-10-18: owner decision — A or B?": "Recommend",
    "- **`RT-A` — verdict** · READY 2026-10-18 · VERDICT 2026-10-18: keep": "retired",
    "- **`RT-A` — design** · DESIGN · NEEDS PLAN 2026-10-18: x": "retired",
    "- **`RT-A` — ruled** · RULED owner: x · READY 2026-10-18": "undated RULED",
    "- **`RT-A` — open lead · READY 2026-10-18": "does not close",
    "- **`RT-A` — bad assignee** · assignee: bob · READY 2026-10-18": "assignee shape",
    "- **`RT-A` — two assignees** · assignee: persona:a · assignee: persona:b · READY 2026-10-18": "2 assignee",
    "- **`RT-A` — bare skill** · skills: git-workflow · READY 2026-10-19": "skills shape",
    "- **`RT-A` — two skills** · skills: `a` · skills: `b` · READY 2026-10-19": "2 skills",
    "- **`WORK-abc` — bad mint** · READY 2026-10-18": "is not",
    "- **`WORK-ABCDE` — short mint** · READY 2026-10-18": "WORK-<6>",
    "- **`RT-A` — unknown host** · READY 2026-10-26 · REQUIRES windos": "REQUIRES shape",
    "- **`RT-A` — no host** · READY 2026-10-26 · REQUIRES": "REQUIRES shape",
    "- **`RT-A` — repeated host** · READY 2026-10-26 · REQUIRES windows, windows": "REQUIRES shape",
    "- **`RT-A` — capital host** · READY 2026-10-26 · REQUIRES Windows": "REQUIRES shape",
    "- **`RT-A` — two hosts segments** · READY 2026-10-26 · REQUIRES windows · REQUIRES linux": "2 REQUIRES",
    "- **`RT-A` — bare claim** · READY 2026-10-27 · **TAKEN 2026-10-27 w1027a-core**": "names no machine",
    "- **`RT-A` — empty group** · group: · READY 2026-11-02": "group shape",
    "- **`RT-A` — upper group** · group: Companion · READY 2026-11-02": "group shape",
    "- **`RT-A` — code group** · group: `a` · READY 2026-11-02": "group shape",
    "- **`RT-A` — two groups** · group: a · group: b · READY 2026-11-02": "2 group",
    "- **`RT-A` — claim with no on** · READY 2026-10-27 · **TAKEN 2026-10-27 w1027a-core as nekwo in wt**": "names no machine",
}


@pytest.mark.parametrize("line", VALID)
def test_a_canonical_row_passes(line: str) -> None:
    assert row_defects(line) == []


@pytest.mark.parametrize(("line", "expected"), sorted(DEFECTS.items()))
def test_each_defect_class_is_caught(line: str, expected: str) -> None:
    assert any(expected in d for d in row_defects(line)), row_defects(line)


def test_a_wrapped_row_is_caught() -> None:
    text = "---\ntype: queue\n---\n- **`RT-A` — wrapped** · READY 2026-10-18\n  and the rest of it\n"
    assert any("next line" in d for d in queue_rows(text)[0][2])


FIXTURES = REPO / "tests" / "fixtures" / "work_queue"
#: Rows the launcher's canonical ``grammar_valid.md`` accepts that this vault's lint refuses on
#: purpose (ADR 0011 § Row grammar: "no `- [ ] ` checkbox"), with the defect each must name. The
#: ID is read wherever the bold lead opens, so a checkbox row still names itself.
STRICTER_HERE = {"FX-CHECKBOX": "checkbox"}


def _fixture_rows(name: str) -> list[tuple[str | None, str, list[str]]]:
    """(ID or None, line, defects) per row of a shared fixture; a duplicate ID is a defect of each copy."""

    rows = [
        (m.group(1) if (m := re.search(r"\*\*`([^`]*)` — ", line)) else None, line, defects)
        for _, line, defects in queue_rows((FIXTURES / name).read_text(encoding="utf-8"))
    ]
    ids = [row_id for row_id, _, _ in rows if row_id]
    return [
        (row_id, line, defects + (["duplicate ID"] if row_id and ids.count(row_id) > 1 else []))
        for row_id, line, defects in rows
    ]


def test_the_shared_fixtures_pass_and_fail_as_the_launcher_says() -> None:
    valid, broken = _fixture_rows("grammar_valid.md"), _fixture_rows("grammar_defects.md")
    assert len(valid) >= 19 and len(broken) >= 11, "a moved or emptied fixture must not pass silently"
    wrong = [f"valid {row_id}: {defects}" for row_id, _, defects in valid if row_id not in STRICTER_HERE and defects]
    wrong += [
        f"valid {row_id}: expected {STRICTER_HERE[row_id]!r}, got {defects}"
        for row_id, _, defects in valid
        if row_id in STRICTER_HERE and not any(STRICTER_HERE[row_id] in d for d in defects)
    ]
    wrong += [f"defect row passes: {line[:80]}" for _, line, defects in broken if not defects]
    assert not wrong, "\n".join(wrong)


# --- the vault ---


def test_the_walk_found_the_queues() -> None:
    notes = _queue_notes()
    assert len(notes) >= 3, f"a moved or emptied queue directory must not pass silently: {sorted(notes)}"
    assert sum(len(queue_rows(text)) for text in notes.values()) >= 100


def test_every_queue_row_is_in_the_canonical_grammar() -> None:
    bad = [
        f"{path}:{number}: {'; '.join(defects)}\n    {line[:120]}"
        for path, text in _queue_notes().items()
        for number, line, defects in queue_rows(text)
        if defects
    ]
    assert not bad, (
        "Rows the Mission Control board cannot read (grammar: "
        "`Harness_Brain/30 — Decisions/0011` § Row grammar):\n" + "\n".join(bad)
    )


def _lane_blocked_rows() -> list[tuple[str, tuple[str, str | None, str]]]:
    return [
        (f"{path}:{number}", blocked)
        for path, text in _queue_notes().items()
        for number, line, _ in queue_rows(text)
        if (blocked := blocker_of(line)) is not None
    ]


def test_a_same_repo_blocker_id_is_a_row_in_this_vault() -> None:
    ids = {m.group(1) for text in _queue_notes().values() for _, line, _ in queue_rows(text) if (m := ROW_ID.match(line.lstrip()))}
    dangling = [
        f"{where}: `{blocker}`"
        for where, (reason, blocker, rest) in _lane_blocked_rows()
        if blocker is not None and blocker not in ids and not (reason != "another lane" or CROSS_REPO.match(rest))
    ]
    assert not dangling, "BLOCKED on a row that does not exist here (name the repo after a cross-repo ID):\n" + "\n".join(
        dangling
    )


def test_lane_blocked_rows_without_a_blocker_id_only_fall() -> None:
    missing = sorted(where for where, (_, blocker, _) in _lane_blocked_rows() if blocker is None)
    assert len(missing) <= BLOCKER_ID_CEILING, (
        f"{len(missing)} lane-blocked rows name no blocking row (ceiling {BLOCKER_ID_CEILING}); a new "
        "`BLOCKED <date>: backend|hermes|launcher|another lane — ` opens with the blocker's `ID`:\n" + "\n".join(missing)
    )
    assert len(missing) == BLOCKER_ID_CEILING, (
        f"only {len(missing)} lane-blocked rows lack a blocker ID now; lower BLOCKER_ID_CEILING to {len(missing)}"
    )


def _plan_rows_missing_a_group() -> list[str]:
    return sorted(
        f"{path}:{number}"
        for path, text in _queue_notes().items()
        for number, line, _ in queue_rows(text)
        if cites_plan(line) and not any(GROUP.match(s.strip()) for s in split_segments(line)[1:])
    )


def test_plan_rows_missing_a_group_only_fall() -> None:
    missing = _plan_rows_missing_a_group()
    assert len(missing) <= GROUP_MISSING_CEILING, (
        f"{len(missing)} rows cite a `planned/` doc but name no group (ceiling {GROUP_MISSING_CEILING}); a plan row "
        "carries ` · group: <slug>` first after its lead:\n" + "\n".join(missing)
    )
    assert len(missing) == GROUP_MISSING_CEILING, (
        f"only {len(missing)} plan rows lack a group now; lower GROUP_MISSING_CEILING to {len(missing)}"
    )


def test_a_plan_is_cited_with_or_without_a_repo_prefix() -> None:
    assert cites_plan("- **`A` — x** · plan `docs/agent-runtime-harness/planned/p.md` §S2 · READY 2026-11-02")
    assert cites_plan("- **`A` — x** · plan `EterniaLauncher/docs/mission_control/planned/Q.md` · READY 2026-11-02")
    assert cites_plan("- **`A` — x** · `planned/p.md` · READY 2026-11-02")
    assert not cites_plan("- **`A` — x** · `docs/agent-runtime-harness/03-transport-and-wire.md` · READY 2026-11-02")
    assert not cites_plan("- **`A` — x** · planned work · READY 2026-11-02")


def test_blocker_ids_are_read_from_the_dash() -> None:
    assert blocker_of("- **`A` — x** · BLOCKED 2026-10-18: another lane — `RT-B` lands first") == ("another lane", "RT-B", " lands first")
    assert blocker_of("- **`A` — x** · BLOCKED 2026-10-18: backend — `PAY-1` (backend)")[1] == "PAY-1"
    assert blocker_of("- **`A` — x** · BLOCKED 2026-10-18: another lane — the next landing")[1] is None
    assert blocker_of("- **`A` — x** · BLOCKED 2026-10-18: launcher — `MC-1` first")[1] == "MC-1"
    assert blocker_of("- **`A` — x** · BLOCKED 2026-10-18: upstream — `X` merges") is None


def test_every_row_id_is_unique_across_the_vault() -> None:
    seen: dict[str, str] = {}
    duplicates = []
    for path, text in _queue_notes().items():
        for number, line, _ in queue_rows(text):
            match = ROW_ID.match(line.lstrip())
            if match is None:
                continue
            where = f"{path}:{number}"
            if match.group(1) in seen:
                duplicates.append(f"{match.group(1)}: {seen[match.group(1)]} and {where}")
            seen.setdefault(match.group(1), where)
    assert not duplicates, "\n".join(duplicates)


# --- the closed-row archive (RT-QUEUE-ARCHIVE-GRAMMAR, launcher plan D1–D3, D6) ---


def _archive_fixture(name: str) -> list[tuple[str | None, str, list[str]]]:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    assert is_queue_archive(text), f"{name} must stay a type: queue-archive note"
    return [(m.group(1) if (m := ROW_ID.match(line.lstrip())) else None, line, defects)
            for _, line, defects in queue_rows(text, archived=True)]


def test_the_archive_fixtures_pass_and_fail_as_the_launcher_says() -> None:
    """Mutation: drop ``|here`` from OUTCOME -> FX-ARCH-DONE-HERE is BAD OUTCOME, red; drop the claim check in the
    archived arm -> FX-ARCH-CLAIM passes, red."""
    valid, broken = _archive_fixture("archive_valid.md"), _archive_fixture("archive_defects.md")
    assert len(valid) >= 8 and len(broken) >= 7, "a moved or emptied archive fixture must not pass silently"
    wrong = [f"valid {row_id}: {defects}" for row_id, _, defects in valid if defects]
    wrong += [f"defect row passes: {line[:80]}" for _, line, defects in broken if not defects]
    assert not wrong, "\n".join(wrong)


def archived_live(live: dict[str, str], archives: dict[str, str]) -> list[str]:
    """``ARCHIVED ROW LIVE``: every ID both in a live queue note and in an archive note (a close MOVES a row)."""

    live_ids = {m.group(1) for text in live.values() for _, line, _ in queue_rows(text)
                if (m := ROW_ID.match(line.lstrip()))}
    return sorted(f"ARCHIVED ROW LIVE: `{row_id}` ({path})" for path, text in archives.items()
                  for row_id in archive_ids(text) if row_id in live_ids)


def test_an_id_both_live_and_archived_is_archived_row_live() -> None:
    """Mutation: scan no archive IDs in ``archived_live`` -> the overlap fixture passes, red."""
    live = {"grammar_valid.md": (FIXTURES / "grammar_valid.md").read_text(encoding="utf-8")}
    overlap = {"archive_live_overlap.md": (FIXTURES / "archive_live_overlap.md").read_text(encoding="utf-8")}
    assert archived_live(live, overlap) == ["ARCHIVED ROW LIVE: `FX-READY` (archive_live_overlap.md)"]
    clean = {"archive_valid.md": (FIXTURES / "archive_valid.md").read_text(encoding="utf-8")}
    assert archived_live(live, clean) == []


def test_the_months_parsed_in_full_are_this_one_and_the_last() -> None:
    assert months_to_parse("2026-11-03") == ("2026-11", "2026-10")
    assert months_to_parse("2027-01-02") == ("2027-01", "2026-12")


def _archive_notes() -> dict[str, str]:
    return {path.relative_to(REPO).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(ARCHIVE.glob("*.md"))} if ARCHIVE.is_dir() else {}


def test_every_archive_note_sits_in_the_archive_and_names_its_month() -> None:
    misplaced = [f"{path.relative_to(REPO).as_posix()}: a type: queue-archive note outside `80 — Archive/Queues/`"
                 for path in sorted(BRAIN.rglob("*.md"))
                 if path.parent != ARCHIVE and is_queue_archive(path.read_text(encoding="utf-8"))]
    for path, text in _archive_notes().items():
        name = ARCHIVE_NAME.match(path.rsplit("/", 1)[-1])
        if is_queue(text):
            misplaced.append(f"{path}: a type: queue note inside the archive directory")
        elif not is_queue_archive(text):
            continue
        elif name is None or f"month: {name.group(2)}" not in text.split("\n---", 1)[0]:
            misplaced.append(f"{path}: an archive note is <queue stem>-<YYYY-MM>.md with that `month:`")
    assert not misplaced, "\n".join(misplaced)


def test_the_recent_archive_months_are_in_the_archive_grammar_and_no_closed_row_is_live() -> None:
    from datetime import date

    recent = months_to_parse(date.today().isoformat())
    archives = {path: text for path, text in _archive_notes().items() if is_queue_archive(text)}
    bad = [f"{path}:{number}: {'; '.join(defects)}\n    {line[:120]}"
           for path, text in archives.items()
           if (name := ARCHIVE_NAME.match(path.rsplit("/", 1)[-1])) and name.group(2) in recent
           for number, line, defects in queue_rows(text, archived=True) if defects]
    ids = [row_id for text in archives.values() for row_id in archive_ids(text)]
    bad += [f"`{row_id}` is archived twice" for row_id in sorted({i for i in ids if ids.count(i) > 1})]
    bad += archived_live(_queue_notes(), archives)
    assert not bad, "\n".join(bad)
