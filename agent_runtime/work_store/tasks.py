"""Tasks and subtasks across the three brains — the hermes twin of the launcher's ``taskDefects``.

Launcher plan ``EterniaLauncher/docs/mission_control/subsystems/QUEUE_TASKS_AND_SUBTASKS_2026-11-09.md`` D1–D4, D7
(reference: ``EterniaLauncher/tool/queue/queue_grammar.dart``). A row with ``task: <slug>`` is the TASK of that
slug (:attr:`grammar.Row.task`); a row with ``group: <slug>`` is a SUBTASK of the task that owns the slug — its own
slug or a dotted prefix of it (a task owns ``<slug>`` and every ``<slug>.<sub>``). One task per slug across the
brains; every row is a task or a subtask. The checks across brains run only where the siblings are visible:
:func:`sibling_rows` reads the launcher's and the backend's live queues checked out beside this repository.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path

from .grammar import (ARCHIVE_DIR, OWNER_DECISION, STARTABLE, Row, Status, asks_owner, blocked_reason, is_queue,
                      is_queue_archive, parse_note)

__layer__ = "policy"

#: The longest title a task row may carry (D4).
TASK_TITLE_LIMIT = 100
#: Each sibling brain's live queue directory, relative to the directory holding the three checkouts.
SIBLING_QUEUE_DIRS = {
    "launcher": "EterniaLauncher/Launcher_Brain/20 — Active Initiatives",
    "backend": "eternia-backend/EterniaBackend_brain/20 — Active Initiatives",
}
#: Extra directories that may hold the checkouts (``:``-separated; ``;`` on Windows), the launcher's variable.
WORKSPACE_ROOTS_ENV = "ETERNIA_WORKSPACE_ROOTS"

_TITLE_ROW_ID = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", re.ASCII)
_TITLE_PATH = re.compile(r"[\w.-]*\w/[\w./-]*\w", re.ASCII)
_LEAD_ID = re.compile(r"^\s*`[^`]+`\s*(?:—|–|-|:)?\s*")


def _raw_title(raw: str) -> str:
    """The row's bold lead as written, its ID code span and separator cut off."""

    start = raw.find("**")
    if start == -1:
        return raw
    end = raw.find("**", start + 2)
    return _LEAD_ID.sub("", raw[start + 2:end if end != -1 else len(raw)], count=1)


def task_title_problem(row: Row) -> str | None:
    """Why a task row's title breaks D4 — a code span, a path, a row ID, or over :data:`TASK_TITLE_LIMIT` — or None."""

    title = _raw_title(row.raw)
    if "`" in title:
        return "a code span"
    if _TITLE_PATH.search(title):
        return "a path"
    if _TITLE_ROW_ID.search(title):
        return "a row ID"
    if len(row.title) > TASK_TITLE_LIMIT:
        return f"{len(row.title)} characters, over {TASK_TITLE_LIMIT}"
    return None


def owning_task(group: str, tasks: Iterable[str]) -> str | None:
    """The task slug that owns ``group``: the slug itself, else its longest dotted prefix in ``tasks``; else None."""

    known = set(tasks)
    slug = group
    while True:
        if slug in known:
            return slug
        if "." not in slug:
            return None
        slug = slug.rsplit(".", 1)[0]


def task_defects(rows: Iterable[Row], siblings: Iterable[Row], *, siblings_visible: bool) -> list[str]:
    """``<note>:<line>  <ID>  (DEFECT: …)`` for each of ``rows`` (this brain's live rows) breaking the task rules,
    read against ``siblings`` (the visible sibling brains' live rows):

    - ``TWO TASKS`` — a task row whose slug another visible task row also names;
    - ``GROUP HAS NO TASK`` — a ``group:`` no visible brain has a task for (judged only when ``siblings_visible``);
    - ``ROW HAS NO TASK`` — a row with neither ``task:`` nor ``group:``;
    - ``TASK TITLE`` — a task row whose title holds a code span, a path, a row ID, or runs over 100 characters.
    """

    rows = list(rows)
    count: dict[str, int] = {}
    for row in [*rows, *siblings]:
        if row.task is not None:
            count[row.task] = count.get(row.task, 0) + 1
    defects: list[str] = []
    for row in rows:
        at = f"{row.ref.note}:{row.line_no}  {row.ref.id}"
        if row.task is not None:
            if count[row.task] > 1:
                defects.append(f"{at}  (TWO TASKS: `task: {row.task}` is named by {count[row.task]} task rows "
                               "across the visible brains)")
            if (why := task_title_problem(row)) is not None:
                defects.append(f"{at}  (TASK TITLE: {why} — a task title is plain English)")
        elif row.group is not None:
            if siblings_visible and owning_task(row.group, count) is None:
                defects.append(f"{at}  (GROUP HAS NO TASK: no brain has `task: {row.group}` or a task for a "
                               "dotted prefix of it)")
        else:
            defects.append(f"{at}  (ROW HAS NO TASK: file it under an existing task (`group: <slug>`) or as a task)")
    return defects


def task_of(row: Row, candidates: Iterable[Row]) -> Row | None:
    """The task row ``row`` (a subtask) belongs to among ``candidates``, or None (no group, or no task visible)."""

    if row.group is None:
        return None
    tasks = {candidate.task: candidate for candidate in candidates if candidate.task is not None}
    slug = owning_task(row.group, tasks)
    return tasks[slug] if slug is not None else None


def subtasks_of(task: Row, rows: Iterable[Row]) -> list[Row]:
    """The rows of ``rows`` whose group ``task`` owns — the nearest task wins, so a nested task keeps its own."""

    rows = list(rows)
    tasks = {row.task for row in rows if row.task is not None} | {task.task}
    return [row for row in rows if row.task is None and row.group is not None
            and owning_task(row.group, tasks) == task.task]


# ── the sibling brains ───────────────────────────────────────────────────────


def workspace_roots(repo: Path, environ: Mapping[str, str] | None = None) -> list[Path]:
    """Where the sibling checkouts may sit: beside ``repo``, each :data:`WORKSPACE_ROOTS_ENV` entry, and — when
    ``repo`` is a linked worktree (its ``.git`` a ``gitdir:`` file) — beside its primary checkout."""

    repo = repo.resolve()
    roots = [repo.parent]
    extra = (os.environ if environ is None else environ).get(WORKSPACE_ROOTS_ENV, "")
    roots += [Path(part.strip()) for part in extra.split(";" if os.name == "nt" else ":") if part.strip()]
    dot_git = repo / ".git"
    if dot_git.is_file():
        line = dot_git.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir:"):
            git_dir = Path(line[len("gitdir:"):].strip())
            git_dir = git_dir if git_dir.is_absolute() else (repo / git_dir).resolve()
            roots.append(git_dir.parents[3])  # <primary>/.git/worktrees/<name>
    return list(dict.fromkeys(roots))


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, check=False)


def _origin_texts(repo: Path, queue_dir: str) -> dict[str, str] | None:
    """The queue notes at the checkout's ``origin/main`` when it is AHEAD of or diverged from ``HEAD``, else None.

    A sibling is usually its primary checkout, fetched but never pulled, so its working tree can lag rows filed
    minutes ago (the launcher's BRAIN-GRAMMAR-STALE-SIBLING-PRIMARY)."""

    head, origin = (_git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") for ref in ("HEAD", "origin/main"))
    if head.returncode or origin.returncode or head.stdout == origin.stdout:
        return None
    if _git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode == 0:
        return None  # HEAD is ahead: the working tree is the newer
    listing = _git(repo, "ls-tree", "-z", "--name-only", "origin/main", "--", f"{queue_dir}/")
    if listing.returncode:
        return None
    texts = {}
    for path in (p for p in listing.stdout.split("\0") if p.endswith(".md")):
        shown = _git(repo, "cat-file", "blob", f"origin/main:{path}")
        if shown.returncode == 0:
            texts[path.rsplit("/", 1)[-1]] = shown.stdout
    return texts


def _queue_rows(texts: Mapping[str, str], slot: str) -> dict[str, Row]:
    return {row.ref.id: row for name, text in sorted(texts.items()) if is_queue(text)
            for row in parse_note(text, slot=slot, note=name)}


def sibling_rows(repo: Path, environ: Mapping[str, str] | None = None) -> dict[str, list[Row]]:
    """The live rows of each sibling brain checked out beside ``repo``, by brain (``launcher`` / ``backend``); a
    brain not found is left out. Read from the working tree joined with ``origin/main``'s rows (a row either holds
    is known; the ``origin/main`` copy wins)."""

    found: dict[str, list[Row]] = {}
    for root in workspace_roots(repo, environ):
        for brain, relative in SIBLING_QUEUE_DIRS.items():
            directory = root / relative
            if brain in found or not directory.is_dir():
                continue
            checkout = root / relative.split("/", 1)[0]
            working = {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md"))}
            rows = _queue_rows(working, brain)
            remote = _origin_texts(checkout, relative.split("/", 1)[1])
            if remote is not None:
                rows.update(_queue_rows(remote, brain))
            found[brain] = list(rows.values())
    return found


def siblings_visible(found: Mapping[str, list[Row]]) -> bool:
    return all(brain in found for brain in SIBLING_QUEUE_DIRS)


def archived_rows(brain_queue_dir: Path) -> list[Row]:
    """Every row of the ``type: queue-archive`` notes beside ``brain_queue_dir`` (``<brain>/80 — Archive/Queues``)."""

    archive = brain_queue_dir.parent / ARCHIVE_DIR
    return [row for path in sorted(archive.glob("*.md")) if is_queue_archive(text := path.read_text(encoding="utf-8"))
            for row in parse_note(text, slot="", note=path.name, archived=True)] if archive.is_dir() else []


# ── the doors (RT-QUEUE-TASKS-DOORS; launcher ``tool/queue/queue_wake.dart`` at 41b1ed9d4f) ──────────

#: The BLOCKED reasons that wait on the owner (the launcher's ``WorkQueueBlockedReason.needsOwner``).
OWNER_REASONS = (OWNER_DECISION, "owner sitting")
_BLOCKER_ID = re.compile(r"`([A-Z0-9][A-Z0-9._-]*)`")


def _reason(row: Row) -> str | None:
    return blocked_reason(row.status_body) if row.status is Status.BLOCKED else None


def _waits_on_owner(row: Row) -> bool:
    """Whether ``row`` waits on the owner: a ``DECISION``, or ``BLOCKED`` on an owner reason."""

    return row.status is Status.DECISION or _reason(row) in OWNER_REASONS


def blocked_on_id(row: Row) -> str | None:
    """The row ID a BLOCKED row names first after its `` — ``, whatever its reason; else None."""

    if row.status is not Status.BLOCKED or " — " not in row.status_body:
        return None
    match = _BLOCKER_ID.match(row.status_body.split(" — ", 1)[1].strip())
    return match.group(1) if match else None


def parked_task(row: Row, candidates: Iterable[Row]) -> Row | None:
    """The task of subtask ``row`` among ``candidates`` when it is not READY (the claim doors refuse then); None for
    a row that is not a subtask, a task no candidate holds, or a READY task."""

    task = task_of(row, candidates) if row.task is None else None
    return task if task is not None and task.status is not Status.READY else None


def task_refuses_done(task: Row, subtask_ids: Iterable[str] = ()) -> str | None:
    """Why a DONE close of a subtask of ``task`` must not go: the owner parked it (DEFERRED) or owes it a decision
    (DECISION, or BLOCKED owner decision). None when the close may go ahead (the launcher's ``taskRefusesDone``) —
    as it may under a task BLOCKED on a decision one of its own subtasks (``subtask_ids``) carries: that block only
    reports that every subtask waited (:func:`task_status_after_close`), it is not the owner's hold on the task."""

    if task.status is Status.BLOCKED and blocked_on_id(task) in set(subtask_ids):
        return None
    if task.status is Status.DEFERRED:
        return f"DEFERRED {task.status_date}"
    if task.status is Status.DECISION:
        return f"DECISION {task.status_date}"
    if asks_owner(task.status, task.status_body):
        return f"BLOCKED {task.status_date}: owner decision"
    return None


def task_status_after_close(task: Row, subtasks: list[Row], *, all_visible: bool, closed_id: str, date: str,
                            unblocked: str) -> list[str] | None:
    """The status segments ``task`` should carry once ``closed_id`` closed, judged from its live ``subtasks`` (in
    work order, each with its brain in ``ref.slot``), or None to leave it (the launcher's ``taskStatusAfterClose``):

    - a BLOCKED task with a startable subtask (READY, NEEDS PLAN or LIVE CHECK) turns READY with ``unblocked`` — unless the owner blocked it
      on a decision of their own (an owner reason naming none of its subtasks);
    - a READY task, or one BLOCKED on one of its own subtasks, with none startable turns ``BLOCKED <date>: <brain> —
      `<first waiting subtask>` …`` (``another lane`` for its own brain) — judged only when ``all_visible``;
    - a DECISION subtask waits, on the owner: a task whose first waiting subtask is one reads ``BLOCKED <date>:
      owner decision — `<that subtask>` …``, with the ``Recommend:`` segment the grammar asks of that reason;
    - DEFERRED, NEEDS PLAN, LIVE CHECK and DECISION tasks never change, and a DEFERRED subtask is neither startable
      nor waiting.
    """

    live = [s for s in subtasks if s.status is not Status.DEFERRED]
    startable = any(s.status in STARTABLE for s in live)
    on_own = task.status is Status.BLOCKED and blocked_on_id(task) in {closed_id, *(s.ref.id for s in subtasks)}
    if task.status is Status.BLOCKED and startable:
        if _waits_on_owner(task) and not on_own:
            return None
        return [f"READY {date}", unblocked]
    if startable or not all_visible:
        return None
    if task.status is not Status.READY and not on_own:
        return None
    waiting = [s for s in live if s.status in (Status.BLOCKED, Status.DECISION) and s.ref.id]
    if not waiting:
        return None
    owner = sum(1 for s in waiting if _waits_on_owner(s))
    mix = ", ".join(part for part in (f"{owner} on the owner" if owner else "",
                                      f"{len(waiting) - owner} on other work" if len(waiting) > owner else "") if part)
    first = waiting[0]
    asks = first.status is Status.DECISION
    reason = OWNER_DECISION if asks else "another lane" if first.ref.slot == task.ref.slot else first.ref.slot
    block = (f"BLOCKED {date}: {reason} — `{first.ref.id}` every live subtask waits ({mix}); the task turns READY "
             "when one of them does")
    if block in task.segments:
        return None
    return [block, f"Recommend: answer `{first.ref.id}`"] if asks else [block]


# ── the rules where rows are written (RT-QUEUE-TASK-RULES-AT-WRITE; launcher tool/queue/queue_write_check.dart) ──


def write_task_defects(written: Mapping[str, tuple[str, str]], brain: Iterable[Row], siblings: Iterable[Row], *,
                       siblings_visible: bool) -> list[str]:
    """The task defects of the rows a write CHANGES — ``BAD TASK`` and :func:`task_defects` — or ``[]`` when it may
    land. ``written`` maps each queue note the write touches to ``(prior text, new text)``; a row whose exact line is
    in the prior text is unchanged, so a defect the note already carried is never refused here (the vault lint's
    business). ``brain`` is the live rows of this brain's notes the write leaves alone; ``siblings`` the sibling
    brains' (``GROUP HAS NO TASK`` is judged only when ``siblings_visible``). A brain none of whose live rows is a
    task (a workspace's own Work brain) does not use tasks, and is held to none of these rules."""

    changed: list[Row] = []
    unchanged: list[Row] = []
    for note, (prior, new) in written.items():
        if not is_queue(new):
            continue
        before = {line.rstrip("\r") for line in prior.split("\n")}
        for row in parse_note(new, slot="hermes", note=note):
            (unchanged if row.raw in before else changed).append(row)
    others = [*unchanged, *brain]
    if not changed or not any(row.task is not None for row in [*changed, *others]):
        return []
    bad = [f"{row.ref.note}:{row.line_no}  {row.ref.id}  ({defect})" for row in changed for defect in row.defects
           if defect.startswith("BAD TASK")]
    return bad + task_defects(changed, [*others, *siblings], siblings_visible=siblings_visible)
