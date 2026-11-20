"""What one close does to a brain: the row archived, the rows waiting on it woken, and its task stepped.

The ONE function every close of a hermes-written brain runs (row
RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE, review w1118a.48 D1b): a lane's
``scripts/work_row.py close`` and the Work writer's ``Op.CLOSE`` (``runtime.work.close``, the owner's close from
Eternia's board; ``runtime.work.done``, an agent's; the Work engine's ``_done``) each call
:func:`close_and_step`, so the board's close and a lane's close leave the queues alike. The launcher's twin is
``EterniaLauncher/tool/queue/close_row.dart`` (``_close`` then ``_taskStep``).

Pure over texts: the caller reads every live queue note of the brain into ``texts`` (path -> text), and writes
back what :class:`Closed` hands it — the archive month files first, then the notes that changed. The month files
already on disk are read here, the first time a path is met, as the archived-subtask count is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .grammar import (
    RECOMMEND, SEPARATOR, STATUS, Op, OutcomeKind, Row, apply, archive_note_for, archive_note_text, find, parse_note,
    parse_outcome, split_segments,
)
from .tasks import (
    SIBLING_QUEUE_DIRS, archived_rows, owning_task, siblings_visible, subtasks_of, task_status_after_close,
)
from .wake import OWN_BRAIN, unblocked_segment, wake_dependents

__layer__ = "policy"
__all__ = ["THREE_BRAINS", "Closed", "archive_row", "brain_siblings", "brains", "close_and_step", "follow_up_lines",
           "live_rows"]

#: The brain folders of the three repositories, whose tasks may hold subtasks in one another: hermes's own and
#: each sibling's (:data:`agent_runtime.work_store.tasks.SIBLING_QUEUE_DIRS`).
THREE_BRAINS = {"hermes": "Harness_Brain",
                **{brain: relative.split("/")[1] for brain, relative in SIBLING_QUEUE_DIRS.items()}}


@dataclass
class Closed:
    """What :func:`close_and_step` did: every note's text after it, and the lines a caller may print."""

    #: Every live queue note read, after the close (only the ones it touched differ from what was read).
    texts: dict[Path, str]
    #: Each archive month file the close appended to -> its whole new text.
    archives: dict[Path, str]
    #: The rows woken back to READY, by the note that holds them.
    woken: dict[Path, list[str]] = field(default_factory=dict)
    #: The rows still BLOCKED, re-pointed: ID -> the rows of their list still open.
    held: dict[str, list[str]] = field(default_factory=dict)
    #: The rows left BLOCKED on the closed row (``wake=False``).
    stranded: list[str] = field(default_factory=list)
    #: What the task step did, as lines (a task moved, archived, or left for its own brain).
    said: list[str] = field(default_factory=list)


def live_rows(texts: dict[Path, str]) -> list[Row]:
    return [row for path, text in texts.items() for row in parse_note(text, slot=OWN_BRAIN, note=str(path))]


def brains(texts: dict[Path, str], siblings: dict[str, list[Row]]) -> list[Row]:
    """Every live row of this brain (slot ``hermes``) then of each sibling brain read — work order."""

    return live_rows(texts) + [row for rows in siblings.values() for row in rows]


def brain_siblings(brain_folder: str, siblings: dict[str, list[Row]]) -> tuple[dict[str, list[Row]], bool]:
    """The sibling brains a close in the brain ``brain_folder`` (``<X>_Brain``, the board's) reads, and whether every
    brain its tasks may span was read — for a writer that closes rows of ANY brain, not only hermes's.

    - A brain outside :data:`THREE_BRAINS` (a workspace's own Work brain, a user's repo) shares no task with them:
      no sibling is read, and its tasks are judged on its own rows (visible).
    - One of the three reads the others found beside the checkout (:func:`agent_runtime.work_store.tasks.
      sibling_rows` finds the launcher's and the backend's): the sibling copy of ITSELF is dropped (its rows are
      this close's own notes, before the close), and it is fully read only when each other brain was — hermes's is
      never a sibling, so a close in the launcher's or the backend's brain leaves its tasks judged not fully read.
    """

    own = next((brain for brain, folder in THREE_BRAINS.items() if folder == brain_folder), None)
    if own is None:
        return {}, True
    # MUTATION: keep the brain's own sibling copy and test_a_close_in_the_launcher_brain_reads_itself_once reds.
    kept = {brain: rows for brain, rows in siblings.items() if brain != own}
    return kept, all(brain in kept for brain in THREE_BRAINS if brain != own)


def _program(text: str) -> str | None:
    front = text.split("\n---", 1)[0].split("\n")
    return next((line.split(":", 1)[1].strip() for line in front if line.startswith("program:")), None)


def archive_row(repo: Path, note: Path, text: str, row_id: str, who: str, payload: dict, archives: dict[Path, str],
                *, today: str) -> tuple[str, Path]:
    """``note``'s text without ``row_id``, and the archive month file its closed line was appended to in
    ``archives`` (path -> text, read from disk the first time a path is met). ``today`` dates an outcome the
    payload leaves undated."""

    row = find(parse_note(text, slot="", note=""), row_id)
    archived = apply(row.raw, Op.CLOSE, who=who, date=today, payload=payload)
    outcome = next(o for o in map(parse_outcome, (s.strip() for s in split_segments(archived))) if o is not None)
    archive = repo / archive_note_for(note.relative_to(repo).as_posix(), outcome.date)
    if archive not in archives:
        archives[archive] = archive.read_bytes().decode("utf-8") if archive.is_file() else archive_note_text(
            note.name, _program(text), outcome.date[:7])
    head = archives[archive]
    archives[archive] = head + ("" if head.endswith("\n") else "\n") + archived + "\n"
    lines = text.split("\n")
    del lines[row.line_no - 1]
    return "\n".join(lines), archive


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


def follow_up_lines(task: Row, rows: list[Row]) -> list[str]:
    """After ``task`` is archived: its live follow-up rows in every brain read, by ID and title, under one line
    saying to read them together — the last moment a defect parked there is in view (launcher row
    QA-TASK-CLOSE-SHOWS-ITS-FOLLOW-UP-ROWS; the words are ``EterniaLauncher/tool/queue/close_row.dart::
    _listFollowUps``'s). A follow-up row is one carrying `` · from: `<task ID>` `` under its domain's standing
    follow-ups task (owner 2026-11-15, "yea do the cleanup": one follow-ups task per domain queue), or one still
    under a per-task ``<slug>-followups``. A print only: nothing when there are none, and no refusal. The Windows box
    and the teammate close rows with this same tool."""

    slug = f"{task.task}-followups"
    mark = f" · from: `{task.ref.id}`"
    # MUTATION: drop the ``mark`` arm and test_closing_a_task_lists_the_rows_that_name_it_in_a_from_segment reddens.
    found = [row for row in rows if row.task is None and (
        (row.group is not None and (row.group == slug or row.group.startswith(slug + "."))) or mark in row.raw)]
    if not found:
        return []
    return [f"task `{task.ref.id}` is closed with {len(found)} follow-up row(s) open (`from: {task.ref.id}`, or under "
            f"`{slug}`) — read them together now: one that is a defect in what this task built goes back into the "
            "task, which reopens for it",
            *(f"  `{row.ref.id}` — {row.title} ({row.ref.slot}, {Path(row.ref.note).name})" for row in found)]


def _close_task(repo: Path, queue_dir: Path, closed: Row, task: Row, texts: dict[Path, str],
                archives: dict[Path, str], payload: dict, siblings: dict[str, list[Row]], who: str, *, visible: bool,
                today: str) -> list[str]:
    """D7: archive ``task``, left with no open subtask by ``closed``'s close; what was done, as lines."""

    if not visible:
        missing = ", ".join(sorted(set(SIBLING_QUEUE_DIRS) - set(siblings)))
        return [f"task `{task.ref.id}` has no open subtask here, but the {missing} brain is not checked out beside "
                "this repository: left open"]
    if task.ref.slot != OWN_BRAIN:
        return [f"task `{task.ref.id}` ({task.ref.slot}) has no open subtask left: close it there with its close tool"]
    counted = archived_rows(queue_dir) + [
        row for text in archives.values() for row in parse_note(text, slot="", note="", archived=True)]
    done = len({row.ref.id for row in subtasks_of(task, counted)} | {closed.ref.id})
    words = f"all {done} subtasks closed"
    by_owner = payload["outcome"] == OutcomeKind.CLOSED
    task_payload = ({"outcome": OutcomeKind.CLOSED.value, "words": words} if by_owner else
                    {"outcome": OutcomeKind.DONE.value, "commit": payload["commit"], "result": words})
    note = Path(task.ref.note)
    texts[note], _ = archive_row(repo, note, texts[note], task.ref.id, who, {**task_payload, "date": payload["date"]},
                                 archives, today=today)
    done_as = f"CLOSED {payload['date']}" if by_owner else f"DONE {payload['date']} {payload['commit']}"
    # MUTATION: drop the follow-up lines and test_closing_a_task_lists_its_open_follow_up_rows reddens.
    return [f"closed task `{task.ref.id}` {done_as}: {words}", *follow_up_lines(task, brains(texts, siblings))]


def _task_step(repo: Path, queue_dir: Path, closed: Row, woken: list[str], texts: dict[Path, str],
               archives: dict[Path, str], payload: dict, siblings: dict[str, list[Row]], who: str, how: str, *,
               visible: bool, today: str) -> list[str]:
    """After a close: the task of the closed row and of every row it woke, judged from the queues as they now stand
    (the launcher's ``close_row.dart::_taskStep``). D7 archives a task left with no open subtask; otherwise its
    status follows its subtasks (:func:`task_status_after_close`). ``texts`` / ``archives`` are edited in place;
    what was done comes back as lines."""

    rows = brains(texts, siblings)
    by_id = {row.ref.id: row for row in live_rows(texts)}
    tasks = {row.task for row in rows if row.task is not None}
    slugs = [owning_task(closed.group, tasks) if closed.group else None]
    slugs += [by_id[row_id].task or (owning_task(by_id[row_id].group, tasks) if by_id[row_id].group else None)
              for row_id in woken if row_id in by_id]
    said: list[str] = []
    for slug in dict.fromkeys(s for s in slugs if s is not None):
        rows = brains(texts, siblings)
        task = next((row for row in rows if row.task == slug), None)
        if task is None:
            continue
        subtasks = subtasks_of(task, rows)
        if slug == slugs[0] and not subtasks:
            said += _close_task(repo, queue_dir, closed, task, texts, archives, payload, siblings, who,
                                visible=visible, today=today)
            continue
        if slug == slugs[0] and all(s.ref.slot != OWN_BRAIN for s in subtasks):
            said += [f"task `{task.ref.id}` stays open: `{s.ref.id}` is still open in {s.ref.slot}" for s in subtasks]
        status = task_status_after_close(task, subtasks, all_visible=visible, closed_id=closed.ref.id,
                                         date=payload["date"], unblocked=unblocked_segment(closed.ref.id,
                                                                                           payload["date"], how))
        if status is None:
            continue
        if task.ref.slot != OWN_BRAIN:
            said.append(f"task `{task.ref.id}` ({task.ref.slot}): set it to `{status[0]}` there")
            continue
        note = Path(task.ref.note)
        texts[note] = _rewrite_status(texts[note], task.ref.id, status)
        said.append(f"task `{task.ref.id}`: {status[0]}")
    return said


def close_and_step(repo: Path, note: Path, texts: dict[Path, str], row_id: str, who: str, payload: dict,
                   siblings: dict[str, list[Row]], *, today: str, wake: bool = True,
                   visible: bool | None = None) -> Closed:
    """Close ``row_id`` of ``note`` (a key of ``texts``, every live queue note of this brain under ``repo``): its
    line archived with ``payload``'s outcome (``Op.CLOSE``), every row of this brain BLOCKED on it woken or
    re-pointed (:func:`agent_runtime.work_store.wake.wake_dependents`; ``wake=False`` leaves them, ``stranded``),
    then the task of the closed row and of every woken row stepped (D3 amended, D7). ``siblings`` are the sibling
    brains' live rows (:func:`agent_runtime.work_store.tasks.sibling_rows`): a task in one is that brain's to move.
    ``visible`` says whether every brain a task's subtasks may live in was read (default: both siblings were,
    :func:`agent_runtime.work_store.tasks.siblings_visible`; :func:`brain_siblings` for a brain that is not
    hermes's) — a task is archived, or BLOCKED on its waiting subtasks, only then. ``payload`` gets its ``date`` from
    ``today`` when it has none. ``texts`` is copied, never edited."""

    payload = {**payload, "date": payload.get("date") or today}
    texts = dict(texts)
    archives: dict[Path, str] = {}
    closed = find(parse_note(texts[note], slot=OWN_BRAIN, note=str(note)), row_id)
    closed_by_owner = payload["outcome"] == OutcomeKind.CLOSED
    how = OutcomeKind.CLOSED.value if closed_by_owner else f"{payload['outcome']} {payload['commit']}"
    texts[note], _ = archive_row(repo, note, texts[note], row_id, who, payload, archives, today=today)
    done = Closed(texts, archives)
    live_ids = {row.ref.id for row in brains(texts, siblings)}
    own_live_ids = {row.ref.id for row in live_rows(texts)}
    for path, current in texts.items():
        stepped = wake_dependents(current, row_id, payload["date"], how, live_ids=live_ids,
                                  own_live_ids=own_live_ids, wake=wake)
        texts[path] = stepped.text
        done.held |= stepped.held
        done.stranded += stepped.stranded
        if stepped.woken:
            done.woken[path] = stepped.woken
    visible = siblings_visible(siblings) if visible is None else visible
    # MUTATION: skip the task step and test_an_owner_close_from_the_board_steps_its_task_and_wakes_its_waiter reds.
    done.said = _task_step(repo, note.parent, closed, [i for ids in done.woken.values() for i in ids], texts,
                           archives, payload, siblings, who, how, visible=visible, today=today)
    return done
