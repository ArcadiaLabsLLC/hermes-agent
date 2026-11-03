"""The queue ROW-HISTORY guard: what a change does to rows that already exist on ``origin/main``.

Ported from the launcher's ``EterniaLauncher/tool/queue/queue_row_guard.dart`` (row
``RT-QUEUE-DELETE-NEEDS-ROW-OWNER``; ADR 0038,
``EterniaLauncher/Launcher_Brain/30 — Decisions/0038 — A teammate's row is deleted only on that teammate's explicit authorization.md``).
The grammar gate (``tests/tooling/test_work_queue_row_grammar.py``) cannot see this half, because a
row that lost a ruling or vanished is still perfectly well-formed. One comparison of this vault's
rows at ``merge-base(HEAD, origin/main)`` against the working tree: a row present on both sides
that lost a ``RULED <date>: …`` segment, or whose status date went BACKWARDS (the older side of a
merge conflict), REDS.

Who filed a deleted row is not checked: ADR 0038's 2026-11-01 amendment (owner, "doesn't matter who
filed them do them all if they are ready") retired that rule, and its filer arm went with it
(``FH-QUEUE-GUARD-FILER-ARM-RETIRE``).

Closed rows are ARCHIVED (RT-QUEUE-ARCHIVE-GRAMMAR, launcher plan
``EterniaLauncher/docs/mission_control/planned/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md`` D6), and three more arms
read the archive: ``closed_without_archive`` — a row live at the base and gone from the live queues is in no
archive line this push added (a row MOVED to another queue is still live by ID); it refuses for a push whose
newest commit is dated :data:`ARCHIVE_REQUIRED_FROM` or later and is a NOTE before, so lanes dispatched under
the delete rule land; ``archived_row_live`` — an ID in an archive note and in a live queue; and
``outcome_sha_unreachable`` — a new archive line's ``<commit>`` (not ``here``) is not an ancestor of HEAD (a
rebased lane: re-point it at the rebased twin).

Every finding is passed when a commit in ``base..HEAD`` carries an ``Authorized-by:`` line and names the
row's ID — the row owner's own words, quoted. Every finding names its row.

The decision is the pure :func:`findings`; :func:`run` does the git reads. By hand::

    python -m tests.tooling._queue_row_guard
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from tests.tooling.test_work_queue_row_grammar import (
    BRAIN, OUTCOME, OUTCOME_OPEN, REPO, ROW_ID, RULED, STATUS, is_queue, is_queue_archive,
    queue_rows, split_segments,
)

__all__ = [
    "Change",
    "Finding",
    "GuardReport",
    "Row",
    "authorized_row_ids",
    "findings",
    "rows_by_id",
    "run",
]


@dataclass(frozen=True, slots=True)
class Row:
    id: str
    file: str
    line: int
    status_date: str | None
    rulings: tuple[str, ...]


def rows_by_id(files: Mapping[str, str]) -> dict[str, Row]:
    """The rows of ``files`` (path → text) by ID; a duplicate keeps its first line (the grammar gate's business)."""
    out: dict[str, Row] = {}
    for path, text in files.items():
        if not is_queue(text):
            continue
        for number, line, _defects in queue_rows(text):
            match = ROW_ID.match(line.lstrip())
            if match is None or match.group(1) in out:
                continue
            segments = [segment.strip() for segment in split_segments(line)]
            dates = [status.group(2) for s in segments if (status := STATUS.match(s)) is not None]
            out[match.group(1)] = Row(match.group(1), path, number, dates[0] if dates else None,
                                      tuple(s for s in segments[1:] if RULED.match(s)))
    return out


_AUTHORIZED = re.compile(r"^\s*Authorized-by:\s*\S", re.IGNORECASE | re.MULTILINE)
_ROW_ID_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9._]*(?:-[A-Z0-9._]+)+")
_BACKTICKED_ID = re.compile(r"`([A-Z0-9][A-Z0-9._-]*)`")


def authorized_row_ids(messages: Iterable[str]) -> set[str]:
    """Every row ID named in a commit message that carries an ``Authorized-by:`` line."""
    ids: set[str] = set()
    for message in messages:
        if _AUTHORIZED.search(message):
            ids.update(match.group(0) for match in _ROW_ID_TOKEN.finditer(message))
            ids.update(match.group(1) for match in _BACKTICKED_ID.finditer(message))
    return ids


class Change(Enum):
    RULING_DROPPED = "ruling_dropped"
    STATUS_DATE_REGRESSED = "status_date_regressed"
    CLOSED_WITHOUT_ARCHIVE = "closed_without_archive"
    ARCHIVED_ROW_LIVE = "archived_row_live"
    OUTCOME_SHA_UNREACHABLE = "outcome_sha_unreachable"


#: The kinds that red — every kind the guard reports (``closed_without_archive`` is a note before
#: :data:`ARCHIVE_REQUIRED_FROM`: :attr:`Finding.note`).
REFUSING: frozenset[Change] = frozenset(Change)

#: The first push date (its newest commit's committer date) a close must archive on; before it a deleted row
#: is a note (the launcher's ``kArchiveRequiredFrom``, plan D6).
ARCHIVE_REQUIRED_FROM = "2026-11-04"


@dataclass(frozen=True, slots=True)
class Archived:
    """One archived row: its archive note and its outcome's commit (None for CLOSED, ``here`` for the close)."""

    id: str
    file: str
    commit: str | None


def archived_by_id(files: Mapping[str, str]) -> dict[str, Archived]:
    """The archived rows of ``files`` (path → text, ``type: queue-archive`` notes only) by ID; first line wins."""
    out: dict[str, Archived] = {}
    for path, text in files.items():
        if not is_queue_archive(text):
            continue
        for _number, line, _defects in queue_rows(text, archived=True):
            match = ROW_ID.match(line.lstrip())
            if match is None or match.group(1) in out:
                continue
            outcome = next((s.strip() for s in split_segments(line)[1:] if OUTCOME_OPEN.match(s.strip())), "")
            done = OUTCOME.match(outcome)
            out[match.group(1)] = Archived(match.group(1), path, done.group(3) if done else None)
    return out


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    change: Change
    message: str
    #: Reported, never refusing (``closed_without_archive`` before :data:`ARCHIVE_REQUIRED_FROM`).
    note: bool = False

    @property
    def refuses(self) -> bool:
        return self.change in REFUSING and not self.note

    def __str__(self) -> str:
        return self.message


def findings(*, base: Mapping[str, Row], head: Mapping[str, Row], authorized: set[str],
             archived: Mapping[str, Archived] | None = None, added: Mapping[str, Archived] | None = None,
             reachable: Callable[[str], bool] = lambda _sha: True, archive_required: bool = True) -> list[Finding]:
    """Every watched change: one per surviving row and kind, then the archive arms (``archived``: every archived
    row at the head; ``added``: the archive lines this push added; ``reachable``: is a sha an ancestor of HEAD)."""
    out: list[Finding] = []
    archived, added = archived or {}, added or {}
    for row_id, before in base.items():
        if row_id in authorized or row_id in head or row_id in added:
            continue
        out.append(Finding(row_id, Change.CLOSED_WITHOUT_ARCHIVE,
                           f"`{row_id}` ({before.file}:{before.line}) left the live queues and is in no archive line "
                           f"this push added — close it with `scripts/work_row.py close {row_id} --done <sha>`",
                           note=not archive_required))
    for row_id, entry in sorted(archived.items()):
        if row_id in head and row_id not in authorized:
            after = head[row_id]
            out.append(Finding(row_id, Change.ARCHIVED_ROW_LIVE,
                               f"`{row_id}` is archived in {entry.file} and still live at {after.file}:{after.line} "
                               "— a close MOVES the row"))
    for row_id, entry in sorted(added.items()):
        if entry.commit and entry.commit != "here" and row_id not in authorized and not reachable(entry.commit):
            out.append(Finding(row_id, Change.OUTCOME_SHA_UNREACHABLE,
                               f"`{row_id}` ({entry.file}) names {entry.commit}, not an ancestor of HEAD — a rebase "
                               "renamed it; point the outcome at the rebased commit"))
    for row_id, before in base.items():
        if row_id in authorized:
            continue
        after = head.get(row_id)
        if after is None:
            continue
        for ruling in before.rulings:
            if ruling not in after.rulings:
                shown = ruling if len(ruling) <= 90 else ruling[:90] + "…"
                out.append(Finding(row_id, Change.RULING_DROPPED,
                                   f"`{row_id}` ({after.file}:{after.line}) lost `{shown}` — a merge keeps every "
                                   f"ruling (row union); dropping one needs an `Authorized-by:` line naming `{row_id}`"))
        if before.status_date and after.status_date and after.status_date < before.status_date:
            out.append(Finding(row_id, Change.STATUS_DATE_REGRESSED,
                               f"`{row_id}` ({after.file}:{after.line}) status date went back from "
                               f"{before.status_date} to {after.status_date} — the older side of a conflict, "
                               f"or a reverted status"))
    return out


@dataclass(frozen=True, slots=True)
class GuardReport:
    base: str | None
    compared: int
    findings: list[Finding]
    skipped: str | None = None


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return result.stdout if result.returncode == 0 else None


def _files_at(root: Path, ref: str) -> dict[str, str]:
    """Every ``type: queue`` and ``type: queue-archive`` note of the vault at ``ref``."""
    brain = BRAIN.relative_to(REPO).as_posix()
    listing = _git(root, "grep", "-l", "-z", "^type: queue", ref, "--", brain) or ""
    files: dict[str, str] = {}
    for entry in filter(None, listing.split("\0")):
        path = entry.split(":", 1)[1] if entry.startswith(ref + ":") else entry
        if path.endswith(".md") and (text := _git(root, "show", f"{ref}:{path}")) is not None:
            files[path] = text
    return files


def _working_tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): text for path in sorted((root / BRAIN.name).rglob("*.md"))
            if is_queue(text := path.read_text(encoding="utf-8")) or is_queue_archive(text)}


def _ancestor(root: Path, sha: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=root, capture_output=True,
                          check=False).returncode == 0


def run(root: Path = REPO, *, upstream: str = "origin/main") -> GuardReport:
    """Compare this vault at ``merge-base(HEAD, upstream)`` with the working tree."""
    base = (_git(root, "merge-base", "HEAD", upstream) or "").strip()
    if not base:
        return GuardReport(None, 0, [], skipped=f"no merge base with {upstream} in this checkout")
    base_files, head_files = _files_at(root, base), _working_tree(root)
    base_rows = rows_by_id(base_files)
    head_rows = rows_by_id(head_files)
    archived = archived_by_id(head_files)
    before = archived_by_id(base_files)
    added = {row_id: entry for row_id, entry in archived.items() if row_id not in before}
    messages = (_git(root, "log", "--format=%B%x00", f"{base}..HEAD") or "").split("\x00")
    newest = (_git(root, "log", "-1", "--format=%cs", "HEAD") or "").strip()
    return GuardReport(base, len(base_rows), findings(
        base=base_rows, head=head_rows, authorized=authorized_row_ids(messages), archived=archived, added=added,
        reachable=lambda sha: _ancestor(root, sha), archive_required=newest >= ARCHIVE_REQUIRED_FROM))


def main() -> int:
    report = run()
    if report.skipped:
        print(f"queue row guard: skipped — {report.skipped}")
        return 0
    refused = [finding for finding in report.findings if finding.refuses]
    for finding in report.findings:
        print(("RED  " if finding.refuses else "NOTE ") + finding.message)
    print(f"queue row guard: {report.compared} rows at {report.base[:10]}, {len(refused)} refused")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
