#!/usr/bin/env python3
"""Apply one work-queue row operation by ID in a SESSION's checkout, then commit and push it.

    python scripts/work_row.py <claim|release|set-status|delete|append> <ID> --who <lane>
        [--note <path>] [--status "<segment>"] [--row "<line>"] [--repo <checkout>] [--no-commit]
        [--machine <host>] [--account <git account>] [--worktree <folder>]
    python scripts/work_row.py close <ID> --who <lane> (--done <sha|here> | --refuted <sha|here> | --owner "<words>")
        [--result "<line>"] [--date YYYY-MM-DD] [--note <path>] [--repo <checkout>] [--no-commit]

``close`` ARCHIVES the row (RT-QUEUE-ARCHIVE-GRAMMAR, launcher plan
``EterniaLauncher/docs/mission_control/planned/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md`` D3–D5): the claim mark
removed, the status replaced by ONE outcome, the line appended to
``<brain>/80 — Archive/Queues/<queue stem>-<YYYY-MM>.md`` (created with its head) and dropped from the queue — both
files in one commit, ``queue(<stem>): close <ID> <outcome>``.

A claim names its place (ADR 0025's 2026-10-26 amendment): ``**TAKEN <date> <lane> on <machine> as
<git account> in <worktree>**``. ``--machine`` defaults to the hostname, ``--account`` to the
checkout's ``git config user.name``, ``--worktree`` to the checkout's folder name; a part that cannot
be read refuses ``invalid`` rather than writing a claim the grammar rejects.

The edit is ``agent_runtime.work_store.grammar.apply`` — the same one-line, by-ID edit the Work
writer makes (plan ``docs/agent-runtime-harness/archive/work-on-markdown-2026-10-18.md`` §5, §6.2):
a session that races the engine re-applies its op here instead of resolving a text conflict.
The row is found across ``*_Brain/20 — Active Initiatives/*.md`` (or ``--note``); the commit is
by pathspec under the session's own git identity; a non-fast-forward push exits 3 with the hint
"fetch, then re-run". It never runs ``fetch``, ``reset``, ``stash``, ``pull``, ``merge`` or
``rebase`` on the checkout.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.work_store.grammar import (
    Op, apply, archive_note_for, archive_note_text, find, is_queue, parse_note, parse_outcome, row_defects,
    split_segments,
)
from agent_runtime.work_store.reasons import Reason, WorkRefused

COMMANDS = {"claim": Op.CLAIM, "release": Op.RELEASE, "set-status": Op.SET_STATUS, "delete": Op.DELETE,
            "append": Op.APPEND, "close": Op.CLOSE}
BRAIN_GLOBS = ("*_Brain/20 — Active Initiatives/*.md", "*_brain/20 — Active Initiatives/*.md")
NON_FAST_FORWARD = ("! [rejected]", "fetch first", "non-fast-forward")
EXIT_REFUSED = 2
EXIT_NON_FAST_FORWARD = 3
EXIT_GIT_FAILED = 4

Git = Callable[[list[str], Path], subprocess.CompletedProcess]


def run_git(args: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, check=False)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("row_id", metavar="ID")
    parser.add_argument("--who", required=True)
    parser.add_argument("--note")
    parser.add_argument("--status")
    parser.add_argument("--row")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--machine")
    parser.add_argument("--account")
    parser.add_argument("--worktree")
    outcome = parser.add_mutually_exclusive_group()
    outcome.add_argument("--done", metavar="SHA")
    outcome.add_argument("--refuted", metavar="SHA")
    outcome.add_argument("--owner", metavar="WORDS")
    parser.add_argument("--result")
    parser.add_argument("--date")
    return parser.parse_args(argv)


def close_payload(args: argparse.Namespace) -> dict:
    """``Op.CLOSE``'s payload from ``--done`` / ``--refuted`` / ``--owner`` (exactly one), ``--result``, ``--date``."""

    if args.done is not None:
        payload = {"outcome": "DONE", "commit": args.done}
    elif args.refuted is not None:
        payload = {"outcome": "REFUTED", "commit": args.refuted}
    elif args.owner is not None:
        payload = {"outcome": "CLOSED", "words": args.owner}
    else:
        raise WorkRefused(Reason.INVALID, "close names --done <sha>, --refuted <sha> or --owner <words>")
    return {**payload, "result": args.result or "", "date": args.date or date.today().isoformat()}


def closed_texts(repo: Path, note: Path, text: str, args: argparse.Namespace) -> tuple[str, Path, str]:
    """``(queue text without the row, archive path, archive text with it)`` for ``close``."""

    row = find(parse_note(text, slot="", note=""), args.row_id)
    archived = apply(row.raw, Op.CLOSE, who=args.who, date=date.today().isoformat(), payload=close_payload(args))
    outcome = next(o for o in map(parse_outcome, (s.strip() for s in split_segments(archived))) if o is not None)
    archive = repo / archive_note_for(note.relative_to(repo).as_posix(), outcome.date)
    front = text.split("\n---", 1)[0].split("\n")
    program = next((line.split(":", 1)[1].strip() for line in front if line.startswith("program:")), None)
    head = archive.read_bytes().decode("utf-8") if archive.is_file() else archive_note_text(
        note.name, program, outcome.date[:7])
    lines = text.split("\n")
    del lines[row.line_no - 1]
    return "\n".join(lines), archive, head + ("" if head.endswith("\n") else "\n") + archived + "\n"


def queue_notes(repo: Path, note: str | None) -> list[Path]:
    if note:
        return [repo / note]
    found = [path for pattern in BRAIN_GLOBS for path in sorted(repo.glob(pattern))]
    return [path for path in found if is_queue(path.read_text(encoding="utf-8-sig"))]


def _note_and_text(repo: Path, args: argparse.Namespace) -> tuple[Path, str]:
    notes = queue_notes(repo, args.note)
    for path in notes:
        text = path.read_bytes().decode("utf-8")
        rows = parse_note(text, slot="", note=path.name)
        if find(rows, args.row_id) is not None:
            if COMMANDS[args.command] is Op.APPEND:
                raise WorkRefused(Reason.ID_EXISTS, args.row_id)
            return path, text
    if COMMANDS[args.command] is Op.APPEND and notes and notes[0].is_file():
        return notes[0], notes[0].read_bytes().decode("utf-8")
    raise WorkRefused(Reason.ROW_GONE if notes else Reason.NOTE_MISSING, args.row_id)


def _place_token(value: str | None, part: str) -> str:
    token = "-".join(str(value or "").split())
    if not token or "*" in token:
        raise WorkRefused(Reason.INVALID, f"the claim's {part} is unreadable; pass --{part}")
    return token


def claim_who(args: argparse.Namespace, repo: Path) -> str:
    """``<lane> on <machine> as <git account> in <worktree>`` — the who a lane claim writes."""

    if " on " in args.who:
        return args.who
    machine = args.machine if args.machine is not None else socket.gethostname()
    account = args.account if args.account is not None else run_git(["config", "user.name"], repo).stdout.strip()
    worktree = args.worktree if args.worktree is not None else repo.name
    return (f"{args.who} on {_place_token(machine, 'machine')} as {_place_token(account, 'account')} "
            f"in {_place_token(worktree, 'worktree')}")


def edited_text(text: str, args: argparse.Namespace) -> str:
    op = COMMANDS[args.command]
    if op is Op.APPEND:
        if not args.row or row_defects(args.row) or f"`{args.row_id}` — " not in args.row:
            raise WorkRefused(Reason.GRAMMAR_INVALID, "--row is one canonical row carrying the ID")
        return text + ("" if text.endswith("\n") else "\n") + args.row + "\n"
    row = find(parse_note(text, slot="", note=""), args.row_id)
    lines = text.split("\n")
    carriage = "\r" if lines[row.line_no - 1].endswith("\r") else ""
    who = claim_who(args, Path(args.repo).resolve()) if op is Op.CLAIM else args.who
    new = apply(row.raw, op, who=who, date=date.today().isoformat(), payload={"status": args.status or ""})
    if new is None:
        del lines[row.line_no - 1]
    else:
        lines[row.line_no - 1] = new + carriage
    return "\n".join(lines)


def commit_and_push(repo: Path, note: Path, args: argparse.Namespace, git: Git, *, also: Path | None = None) -> int:
    relative = [note.relative_to(repo).as_posix(), *([also.relative_to(repo).as_posix()] if also else [])]
    if also is None:
        subject = f"queue: {COMMANDS[args.command].value} {args.row_id} {args.who}"
    else:
        word = f"DONE {args.done}" if args.done else f"REFUTED {args.refuted}" if args.refuted else "CLOSED by owner"
        subject = f"queue({note.stem}): close {args.row_id} {word}"
    for step in (["add", "--", *relative], ["commit", "-q", "-m", subject, "--", *relative]):
        done = git(step, repo)
        if done.returncode != 0:
            print(f"git {step[0]} failed: {str(done.stderr).strip()[-300:]}", file=sys.stderr)
            return EXIT_GIT_FAILED
    pushed = git(["push", "-q"], repo)
    if pushed.returncode == 0:
        return 0
    if any(marker in str(pushed.stderr) for marker in NON_FAST_FORWARD):
        print("push rejected (non-fast-forward): fetch, then re-run", file=sys.stderr)
        return EXIT_NON_FAST_FORWARD
    print(f"git push failed: {str(pushed.stderr).strip()[-300:]}", file=sys.stderr)
    return EXIT_GIT_FAILED


def main(argv: list[str] | None = None, *, git: Git = run_git) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = Path(args.repo).resolve()
    try:
        note, text = _note_and_text(repo, args)
        archive = None
        if COMMANDS[args.command] is Op.CLOSE:
            queue_text, archive, archive_text = closed_texts(repo, note, text, args)
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(archive_text.encode("utf-8"))
            note.write_bytes(queue_text.encode("utf-8"))
        else:
            note.write_bytes(edited_text(text, args).encode("utf-8"))
    except WorkRefused as refusal:
        print(f"refused: {refusal.reason.value} {refusal.detail}".rstrip(), file=sys.stderr)
        return EXIT_REFUSED
    if args.no_commit:
        return 0
    return commit_and_push(repo, note, args, git, also=archive)


if __name__ == "__main__":
    raise SystemExit(main())
