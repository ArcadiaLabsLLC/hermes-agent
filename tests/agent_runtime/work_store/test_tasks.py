"""Tasks and subtasks across the brains (RT-QUEUE-TASKS-GRAMMAR; launcher plan
``EterniaLauncher/docs/mission_control/planned/QUEUE_TASKS_AND_SUBTASKS_2026-11-09.md`` D1, D2, D4).

The fixtures ``grammar_tasks.md`` / ``grammar_task_defects.md`` are the launcher's, byte-identical, and the
expectations are its ``test/tool/queue_grammar_tasks_test.dart``'s.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from agent_runtime.work_store import grammar, tasks

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "work_queue"


def _fixture(name: str) -> list[grammar.Row]:
    return grammar.parse_note((FIXTURES / name).read_text(encoding="utf-8"), slot="fx", note=name)


def _rows(note: str, lines: list[str]) -> list[grammar.Row]:
    return grammar.parse_note("---\ntype: queue\nprogram: test\n---\n\n" + "\n".join(lines) + "\n", slot="t", note=note)


def _by_id(found: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in found:
        out.setdefault(line.split("  ")[1], []).append(re.search(r"\(([A-Z ]+):", line).group(1))
    return out


def test_the_task_fixture_is_clean() -> None:
    """KILLING MUTATION: drop the ``task=`` read in ``grammar.parse_row`` -> the task rows read as plain rows, so
    FX-TASK comes back ROW HAS NO TASK and its subtasks GROUP HAS NO TASK, red."""

    rows = _fixture("grammar_tasks.md")
    assert len(rows) == 5 and rows[0].task == "board-pills"
    assert all(row.defects == () for row in rows)
    assert tasks.task_defects(rows, [], siblings_visible=True) == []


def test_each_task_defect_fixture_row_is_caught_by_its_own_defect() -> None:
    """KILLING MUTATIONS: drop the TWO TASKS arm, the GROUP HAS NO TASK arm, the ROW HAS NO TASK arm, or any TASK TITLE
    arm of ``task_defects`` / ``task_title_problem`` -> that fixture row is missing here, red."""

    rows = _fixture("grammar_task_defects.md")
    assert all(row.defects == () for row in rows), "the task defects are cross-row, never row grammar"
    assert _by_id(tasks.task_defects(rows, [], siblings_visible=True)) == {
        "FX-TWO-TASKS-A": ["TWO TASKS"],
        "FX-TWO-TASKS-B": ["TWO TASKS"],
        "FX-GROUP-NO-TASK": ["GROUP HAS NO TASK"],
        "FX-PREFIX-NOT-DOTTED": ["GROUP HAS NO TASK"],
        "FX-ROW-NO-TASK": ["ROW HAS NO TASK"],
        "FX-TITLE-CODE": ["TASK TITLE"],
        "FX-TITLE-PATH": ["TASK TITLE"],
        "FX-TITLE-ID": ["TASK TITLE"],
        "FX-TITLE-LONG": ["TASK TITLE"],
    }


def test_the_title_problems_name_their_cause() -> None:
    why = {row.ref.id: tasks.task_title_problem(row) for row in _fixture("grammar_task_defects.md")
           if row.ref.id.startswith("FX-TITLE-")}
    assert why["FX-TITLE-CODE"] == "a code span"
    assert why["FX-TITLE-PATH"] == "a path"
    assert why["FX-TITLE-ID"] == "a row ID"
    assert f"over {tasks.TASK_TITLE_LIMIT}" in why["FX-TITLE-LONG"]
    assert [tasks.task_title_problem(r) for r in _fixture("grammar_tasks.md") if r.task] == [None, None]


def test_a_task_in_a_sibling_brain_owns_a_group_here_and_a_sibling_task_for_the_same_slug_is_two_tasks() -> None:
    here = _rows("runtime-queue.md", [
        "- **`H-SUB` — A subtask** · group: pills.hermes · READY 2026-11-09",
        "- **`H-TASK` — Pills on the board** · task: twice · READY 2026-11-09",
    ])
    sibling = _rows("launcher-queue.md", [
        "- **`L-TASK` — Pills everywhere** · task: pills · READY 2026-11-09",
        "- **`L-TWICE` — Pills again** · task: twice · READY 2026-11-09",
    ])
    assert _by_id(tasks.task_defects(here, sibling, siblings_visible=True)) == {"H-TASK": ["TWO TASKS"]}
    assert _by_id(tasks.task_defects(here, [], siblings_visible=True)) == {"H-SUB": ["GROUP HAS NO TASK"]}


def test_group_has_no_task_is_not_judged_when_a_sibling_brain_is_missing() -> None:
    """KILLING MUTATION: drop ``siblings_visible and`` in ``task_defects`` -> the orphan group is judged, red."""

    rows = _rows("runtime-queue.md", [
        "- **`H-SUB` — A subtask** · group: elsewhere · READY 2026-11-09",
        "- **`H-LONE` — A lone row** · READY 2026-11-09",
    ])
    assert _by_id(tasks.task_defects(rows, [], siblings_visible=False)) == {"H-LONE": ["ROW HAS NO TASK"]}


def test_owning_task_walks_dotted_prefixes_never_bare_string_prefixes() -> None:
    """KILLING MUTATION: match a bare string prefix (``group.startswith(task)``) -> FX-PREFIX-NOT-DOTTED
    (``twicefold``) finds ``twice``; the defect fixture test reds."""

    assert tasks.owning_task("a.b.c", {"a"}) == "a"
    assert tasks.owning_task("a.b", {"a.b"}) == "a.b"
    assert tasks.owning_task("a.b.c", {"a", "a.b"}) == "a.b", "the nearest task wins"
    assert tasks.owning_task("ab", {"a"}) is None
    assert tasks.owning_task("a", {"a.b"}) is None


def test_subtasks_of_keeps_a_nested_tasks_rows_to_it() -> None:
    rows = _rows("q.md", [
        "- **`T-A` — A** · task: a · READY 2026-11-09",
        "- **`T-AB` — A and B** · task: a.b · READY 2026-11-09",
        "- **`S-1` — one** · group: a · READY 2026-11-09",
        "- **`S-2` — two** · group: a.c · READY 2026-11-09",
        "- **`S-3` — three** · group: a.b.d · READY 2026-11-09",
    ])
    by_id = {row.ref.id: row for row in rows}
    assert [r.ref.id for r in tasks.subtasks_of(by_id["T-A"], rows)] == ["S-1", "S-2"]
    assert tasks.task_of(by_id["S-3"], rows).ref.id == "T-AB"
    assert tasks.task_of(by_id["T-A"], rows) is None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args], check=True,
                   capture_output=True)


def test_sibling_rows_reads_both_brains_beside_a_worktree_and_origin_main_when_it_is_ahead(tmp_path: Path) -> None:
    """A linked worktree outside the workspace still finds the siblings beside its primary; a sibling's
    ``origin/main`` ahead of its HEAD (fetched, not pulled) is read. KILLING MUTATIONS: drop the ``gitdir:`` root in
    ``workspace_roots`` -> nothing found from the worktree, red; skip ``_origin_texts`` -> L-NEW missing, red."""

    workspace = tmp_path / "ws"
    hermes = workspace / "hermes-agent"
    hermes.mkdir(parents=True)
    _git(hermes, "init", "-q", "-b", "main")
    _git(hermes, "commit", "-q", "--allow-empty", "-m", "root")
    lane = tmp_path / "lanes" / "lane"
    _git(hermes, "worktree", "add", "-q", str(lane))
    head = "---\ntype: queue\nprogram: t\n---\n\n"
    for brain, relative in tasks.SIBLING_QUEUE_DIRS.items():
        checkout = workspace / relative.split("/", 1)[0]
        directory = workspace / relative
        directory.mkdir(parents=True)
        note = directory / "q.md"
        note.write_text(head + f"- **`{brain.upper()}-T` — A task** · task: {brain} · READY 2026-11-09\n",
                        encoding="utf-8")
        _git(checkout, "init", "-q", "-b", "main")
        _git(checkout, "add", "-A")
        _git(checkout, "commit", "-q", "-m", "one")
    launcher = workspace / "EterniaLauncher"
    note = workspace / tasks.SIBLING_QUEUE_DIRS["launcher"] / "q.md"
    note.write_text(note.read_text(encoding="utf-8") + "- **`L-NEW` — New** · group: launcher · READY 2026-11-09\n",
                    encoding="utf-8")
    _git(launcher, "commit", "-q", "-am", "two")
    _git(launcher, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(launcher, "reset", "-q", "--hard", "HEAD~1")
    found = tasks.sibling_rows(lane, environ={})
    assert tasks.siblings_visible(found)
    assert sorted(r.ref.id for r in found["launcher"]) == ["L-NEW", "LAUNCHER-T"]
    assert [r.task for r in found["backend"]] == ["backend"]
    assert tasks.sibling_rows(tmp_path / "lanes" / "nowhere", environ={}) == {}


def test_write_task_defects_holds_only_the_rows_a_write_changes() -> None:
    """RT-QUEUE-TASK-RULES-AT-WRITE. KILLING MUTATIONS: treat every row as changed (drop the prior filter) -> the
    carried RT-OLD is refused, red; drop the uses-no-tasks exemption -> the Work brain's untasked append is refused,
    red; drop the BAD TASK arm -> the task beside a group passes, red."""

    head = "---\ntype: queue\nprogram: t\n---\n\n"
    prior = head + ("- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n"
                    "- **`RT-OLD` — carried, no task** · READY 2026-11-09\n")
    def defects(*lines: str, before: str = prior) -> list[str]:
        return tasks.write_task_defects({"q.md": (before, before + "".join(line + "\n" for line in lines))}, [], [],
                                        siblings_visible=True)
    assert defects() == [], "a defect the note already carried is not refused"
    assert defects("- **`RT-SUB` — slice** · group: p.x · READY 2026-11-09") == []
    assert "ROW HAS NO TASK" in defects("- **`RT-NEW` — new** · READY 2026-11-09")[0]
    assert "GROUP HAS NO TASK" in defects("- **`RT-G` — g** · group: nowhere · READY 2026-11-09")[0]
    assert "BAD TASK" in defects("- **`TASK-X` — X** · task: x · group: p · READY 2026-11-09")[0]
    work = head + "- **`WORK-ABCDEF` — t** · READY 2026-11-09\n"
    assert defects("- **`WORK-BCDEFG` — u** · READY 2026-11-09", before=work) == [], "a brain using no tasks"
