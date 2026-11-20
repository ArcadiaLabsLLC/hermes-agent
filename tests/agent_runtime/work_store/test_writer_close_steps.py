"""A close the Work writer lands steps the queue as a lane's close does: the rows waiting on the closed row wake and
its task moves, in the same commit (RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE,
review w1118a.48 D1b). The owner's close from Eternia's board (``runtime.work.close``), an agent's
``runtime.work.done`` and the engine's done are each one ``Op.CLOSE`` through :class:`Writer`; the writer and
``scripts/work_row.py close`` share :func:`agent_runtime.work_store.close_step.close_and_step`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.work_store.board import boards
from agent_runtime.work_store.close_step import brain_siblings
from agent_runtime.work_store.grammar import Op, RowRef, parse_note
from agent_runtime.work_store.tasks import SIBLING_QUEUE_DIRS
from agent_runtime.work_store.writer import RowOp, Writer

from work_store_support import bind_here, declare_slots, slot_decl

NOTE = "Harness_Brain/20 — Active Initiatives/q.md"
ARCHIVE = "Harness_Brain/80 — Archive/Queues/q-2026-11.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
#: BLOCKED on its own waiting subtask, not on RT-A: only the task step (never the wake) can move it.
TASK = ("- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-18: another lane — `RT-W` every live subtask "
        "waits; the task turns READY when one of them does")
ROWS = (f"{TASK}\n"
        "- **`RT-A` — first slice** · group: p · READY 2026-11-18\n"
        "- **`RT-W` — waits on the first** · group: p · BLOCKED 2026-11-18: another lane — `RT-A`: needs it\n")
ID = ("-c", "user.name=Test Session", "-c", "user.email=session@test.invalid")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def _seed(tmp_path: Path, workspace: str, rows: str) -> SimpleNamespace:
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / NOTE).parent.mkdir(parents=True)
    (seed / NOTE).write_text(HEAD + rows, encoding="utf-8", newline="\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=clone)
    board = next(b for b in boards(workspace) if b.slot == "hermes")
    return SimpleNamespace(origin=origin, seed=seed, board=board)


@pytest.fixture
def repo(tmp_path: Path, workspace: str, monkeypatch) -> SimpleNamespace:
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)  # never this box's real sibling queues
    return _seed(tmp_path, workspace, ROWS)


def _siblings_beside(tmp_path: Path) -> None:
    """The launcher's and the backend's brains checked out beside the clone, each a queue holding no row of task p."""

    for relative in SIBLING_QUEUE_DIRS.values():
        directory = tmp_path / relative
        directory.mkdir(parents=True)
        (directory / "q.md").write_text(HEAD, encoding="utf-8", newline="\n")


def _close(row_id: str, rid: str, **payload) -> RowOp:
    return RowOp(RowRef("hermes", NOTE, row_id), Op.CLOSE, "operator", rid, payload)


def _at_origin(repo: SimpleNamespace, path: str) -> str:
    git("pull", "-q", "--ff-only", cwd=repo.seed)
    target = repo.seed / path
    return target.read_text(encoding="utf-8") if target.is_file() else ""


def _changed(repo: SimpleNamespace, commit: str) -> set[str]:
    listing = git("-c", "core.quotePath=false", "show", "--name-only", "--format=", commit, cwd=repo.origin)
    return set(filter(None, listing.split("\n")))


def test_an_owner_close_from_the_board_steps_its_task_and_wakes_its_waiter(repo):
    """``runtime.work.close``'s write: RT-A archived, RT-W (BLOCKED on it) READY with the ``unblocked`` record, and
    TASK-P (BLOCKED on RT-W, its own subtask) READY because RT-W is startable — one commit, the note and the month file.
    KILLING MUTATION: skip the task step in ``close_and_step`` -> TASK-P stays BLOCKED, red; and before the fix
    (``Writer._close`` archiving only) RT-W stayed BLOCKED on an archived row, red."""

    receipt = Writer(repo.board, machine_id="m1").apply(
        _close("RT-A", "c1", outcome="CLOSED", words="done", result="", date="2026-11-19"))
    assert _changed(repo, receipt.commit) == {NOTE, ARCHIVE}
    rows = {row.ref.id: row for row in parse_note(_at_origin(repo, NOTE), slot="hermes", note=NOTE)}
    assert set(rows) == {"TASK-P", "RT-W"}
    assert rows["RT-W"].raw.endswith(
        "· READY 2026-11-19 · unblocked 2026-11-19: `RT-A` closed by the owner")
    assert rows["TASK-P"].raw.endswith(
        "· READY 2026-11-19 · unblocked 2026-11-19: `RT-A` closed by the owner")
    archived = parse_note(_at_origin(repo, ARCHIVE), slot="hermes", note=ARCHIVE)
    assert [(r.ref.id, r.outcome.render()) for r in archived] == [("RT-A", "CLOSED 2026-11-19: owner — done")]


def test_an_agents_done_of_the_last_subtask_archives_its_task_when_every_brain_is_read(repo, tmp_path):
    """``runtime.work.done`` (``outcome: DONE, commit: here``) of the last open subtask archives the task in the same
    commit, ``DONE … · result: all 2 subtasks closed``, once the sibling brains are read beside the checkout (D7, as
    ``work_row.py close`` does). KILLING MUTATION: skip the task step -> TASK-P stays live, red."""

    _siblings_beside(tmp_path)
    writer = Writer(repo.board, machine_id="m1")
    writer.apply(_close("RT-A", "d1", outcome="DONE", commit="here", result="first", date="2026-11-19"))
    receipt = writer.apply(_close("RT-W", "d2", outcome="DONE", commit="here", result="second", date="2026-11-19"))
    assert _changed(repo, receipt.commit) == {NOTE, ARCHIVE}
    assert parse_note(_at_origin(repo, NOTE), slot="hermes", note=NOTE) == []
    archived = {r.ref.id: r for r in parse_note(_at_origin(repo, ARCHIVE), slot="hermes", note=ARCHIVE)}
    assert list(archived) == ["RT-A", "RT-W", "TASK-P"]
    assert archived["TASK-P"].outcome.render() == "DONE 2026-11-19 here"
    assert archived["TASK-P"].result == "all 2 subtasks closed"


def test_a_task_with_its_sibling_brains_unseen_is_left_open_as_the_script_leaves_it(repo):
    """With the launcher's and the backend's brains not beside the checkout, the last subtask's close leaves the
    task live (a subtask of it may live there) — ``work_row.py close``'s rule, not a second one."""

    writer = Writer(repo.board, machine_id="m1")
    writer.apply(_close("RT-A", "o1", outcome="CLOSED", words="done", result="", date="2026-11-19"))
    writer.apply(_close("RT-W", "o2", outcome="CLOSED", words="done", result="", date="2026-11-19"))
    assert [r.ref.id for r in parse_note(_at_origin(repo, NOTE), slot="hermes", note=NOTE)] == ["TASK-P"]


def test_a_workspace_brain_judges_its_tasks_on_its_own_rows():
    """A brain outside the three repos' (a workspace's own Work brain) reads no sibling and counts as fully read,
    so its last subtask's close archives its task. KILLING MUTATION: answer ``siblings_visible({})`` (False) for
    it -> red."""

    assert brain_siblings("Work_Brain", {"launcher": [], "backend": []}) == ({}, True)
    assert brain_siblings("Harness_Brain", {"launcher": []}) == ({"launcher": []}, False)
    assert brain_siblings("Harness_Brain", {"launcher": [], "backend": []}) == ({"launcher": [], "backend": []}, True)


def test_a_close_in_the_launcher_brain_reads_itself_once():
    """A board bound to the launcher's checkout finds its own brain among the siblings: that copy (its rows from
    before the close) is dropped. hermes's brain is never among the siblings read, so the launcher's tasks are not
    judged fully read (a subtask may live in hermes). KILLING MUTATION: keep the copy -> red."""

    own = parse_note(HEAD + ROWS, slot="launcher", note="q.md")
    assert brain_siblings("Launcher_Brain", {"launcher": own, "backend": []}) == ({"backend": []}, False)
