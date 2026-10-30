"""The queue ROW-HISTORY guard: what a change does to rows that already exist on ``origin/main``.

Ported from the launcher's ``EterniaLauncher/tool/queue/queue_row_guard.dart`` (row
``RT-QUEUE-DELETE-NEEDS-ROW-OWNER``; ADR 0038,
``EterniaLauncher/Launcher_Brain/30 — Decisions/0038 — A teammate's row is deleted only on that teammate's explicit authorization.md``).
The grammar gate (``tests/tooling/test_work_queue_row_grammar.py``) cannot see this half, because a
row that lost a ruling or vanished is still perfectly well-formed. One comparison of this vault's
rows at ``merge-base(HEAD, origin/main)`` against the working tree:

* a row present on both sides that lost a ``RULED <date>: …`` segment, or whose status date went
  BACKWARDS (the older side of a merge conflict) — this REDS;
* a row deleted from every queue whose filing commit's author is a different teammate from the
  pusher (``git config user.*``) — this is a NOTE, printed and never refused (owner ruling
  2026-10-29, "Keep it a note": a DONE close and an inference-delete look the same to a diff).

Either is passed when a commit in ``base..HEAD`` carries an ``Authorized-by:`` line and names the
row's ID — the row owner's own words, quoted. Every finding names its row.

The decision is the pure :func:`findings`; :func:`run` does the git reads. By hand::

    python -m tests.tooling._queue_row_guard
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from tests.tooling.test_work_queue_row_grammar import BRAIN, REPO, ROW_ID, RULED, STATUS, is_queue, queue_rows, split_segments

__all__ = [
    "Change",
    "Finding",
    "GuardReport",
    "Row",
    "RowOwner",
    "authorized_row_ids",
    "findings",
    "rows_by_id",
    "run",
]


@dataclass(frozen=True, slots=True)
class RowOwner:
    """A git identity: who filed a row, or who is pushing."""

    name: str
    email: str

    @property
    def automated(self) -> bool:
        """A cloud agent's default author names no teammate, so its rows have no owner to protect."""
        email = self.email.strip().lower()
        return email == "noreply@anthropic.com" or email.endswith("@eternia.local")

    def same_teammate_as(self, other: RowOwner) -> bool:
        """One teammate commits under several identities; a shared name or email is the same person."""
        return (self.name.strip().lower() == other.name.strip().lower()
                or self.email.strip().lower() == other.email.strip().lower())

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


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
    TEAMMATE_ROW_DELETED = "teammate_row_deleted"


#: The kinds that red; a teammate-row deletion is a note (owner ruling 2026-10-29, "Keep it a note").
REFUSING: frozenset[Change] = frozenset({Change.RULING_DROPPED, Change.STATUS_DATE_REGRESSED})


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    change: Change
    message: str

    @property
    def refuses(self) -> bool:
        return self.change in REFUSING

    def __str__(self) -> str:
        return self.message


def findings(*, base: Mapping[str, Row], head: Mapping[str, Row], pusher: RowOwner,
             filer_of: Callable[[Row], RowOwner | None], authorized: set[str]) -> list[Finding]:
    """Every watched change, one per row and kind. An unknown filer is never guessed."""
    out: list[Finding] = []
    for row_id, before in base.items():
        if row_id in authorized:
            continue
        after = head.get(row_id)
        if after is None:
            filer = filer_of(before)
            if filer is not None and not filer.automated and not filer.same_teammate_as(pusher):
                out.append(Finding(row_id, Change.TEAMMATE_ROW_DELETED,
                                   f"`{row_id}` ({before.file}) is deleted, and {filer} filed it — a teammate's "
                                   f"row is deleted only on their explicit authorization: quote them on an "
                                   f"`Authorized-by:` line in a commit that names `{row_id}` (ADR 0038)"))
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
            if is_queue(text := path.read_text(encoding="utf-8"))}


def run(root: Path = REPO, *, upstream: str = "origin/main") -> GuardReport:
    """Compare this vault at ``merge-base(HEAD, upstream)`` with the working tree, pushed by ``git config``."""
    base = (_git(root, "merge-base", "HEAD", upstream) or "").strip()
    if not base:
        return GuardReport(None, 0, [], skipped=f"no merge base with {upstream} in this checkout")
    base_rows = rows_by_id(_files_at(root, base))
    head_rows = rows_by_id(_working_tree(root))
    pusher = RowOwner((_git(root, "config", "user.name") or "").strip(),
                      (_git(root, "config", "user.email") or "").strip())
    messages = (_git(root, "log", "--format=%B%x00", f"{base}..HEAD") or "").split("\x00")

    def filer_of(row: Row) -> RowOwner | None:
        for needle in (f"**`{row.id}` —", f"`{row.id}`"):
            log = _git(root, "log", base, "--reverse", "--format=%an%x09%ae", f"-S{needle}", "--", row.file)
            first = next((line for line in (log or "").splitlines() if "\t" in line), None)
            if first:
                name, email = first.split("\t", 1)
                return RowOwner(name, email)
        return None

    deleted = {row_id: row for row_id, row in base_rows.items() if row_id not in head_rows}
    # Each filer is one history-wide ``git log -S`` (~1.5 s on this vault); they are independent, so
    # they run side by side and a push deleting N rows pays about one, not N (the prepush budget,
    # FH-PREPUSH-PROGRESS-BUDGET).
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(deleted)))) as pool:
        filers = dict(zip(deleted, pool.map(filer_of, deleted.values()), strict=True))
    return GuardReport(base, len(base_rows), findings(
        base=base_rows, head=head_rows, pusher=pusher, filer_of=lambda row: filers.get(row.id),
        authorized=authorized_row_ids(messages)))


def main() -> int:
    report = run()
    if report.skipped:
        print(f"queue row guard: skipped — {report.skipped}")
        return 0
    for finding in report.findings:
        print(("RED  " if finding.refuses else "NOTE ") + finding.message)
    refused = sum(1 for finding in report.findings if finding.refuses)
    print(f"queue row guard: {report.compared} rows at {report.base[:10]}, {refused} refused, "
          f"{len(report.findings) - refused} noted")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
