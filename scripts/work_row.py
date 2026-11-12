#!/usr/bin/env python3
"""Apply one work-queue row operation by ID in a SESSION's checkout, then commit and push it.

    python scripts/work_row.py <claim|release|set-status|delete|append> <ID> --who <lane>
        [--note <path>] [--status "<segment>"] [--row "<line>"] [--repo <checkout>] [--no-commit]
        [--machine <host>] [--account <git account>] [--worktree <folder>]
    python scripts/work_row.py close <ID> --who <lane> (--done <sha|here> | --refuted <sha|here> | --owner "<words>")
        [--result "<line>"] [--date YYYY-MM-DD] [--note <path>] [--repo <checkout>] [--no-wake] [--no-commit]
        [--allow-unlanded]

A finished row is CLOSED, never deleted: ``delete`` only drops a line (to move a row, with ``append`` in
its new queue), and the row guard refuses a row that left the live queues without an archive line (ADR 0011).
``close`` ARCHIVES the row (RT-QUEUE-ARCHIVE-GRAMMAR, launcher plan
``EterniaLauncher/docs/mission_control/subsystems/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md`` D3–D5): the claim mark
removed, the status replaced by ONE outcome, the line appended to
``<brain>/80 — Archive/Queues/<queue stem>-<YYYY-MM>.md`` (created with its head) and dropped from the queue — both
files in one commit, ``queue(<stem>): close <ID> <outcome>``. Every row of this brain BLOCKED on ``<ID>`` (reason
``hermes`` or ``another lane``) is woken in the same commit: back to ``READY <date>`` with an ``unblocked`` segment
naming the close (``agent_runtime/work_store/wake.py``; launcher row BRAIN-QUEUE-CLOSE-WAKES-DEPENDENTS);
``--no-wake`` leaves them (and says so on stderr: a row left BLOCKED on an archived row reds the queue gate). A row
whose block lists several rows (``— `A` then `B`, `C`: why``) is woken only by the close of the last one still
open; until then a close of one of them re-points it at the rest, ``--no-wake`` or not. Rows in the launcher or backend brains are theirs to wake — the launcher's
``dart tool/queue/waits_on.dart <ID> --in hermes`` lists them.

A close also moves the row's TASK (launcher plan ``EterniaLauncher/docs/mission_control/planned/
QUEUE_TASKS_AND_SUBTASKS_2026-11-09.md`` D3 amended, D7; the launcher's ``tool/queue/close_row.dart``;
``agent_runtime/work_store/tasks.py``), judged with the launcher's and the backend's queues checked out beside this
repository: ``--done`` on a subtask whose task is DEFERRED, a DECISION or BLOCKED on an owner decision of its own is refused, naming the
task (an owner close still goes); the last open subtask's close archives a task in this brain in the same commit
(``DONE <date> <sha> · result: all N subtasks closed``); otherwise the task of the closed row and of every woken row
follows its subtasks — READY with an ``unblocked`` segment once one is startable, ``BLOCKED`` on the first waiting
one when none is (:func:`agent_runtime.work_store.tasks.task_status_after_close`). A task in a sibling brain is that
brain's to move — the close prints what to set there; with a sibling brain not checked out the task is left open. A close that archives a task prints the live rows under
``<slug>-followups`` in every brain read, with one line saying to read them together (nothing when there are none).
``claim`` refuses a subtask whose task holds its subtasks back (``task_not_ready``).

A claim names its place (ADR 0025's 2026-10-26 amendment): ``**TAKEN <date> <lane> on <machine> as
<git account> in <worktree>**``. ``--machine`` defaults to the hostname, ``--account`` to the
checkout's ``git config user.name``, ``--worktree`` to the checkout's folder name; a part that cannot
be read refuses ``invalid`` rather than writing a claim the grammar rejects.

The edit is ``agent_runtime.work_store.grammar.apply`` — the same one-line, by-ID edit the Work
writer makes (plan ``docs/agent-runtime-harness/archive/work-on-markdown-2026-10-18.md`` §5, §6.2):
a session that races the engine re-applies its op here instead of resolving a text conflict.
The row is found across ``*_Brain/20 — Active Initiatives/*.md`` (or ``--note``); the commit is
by pathspec under the session's own git identity and pushed as ``HEAD`` to the branch's upstream, or to
``origin`` ``main`` from a lane branch with none or a detached HEAD.

A push that loses the race for the branch is retried here, by re-applying the op, never by a text merge
(FH-WORK-ROW-CLOSE-CHECKS-SHA-ON-MAIN; four lanes of wave w1112b each lost ~2 min per row to it): fetch the
target, take the op's own commit back off (``reset --soft`` + ``restore`` of its paths only), fast-forward to
the new tip, apply the op again by ID there, commit, push — up to ``PUSH_ATTEMPTS`` times. A claim that lost
to another lane's claim of the same row is then refused ``already_taken``, which is the answer. The retry runs
only when the op's commit is the one thing the checkout has that the remote lacks and no file the checkout
changed is touched by the incoming commits; otherwise the push exits 3 with the hint "fetch, then re-run", as
before, and nothing else is touched. It never runs ``stash``, ``pull``, ``rebase``, ``reset --hard`` or a
merge that is not a fast-forward, and a push that lands the first time runs no ``fetch`` at all.

``close --done <sha>`` / ``--refuted <sha>`` refuses a commit that is not on the push target's branch
(``sha_not_on_main``, "push it first"): a landing chain once hid a rejected push behind a pipe and archived a
row DONE on a commit that never reached ``main``. It reads the checkout's remote-tracking ref and fetches once
before refusing. ``here`` is not checked; ``--allow-unlanded`` is for a commit that lives in another
repository.
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
    RECOMMEND, SEPARATOR, STATUS, Op, OutcomeKind, Row, apply, archive_note_for, archive_note_text, find, is_queue,
    parse_note, parse_outcome, row_defects, split_segments,
)
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.tasks import (
    SIBLING_QUEUE_DIRS, archived_rows, owning_task, parked_task, sibling_rows, siblings_visible, subtasks_of, task_of,
    task_refuses_done, task_status_after_close, write_task_defects,
)
from agent_runtime.work_store.wake import unblocked_segment, wake_dependents

COMMANDS = {"claim": Op.CLAIM, "release": Op.RELEASE, "set-status": Op.SET_STATUS, "delete": Op.DELETE,
            "append": Op.APPEND, "close": Op.CLOSE}
BRAIN_GLOBS = ("*_Brain/20 — Active Initiatives/*.md", "*_brain/20 — Active Initiatives/*.md")
#: What a push that lost the race for the branch says. ``cannot lock ref`` is the remote's own wording when two
#: pushes arrive together (``! [remote rejected] … is at <sha> but expected <sha>``, lived 2026-11-12).
NON_FAST_FORWARD = ("! [rejected]", "fetch first", "non-fast-forward", "cannot lock ref")
#: How many times one op is committed and pushed before a lost race is reported (exit 3).
PUSH_ATTEMPTS = 5
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
    parser.add_argument("--no-wake", action="store_true")
    parser.add_argument("--allow-unlanded", action="store_true")
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


def archive_row(repo: Path, note: Path, text: str, row_id: str, who: str, payload: dict,
                archives: dict[Path, str]) -> tuple[str, Path]:
    """``note``'s text without ``row_id``, and the archive month file its closed line was appended to in
    ``archives`` (path -> text, read from disk the first time a path is met)."""

    row = find(parse_note(text, slot="", note=""), row_id)
    archived = apply(row.raw, Op.CLOSE, who=who, date=date.today().isoformat(), payload=payload)
    outcome = next(o for o in map(parse_outcome, (s.strip() for s in split_segments(archived))) if o is not None)
    archive = repo / archive_note_for(note.relative_to(repo).as_posix(), outcome.date)
    if archive not in archives:
        front = text.split("\n---", 1)[0].split("\n")
        program = next((line.split(":", 1)[1].strip() for line in front if line.startswith("program:")), None)
        archives[archive] = archive.read_bytes().decode("utf-8") if archive.is_file() else archive_note_text(
            note.name, program, outcome.date[:7])
    head = archives[archive]
    archives[archive] = head + ("" if head.endswith("\n") else "\n") + archived + "\n"
    lines = text.split("\n")
    del lines[row.line_no - 1]
    return "\n".join(lines), archive


def _live_rows(texts: dict[Path, str]) -> list[Row]:
    return [row for path, text in texts.items() for row in parse_note(text, slot="hermes", note=str(path))]


def _brains(texts: dict[Path, str], siblings: dict[str, list[Row]]) -> list[Row]:
    """Every live row of this brain (slot ``hermes``) then of each sibling brain read — work order."""

    return _live_rows(texts) + [row for rows in siblings.values() for row in rows]


def refuse_task_defects(repo: Path, written: dict[Path, tuple[str, str]], texts: dict[Path, str],
                        siblings: dict[str, list[Row]]) -> None:
    """Refuse a write whose CHANGED rows break the task rules, naming each defect, before anything is written
    (RT-QUEUE-TASK-RULES-AT-WRITE; :func:`agent_runtime.work_store.tasks.write_task_defects`)."""

    brain = _live_rows({path: text for path, text in texts.items() if path not in written})
    defects = write_task_defects({str(path): pair for path, pair in written.items()}, brain,
                                 [row for rows in siblings.values() for row in rows],
                                 siblings_visible=siblings_visible(siblings))
    if defects:
        shown = [d.replace(f"{repo}/", "", 1) for d in defects]
        raise WorkRefused(Reason.GRAMMAR_INVALID, "the write breaks the task rules: " + "; ".join(shown))


def refuse_claim_of_parked(repo: Path, note: Path, text: str, row_id: str) -> None:
    """A lane claim of a subtask whose task holds its subtasks back (``task_holds_subtasks``: DEFERRED, NEEDS PLAN,
    a DECISION, or BLOCKED on an owner reason of its own) is refused, naming the task (D3); a task no brain read
    here holds lets the claim through."""

    texts = {path: path.read_bytes().decode("utf-8") for path in queue_notes(repo, None)}
    texts[note] = text
    row = find(_live_rows({note: text}), row_id)
    task = parked_task(row, _brains(texts, sibling_rows(repo)))
    if task is not None:
        raise WorkRefused(Reason.TASK_NOT_READY, f"`{row_id}` is a subtask of task `{task.ref.id}` (task: {task.task}, "
                                                 f"{task.ref.slot}), which is {task.status.value if task.status else 'without a status'}"
                                                 ": the task's status holds every subtask back")


def refuse_parked_task(closed: Row, rows: list[Row]) -> None:
    """``--done`` on a subtask whose task the owner parked or owes a decision is refused, naming the task (D3)."""

    task = task_of(closed, rows) if closed.task is None else None
    own = [closed.ref.id, *(s.ref.id for s in subtasks_of(task, rows))] if task is not None else []
    if task is not None and (why := task_refuses_done(task, own)) is not None:
        raise WorkRefused(Reason.TASK_NOT_READY, f"`{closed.ref.id}` is a subtask of task `{task.ref.id}` "
                                                 f"(task: {task.task}, {task.ref.slot}), which is {why} — the task's "
                                                 "status is the owner's decision for every subtask; reopen the task first")


def _rewrite_status(text: str, row_id: str, status: list[str]) -> str:
    """``text`` with ``row_id``'s status segment replaced by ``status``, its earlier ``unblocked`` records dropped
    (a task line keeps only the latest) and the ``Recommend:`` an owner-decision block carried (``status`` brings
    its own when it asks the owner), and every other segment, a claim included, kept."""

    lines = text.split("\n")
    row = find(parse_note(text, slot="", note=""), row_id)
    line = lines[row.line_no - 1]
    carriage = "\r" if line.endswith("\r") else ""
    kept: list[str] = []
    for index, segment in enumerate(split_segments(line.rstrip("\r"))):
        if index and STATUS.match(segment.strip()):
            kept += status
        elif not (index and (segment.strip().startswith("unblocked ") or RECOMMEND.match(segment.strip()))):
            kept.append(segment)
    lines[row.line_no - 1] = SEPARATOR.join(kept) + carriage
    return "\n".join(lines)


def task_step(repo: Path, closed: Row, woken: list[str], texts: dict[Path, str], archives: dict[Path, str],
              payload: dict, siblings: dict[str, list[Row]], who: str, how: str) -> list[str]:
    """After a close: the task of the closed row and of every row it woke, judged from the queues as they now stand
    (the launcher's ``close_row.dart::_taskStep``). D7 archives a task left with no open subtask; otherwise its
    status follows its subtasks (:func:`task_status_after_close`). ``texts`` / ``archives`` are edited in place;
    what was done comes back as lines."""

    rows = _brains(texts, siblings)
    by_id = {row.ref.id: row for row in _live_rows(texts)}
    tasks = {row.task for row in rows if row.task is not None}
    slugs = [owning_task(closed.group, tasks) if closed.group else None]
    slugs += [by_id[row_id].task or (owning_task(by_id[row_id].group, tasks) if by_id[row_id].group else None)
              for row_id in woken if row_id in by_id]
    visible = siblings_visible(siblings)
    said: list[str] = []
    for slug in dict.fromkeys(s for s in slugs if s is not None):
        rows = _brains(texts, siblings)
        task = next((row for row in rows if row.task == slug), None)
        if task is None:
            continue
        subtasks = subtasks_of(task, rows)
        if slug == slugs[0] and not subtasks:
            said += close_task(repo, closed, task, texts, archives, payload, siblings, who)
            continue
        if slug == slugs[0] and all(s.ref.slot != "hermes" for s in subtasks):
            said += [f"task `{task.ref.id}` stays open: `{s.ref.id}` is still open in {s.ref.slot}" for s in subtasks]
        status = task_status_after_close(task, subtasks, all_visible=visible, closed_id=closed.ref.id,
                                         date=payload["date"], unblocked=unblocked_segment(closed.ref.id,
                                                                                           payload["date"], how))
        if status is None:
            continue
        if task.ref.slot != "hermes":
            said.append(f"task `{task.ref.id}` ({task.ref.slot}): set it to `{status[0]}` there")
            continue
        note = Path(task.ref.note)
        texts[note] = _rewrite_status(texts[note], task.ref.id, status)
        said.append(f"task `{task.ref.id}`: {status[0]}")
    return said


def close_task(repo: Path, closed: Row, task: Row, texts: dict[Path, str], archives: dict[Path, str], payload: dict,
               siblings: dict[str, list[Row]], who: str) -> list[str]:
    """D7: archive ``task``, left with no open subtask by ``closed``'s close; what was done, as lines."""

    if not siblings_visible(siblings):
        missing = ", ".join(sorted(set(SIBLING_QUEUE_DIRS) - set(siblings)))
        return [f"task `{task.ref.id}` has no open subtask here, but the {missing} brain is not checked out beside "
                "this repository: left open"]
    if task.ref.slot != "hermes":
        return [f"task `{task.ref.id}` ({task.ref.slot}) has no open subtask left: close it there with its close tool"]
    counted = archived_rows(repo / "Harness_Brain" / "20 — Active Initiatives") + [
        row for text in archives.values() for row in parse_note(text, slot="", note="", archived=True)]
    done = len({row.ref.id for row in subtasks_of(task, counted)} | {closed.ref.id})
    words = f"all {done} subtasks closed"
    by_owner = payload["outcome"] == OutcomeKind.CLOSED
    task_payload = ({"outcome": OutcomeKind.CLOSED.value, "words": words} if by_owner else
                    {"outcome": OutcomeKind.DONE.value, "commit": payload["commit"], "result": words})
    note = Path(task.ref.note)
    texts[note], _ = archive_row(repo, note, texts[note], task.ref.id, who, {**task_payload, "date": payload["date"]},
                                 archives)
    done_as = f"CLOSED {payload['date']}" if by_owner else f"DONE {payload['date']} {payload['commit']}"
    # MUTATION: drop the follow-up lines and test_closing_a_task_lists_its_open_follow_up_rows reddens.
    return [f"closed task `{task.ref.id}` {done_as}: {words}", *follow_up_lines(task, _brains(texts, siblings))]


def follow_up_lines(task: Row, rows: list[Row]) -> list[str]:
    """After ``task`` is archived: the live rows under ``<slug>-followups`` in every brain read, by ID and title,
    under one line saying to read them together — the last moment a defect parked there is in view (launcher row
    QA-TASK-CLOSE-SHOWS-ITS-FOLLOW-UP-ROWS; the words are ``EterniaLauncher/tool/queue/close_row.dart::
    _listFollowUps``'s). A print only: nothing when there are none, and no refusal."""

    slug = f"{task.task}-followups"
    found = [row for row in rows if row.task is None and row.group is not None
             and (row.group == slug or row.group.startswith(slug + "."))]
    if not found:
        return []
    return [f"task `{task.ref.id}` is closed with {len(found)} follow-up row(s) open under `{slug}` — read them "
            "together now: one that is a defect in what this task built goes back into the task, which reopens for it",
            *(f"  `{row.ref.id}` — {row.title} ({row.ref.slot}, {Path(row.ref.note).name})" for row in found)]


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


def push_target(repo: Path, git: Git) -> list[str]:
    """``[<remote>, HEAD:<ref>]``: the branch's upstream when it has one, else ``origin`` ``main``.

    A bare ``git push`` worked only on a branch tracking ``main``. A lane closes from its own
    branch (no upstream: git's "no upstream branch", exit 4) or a detached HEAD, and then pushed
    the close by hand (FH-WORK-ROW-CLOSE-PUSH-FROM-LANE-BRANCH); lanes land with
    ``git push origin HEAD:main`` (CLAUDE.md § Git), so that is the default here too. Read-only
    git only: ``symbolic-ref`` and ``for-each-ref``.
    """

    branch = git(["symbolic-ref", "-q", "HEAD"], repo)
    ref = str(branch.stdout).strip() if branch.returncode == 0 else ""
    if ref.startswith("refs/heads/"):
        upstream = git(["for-each-ref", "--format=%(upstream:remotename)%09%(upstream:remoteref)", ref], repo)
        remote, _, merge = str(upstream.stdout).strip().partition("\t")
        if upstream.returncode == 0 and remote and merge:
            return [remote, f"HEAD:{merge}"]
    return ["origin", "HEAD:main"]


def commit_and_push(repo: Path, note: Path, args: argparse.Namespace, git: Git, *, also: tuple[Path, ...] = (),
                    woken: tuple[Path, ...] = ()) -> int:
    relative = list(dict.fromkeys([note.relative_to(repo).as_posix(), *(path.relative_to(repo).as_posix()
                                                                         for path in (*also, *woken))]))
    if not also:
        subject = f"queue: {COMMANDS[args.command].value} {args.row_id} {args.who}"
    else:
        word = f"DONE {args.done}" if args.done else f"REFUTED {args.refuted}" if args.refuted else "CLOSED by owner"
        subject = f"queue({note.stem}): close {args.row_id} {word}"
    for step in (["add", "--", *relative], ["commit", "-q", "-m", subject, "--", *relative]):
        done = git(step, repo)
        if done.returncode != 0:
            print(f"git {step[0]} failed: {str(done.stderr).strip()[-300:]}", file=sys.stderr)
            return EXIT_GIT_FAILED
    pushed = git(["push", "-q", *push_target(repo, git)], repo)
    if pushed.returncode == 0:
        return 0
    if any(marker in str(pushed.stderr) for marker in NON_FAST_FORWARD):
        return EXIT_NON_FAST_FORWARD
    print(f"git push failed: {str(pushed.stderr).strip()[-300:]}", file=sys.stderr)
    return EXIT_GIT_FAILED


def _apply_close(repo: Path, note: Path, text: str, args, archives: dict[Path, str]) -> list[Path]:
    """Archive *args.row_id*, wake its dependents and step its task; the notes it rewrote."""
    payload = close_payload(args)
    closed = find(parse_note(text, slot="hermes", note=str(note)), args.row_id)
    texts = {path: path.read_bytes().decode("utf-8") for path in queue_notes(repo, None)}
    siblings = sibling_rows(repo)
    if payload["outcome"] == OutcomeKind.DONE:
        refuse_parked_task(closed, _brains(texts, siblings))
    closed_by_owner = payload["outcome"] == OutcomeKind.CLOSED
    how = OutcomeKind.CLOSED.value if closed_by_owner else f"{payload['outcome']} {payload['commit']}"
    before = {**texts, note: text}
    texts[note], _ = archive_row(repo, note, text, args.row_id, args.who, payload, archives)
    woken: dict[Path, list[str]] = {}
    held: dict[str, list[str]] = {}
    stranded: list[str] = []
    live_ids = {row.ref.id for row in _brains(texts, siblings)}
    for path, current in texts.items():
        stepped = wake_dependents(current, args.row_id, payload["date"], how, live_ids=live_ids,
                                  wake=not args.no_wake)
        texts[path] = stepped.text
        held |= stepped.held
        stranded += stepped.stranded
        if stepped.woken:
            woken[path] = stepped.woken
    said = task_step(repo, closed, [i for ids in woken.values() for i in ids], texts, archives, payload,
                     siblings, args.who, how)
    touched = [path for path in texts if texts[path] != before.get(path)]
    refuse_task_defects(repo, {path: (before[path], texts[path]) for path in touched}, texts, siblings)
    # The archives first: a failed write must never lose a row.
    for archive, archive_text in archives.items():
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(archive_text.encode("utf-8"))
    for path in touched:
        path.write_bytes(texts[path].encode("utf-8"))
    for ids in woken.values():
        for woke in ids:
            print(f"woke `{woke}`: READY (it waited on `{args.row_id}`)")
    for row_id, still_open in held.items():
        print(f"`{row_id}` stays BLOCKED: it also waits on {', '.join(f'`{b}`' for b in still_open)}, still open "
              f"(`{args.row_id}` is off its list)")
    for row_id in stranded:
        print(f"warning: `{row_id}` is left BLOCKED on `{args.row_id}`, which this close archives (--no-wake): "
              "re-status it before you push, or the queue gate reds on a blocker that is no longer a row",
              file=sys.stderr)
    for line in said:
        print(line)
    return touched


def _apply_edit(repo: Path, note: Path, text: str, args) -> None:
    """Every operation but close: one row of *note* rewritten in place."""
    if COMMANDS[args.command] is Op.CLAIM:
        refuse_claim_of_parked(repo, note, text, args.row_id)
    new = edited_text(text, args)
    others = {path: path.read_bytes().decode("utf-8") for path in queue_notes(repo, None) if path != note}
    refuse_task_defects(repo, {note: (text, new)}, others, sibling_rows(repo))
    note.write_bytes(new.encode("utf-8"))


def _target_branch(repo: Path, git: Git) -> tuple[str, str]:
    """``(<remote>, <branch>)`` the op is pushed to."""

    remote, target = push_target(repo, git)
    return remote, target.removeprefix("HEAD:").removeprefix("refs/heads/")


def unlanded_sha(repo: Path, args: argparse.Namespace, git: Git) -> str | None:
    """Why ``close --done|--refuted <sha>`` is refused: the commit is not on the branch the close is pushed to.

    ``None`` when it is there (or for ``here``, ``--owner``, ``--allow-unlanded``, any other command). The
    checkout's remote-tracking ref answers; one fetch of the target is tried before refusing, so a commit a
    peer pushed is found.
    """

    sha = args.done or args.refuted
    if COMMANDS[args.command] is not Op.CLOSE or not sha or sha == "here" or args.allow_unlanded:
        return None
    remote, branch = _target_branch(repo, git)

    def landed() -> bool:
        return git(["merge-base", "--is-ancestor", sha, f"{remote}/{branch}"], repo).returncode == 0

    if landed():
        return None
    git(["fetch", "-q", remote, branch], repo)
    if landed():
        return None
    return (f"sha_not_on_main `{sha}` is not on {remote}/{branch}: push it first (--allow-unlanded when the "
            "commit lives in another repository)")


def _names(listing: str) -> set[str]:
    return {name for name in str(listing).split("\0") if name}


def back_onto_remote_tip(repo: Path, git: Git) -> int | None:
    """After a lost push race: take the op's own commit back off and fast-forward to the target's new tip.

    ``None`` when the checkout now stands on the fetched tip with the op undone, ready for it to be applied
    again. ``EXIT_NON_FAST_FORWARD`` when this is not safe to do — the checkout holds other commits the remote
    lacks, or changed a file the incoming commits touch — and nothing was changed. ``EXIT_GIT_FAILED`` when the
    fast-forward itself failed after the op was undone (said on stderr).
    """

    remote, branch = _target_branch(repo, git)
    if git(["fetch", "-q", remote, branch], repo).returncode != 0:
        return EXIT_NON_FAST_FORWARD
    tip = str(git(["rev-parse", "FETCH_HEAD"], repo).stdout).strip()
    if not tip or git(["merge-base", "--is-ancestor", "HEAD~1", tip], repo).returncode != 0:
        return EXIT_NON_FAST_FORWARD
    own = _names(git(["diff", "--name-only", "-z", "HEAD~1", "HEAD"], repo).stdout)
    incoming = _names(git(["diff", "--name-only", "-z", "HEAD~1", tip], repo).stdout)
    if _names(git(["diff", "--name-only", "-z", "HEAD"], repo).stdout) & incoming:
        return EXIT_NON_FAST_FORWARD
    for step in (["reset", "-q", "--soft", "HEAD~1"],
                 ["restore", "-q", "--staged", "--worktree", "--source=HEAD", "--", *sorted(own)],
                 ["merge", "-q", "--ff-only", tip]):
        done = git(step, repo)
        if done.returncode != 0:
            print(f"git {step[0]} failed while retrying the push: {str(done.stderr).strip()[-300:]} — the row "
                  "operation is not committed here; re-run it", file=sys.stderr)
            return EXIT_GIT_FAILED
    return None


def _apply_and_push(repo: Path, args: argparse.Namespace, git: Git) -> int:
    """One attempt: apply the op to the checkout as it stands, commit it by pathspec, push it."""

    archives: dict[Path, str] = {}
    touched: list[Path] = []
    try:
        note, text = _note_and_text(repo, args)
        if COMMANDS[args.command] is Op.CLOSE:
            touched = _apply_close(repo, note, text, args, archives)
        else:
            _apply_edit(repo, note, text, args)
    except WorkRefused as refusal:
        print(f"refused: {refusal.reason.value} {refusal.detail}".rstrip(), file=sys.stderr)
        return EXIT_REFUSED
    if args.no_commit:
        return 0
    return commit_and_push(repo, note, args, git, also=tuple(archives), woken=tuple(touched))


def main(argv: list[str] | None = None, *, git: Git = run_git) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = Path(args.repo).resolve()
    unlanded = unlanded_sha(repo, args, git)
    if unlanded is not None:
        print(f"refused: {unlanded}", file=sys.stderr)
        return EXIT_REFUSED
    code = _apply_and_push(repo, args, git)
    for _ in range(PUSH_ATTEMPTS - 1):
        if code != EXIT_NON_FAST_FORWARD:
            return code
        # MUTATION: return here (no retry) and test_a_lost_push_race_is_retried_on_the_new_tip reddens.
        undone = back_onto_remote_tip(repo, git)
        if undone is not None:
            code = undone
            break
        code = _apply_and_push(repo, args, git)
    if code == EXIT_NON_FAST_FORWARD:
        print("push rejected (non-fast-forward): fetch, then re-run", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
