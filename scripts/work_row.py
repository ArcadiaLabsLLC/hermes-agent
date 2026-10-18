#!/usr/bin/env python3
"""Apply one work-queue row operation by ID in a SESSION's checkout, then commit and push it.

    python scripts/work_row.py <claim|release|set-status|delete|append> <ID> --who <lane>
        [--note <path>] [--status "<segment>"] [--row "<line>"] [--repo <checkout>] [--no-commit]

The edit is ``agent_runtime.work_store.grammar.apply`` — the same one-line, by-ID edit the Work
writer makes (plan ``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` §5, §6.2):
a session that races the engine re-applies its op here instead of resolving a text conflict.
The row is found across ``*_Brain/20 — Active Initiatives/*.md`` (or ``--note``); the commit is
by pathspec under the session's own git identity; a non-fast-forward push exits 3 with the hint
"fetch, then re-run". It never runs ``fetch``, ``reset``, ``stash``, ``pull``, ``merge`` or
``rebase`` on the checkout.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.work_store.grammar import Op, apply, find, is_queue, parse_note, row_defects  # noqa: E402
from agent_runtime.work_store.reasons import Reason, WorkRefused  # noqa: E402

COMMANDS = {"claim": Op.CLAIM, "release": Op.RELEASE, "set-status": Op.SET_STATUS, "delete": Op.DELETE,
            "append": Op.APPEND}
BRAIN_GLOBS = ("*_Brain/20 — Active Initiatives/*.md", "*_brain/20 — Active Initiatives/*.md")
NON_FAST_FORWARD = ("! [rejected]", "fetch first", "non-fast-forward")
EXIT_REFUSED = 2
EXIT_NON_FAST_FORWARD = 3
EXIT_GIT_FAILED = 4

Git = Callable[[list[str], Path], subprocess.CompletedProcess]


def run_git(args: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)


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
    return parser.parse_args(argv)


def queue_notes(repo: Path, note: str | None) -> list[Path]:
    if note:
        return [repo / note]
    found = [path for pattern in BRAIN_GLOBS for path in sorted(repo.glob(pattern))]
    return [path for path in found if is_queue(path.read_text(encoding="utf-8"))]


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


def edited_text(text: str, args: argparse.Namespace) -> str:
    op = COMMANDS[args.command]
    if op is Op.APPEND:
        if not args.row or row_defects(args.row) or f"`{args.row_id}` — " not in args.row:
            raise WorkRefused(Reason.GRAMMAR_INVALID, "--row is one canonical row carrying the ID")
        return text + ("" if text.endswith("\n") else "\n") + args.row + "\n"
    row = find(parse_note(text, slot="", note=""), args.row_id)
    lines = text.split("\n")
    carriage = "\r" if lines[row.line_no - 1].endswith("\r") else ""
    new = apply(row.raw, op, who=args.who, date=date.today().isoformat(), payload={"status": args.status or ""})
    if new is None:
        del lines[row.line_no - 1]
    else:
        lines[row.line_no - 1] = new + carriage
    return "\n".join(lines)


def commit_and_push(repo: Path, note: Path, args: argparse.Namespace, git: Git) -> int:
    relative = note.relative_to(repo).as_posix()
    for step in (["add", "--", relative],
                 ["commit", "-q", "-m", f"queue: {COMMANDS[args.command].value} {args.row_id} {args.who}", "--", relative]):
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
        note.write_bytes(edited_text(text, args).encode("utf-8"))
    except WorkRefused as refusal:
        print(f"refused: {refusal.reason.value} {refusal.detail}".rstrip(), file=sys.stderr)
        return EXIT_REFUSED
    if args.no_commit:
        return 0
    return commit_and_push(repo, note, args, git)


if __name__ == "__main__":
    raise SystemExit(main())
