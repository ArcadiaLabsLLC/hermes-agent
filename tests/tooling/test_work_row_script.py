"""``scripts/work_row.py`` — a session's by-ID row op: commit by pathspec, push, never fetch or reset."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

ROOT = Path(__file__).resolve().parents[2]
NOTE = "Harness_Brain/20 — Active Initiatives/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
ROWS = "- **`RT-A` — first** · READY 2026-10-18\n- **`RT-B` — second** · READY 2026-10-18\n"


def _load():
    spec = importlib.util.spec_from_file_location("work_row_script", ROOT / "scripts" / "work_row.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


work_row = _load()


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


@pytest.fixture
def clones(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Session Lane")
        monkeypatch.setenv(f"{key}_EMAIL", "lane@test.invalid")
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    mine = tmp_path / "mine"
    git("clone", "-q", str(origin), str(mine), cwd=tmp_path)
    git("config", "user.name", "Session Lane", cwd=mine)
    (mine / NOTE).parent.mkdir(parents=True)
    (mine / NOTE).write_text(HEAD + ROWS, encoding="utf-8", newline="\n")
    (mine / "README.md").write_text("seed\n", encoding="utf-8")
    git("add", "-A", cwd=mine)
    git("commit", "-q", "-m", "seed", cwd=mine)
    git("push", "-q", "-u", "origin", "main", cwd=mine)
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    return origin, mine, other


def test_claim_by_id_commits_by_pathspec_and_pushes(clones):
    origin, mine, _ = clones
    (mine / "README.md").write_text("staged, not this commit's\n", encoding="utf-8")
    git("add", "README.md", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue: claim RT-A r-lane"
    assert git("show", "--name-only", "--format=", "main", cwd=origin).strip() == NOTE
    assert "**TAKEN " in git("show", f"main:{NOTE}", cwd=origin)
    assert git("diff", "--cached", "--name-only", cwd=mine).strip() == "README.md"


def test_claim_names_machine_account_and_worktree(clones, monkeypatch):
    origin, mine, _ = clones
    monkeypatch.setattr(work_row.socket, "gethostname", lambda: "box-1")
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    note = git("show", f"main:{NOTE}", cwd=origin)
    assert "· **TAKEN " in note and " r-lane on box-1 as Session-Lane in mine**" in note
    assert work_row.main(["claim", "RT-B", "--who", "r-lane", "--machine", "m", "--account", "a", "--worktree", "w",
                          "--repo", str(mine)]) == 0
    assert " r-lane on m as a in w**" in git("show", f"main:{NOTE}", cwd=origin)


def test_claim_with_an_unreadable_part_refuses(clones, capsys):
    _, mine, _ = clones
    before = (mine / NOTE).read_bytes()
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--account", " ", "--repo", str(mine)]) == 2
    assert "pass --account" in capsys.readouterr().err
    assert (mine / NOTE).read_bytes() == before


def test_non_fast_forward_exits_3_and_touches_nothing_else(clones, capsys):
    origin, mine, other = clones
    (other / NOTE).write_text(HEAD + ROWS.replace("second", "renamed"), encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", "other session", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    tracking = git("rev-parse", "origin/main", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 3
    assert "fetch, then re-run" in capsys.readouterr().err
    assert git("rev-parse", "origin/main", cwd=mine) == tracking
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "other session"


def test_never_fetches_or_resets(clones):
    _, mine, _ = clones
    calls: list[list[str]] = []

    def fake(args, repo):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    for argv in (["claim", "RT-A"], ["set-status", "RT-A", "--status", "DEFERRED 2026-10-18: later"],
                 ["delete", "RT-B"], ["append", "RT-C", "--row", "- **`RT-C` — new** · READY 2026-10-18"]):
        assert work_row.main([*argv, "--who", "r-lane", "--repo", str(mine)], git=fake) == 0
    verbs = {call[0] for call in calls}
    assert verbs == {"add", "commit", "push", "symbolic-ref"}
    assert not verbs & {"fetch", "reset", "stash", "pull", "merge", "rebase", "checkout"}


@pytest.mark.parametrize("place", ["lane branch", "detached HEAD"])
def test_a_close_from_a_lane_branch_or_a_detached_head_pushes_to_main(clones, place):
    """FH-WORK-ROW-CLOSE-PUSH-FROM-LANE-BRANCH: a bare ``git push`` from a branch with no upstream exited 4
    ("no upstream branch") and from a detached HEAD pushed nothing, so lanes pushed the close by hand.
    Mutation: ``push_target`` back to ``[]`` (a bare push) -> exit 4 and origin's main unmoved, red."""
    origin, mine, _ = clones
    if place == "lane branch":
        git("checkout", "-q", "-b", "wave/lane", cwd=mine)
    else:
        git("checkout", "-q", "--detach", cwd=mine)
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--date", "2026-11-03",
                          "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue(q): close RT-A DONE 3f9c2a1"
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "HEAD", cwd=mine)


def test_a_branch_with_an_upstream_pushes_to_that_upstream(clones):
    origin, mine, _ = clones
    git("push", "-q", "origin", "main:side", cwd=mine)
    git("checkout", "-q", "-b", "mine-side", "--track", "origin/side", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "side", cwd=origin).strip() == "queue: claim RT-A r-lane"
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "seed"


def test_close_archives_the_row_and_commits_both_files(clones):
    """RT-QUEUE-ARCHIVE-GRAMMAR. Mutation: write the queue text unchanged in ``main``'s close arm -> the row stays
    live beside its archived copy, red."""
    origin, mine, _ = clones
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--date", "2026-11-03",
                          "--result", "shipped", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue(q): close RT-A DONE 3f9c2a1"
    changed = set(filter(None, git("show", "--name-only", "--format=", "main", cwd=origin).split("\n")))
    archive = "Harness_Brain/80 — Archive/Queues/q-2026-11.md"
    assert changed == {NOTE, archive}
    archived = (mine / archive).read_text(encoding="utf-8")
    assert archived.startswith("---\ntype: queue-archive\nqueue: q.md\nprogram: test\nmonth: 2026-11\n---\n")
    assert archived.endswith("- **`RT-A` — first** · DONE 2026-11-03 3f9c2a1 · result: shipped\n")
    assert "RT-A" not in (mine / NOTE).read_text(encoding="utf-8")
    assert work_row.main(["close", "RT-B", "--who", "r-lane", "--repo", str(mine), "--no-commit"]) == work_row.EXIT_REFUSED


def test_close_wakes_the_rows_blocked_on_it_and_commits_their_note(clones):
    """BRAIN-QUEUE-CLOSE-WAKES-DEPENDENTS. Mutation: skip ``wake_dependents`` in ``main``'s close arm -> RT-W stays
    BLOCKED and its note is not in the commit, red."""
    origin, mine, _ = clones
    waiting = (HEAD + "- **`RT-W` — waits** · BLOCKED 2026-11-01: another lane — `RT-A` the fix\n"
               "- **`RT-L` — waits on the launcher** · BLOCKED 2026-11-01: launcher — `RT-A`\n")
    other_note = "Harness_Brain/20 — Active Initiatives/w.md"
    (mine / other_note).write_text(waiting, encoding="utf-8", newline="\n")
    git("add", "-A", cwd=mine)
    git("commit", "-q", "-m", "waiting", cwd=mine)
    git("push", "-q", cwd=mine)
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--date", "2026-11-03",
                          "--repo", str(mine)]) == 0
    woken = (mine / other_note).read_text(encoding="utf-8")
    assert ("- **`RT-W` — waits** · READY 2026-11-03 · unblocked 2026-11-03: `RT-A` closed DONE 3f9c2a1\n"
            in woken)
    assert "BLOCKED 2026-11-01: launcher — `RT-A`" in woken
    changed = set(filter(None, git("show", "--name-only", "--format=", "main", cwd=origin).split("\n")))
    assert other_note in changed


def test_no_wake_leaves_them_blocked(clones):
    _, mine, _ = clones
    waiting = HEAD + "- **`RT-W` — waits** · BLOCKED 2026-11-01: hermes — `RT-A`\n"
    other_note = "Harness_Brain/20 — Active Initiatives/w.md"
    (mine / other_note).write_text(waiting, encoding="utf-8", newline="\n")
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--owner", "not needed", "--no-wake",
                          "--repo", str(mine), "--no-commit"]) == 0
    assert (mine / other_note).read_text(encoding="utf-8") == waiting


TASK_ROWS = ("- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n"
             "- **`RT-S1` — first slice** · group: p · READY 2026-11-09\n"
             "- **`RT-S2` — second slice** · group: p.x · READY 2026-11-09\n")


def _siblings(tmp_path: Path, launcher_rows: str = "") -> None:
    for relative in work_row.SIBLING_QUEUE_DIRS.values():
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    note = tmp_path / work_row.SIBLING_QUEUE_DIRS["launcher"] / "mission-control-queue.md"
    note.write_text(HEAD + launcher_rows, encoding="utf-8", newline="\n")


def _seed(mine: Path, rows: str) -> None:
    (mine / NOTE).write_text(HEAD + ROWS + rows, encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", "tasks", cwd=mine)
    git("push", "-q", cwd=mine)


def test_the_last_subtask_closing_closes_its_task(clones, tmp_path, monkeypatch, capsys):
    """RT-QUEUE-TASKS-GRAMMAR (launcher plan QUEUE_TASKS_AND_SUBTASKS_2026-11-09 D7). KILLING MUTATION: skip
    ``close_task`` in ``task_step`` -> TASK-P stays live after RT-S2 closes, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    origin, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, TASK_ROWS)
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--date", "2026-11-09",
                          "--repo", str(mine)]) == 0
    assert "`TASK-P` — Pills" in (mine / NOTE).read_text(encoding="utf-8"), "RT-S2 is still open"
    assert work_row.main(["close", "RT-S2", "--who", "r", "--done", "5d6e7f8", "--date", "2026-11-09",
                          "--repo", str(mine)]) == 0
    assert "closed task `TASK-P` DONE 2026-11-09 5d6e7f8: all 2 subtasks closed" in capsys.readouterr().out
    assert "TASK-P" not in (mine / NOTE).read_text(encoding="utf-8")
    archive = (mine / "Harness_Brain/80 — Archive/Queues/q-2026-11.md").read_text(encoding="utf-8")
    assert archive.endswith("- **`RT-S2` — second slice** · group: p.x · DONE 2026-11-09 5d6e7f8\n"
                            "- **`TASK-P` — Pills on the board** · task: p · DONE 2026-11-09 5d6e7f8 · "
                            "result: all 2 subtasks closed\n")
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue(q): close RT-S2 DONE 5d6e7f8"


def test_a_subtask_open_in_a_sibling_brain_or_a_sibling_not_checked_out_keeps_the_task_open(
        clones, tmp_path, monkeypatch, capsys):
    """KILLING MUTATIONS: drop the sibling rows from ``_brains`` in ``task_step`` -> TASK-P closes with
    L-S open, red; drop the ``siblings_visible`` arm -> TASK-P closes with no siblings checked out, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _seed(mine, TASK_ROWS.replace("- **`RT-S2` — second slice** · group: p.x · READY 2026-11-09\n", ""))
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--repo", str(mine),
                          "--no-commit"]) == 0
    assert "brain is not checked out beside this repository: left open" in capsys.readouterr().out
    assert "TASK-P" in (mine / NOTE).read_text(encoding="utf-8")
    git("checkout", "-q", "--", ".", cwd=mine)
    git("clean", "-qfd", cwd=mine)
    _siblings(tmp_path, "- **`L-S` — launcher slice** · group: p · READY 2026-11-09\n")
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--repo", str(mine),
                          "--no-commit"]) == 0
    assert "TASK-P" in (mine / NOTE).read_text(encoding="utf-8")


def test_a_woken_subtask_sets_its_blocked_task_ready(clones, tmp_path, monkeypatch, capsys):
    """D3 amended. KILLING MUTATION: never return READY in ``task_status_after_close`` -> TASK-W stays BLOCKED, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    origin, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, "- **`TASK-W` — Wait for the fix** · task: w · BLOCKED 2026-11-09: another lane — `RT-W1` first\n"
                "- **`RT-W1` — the slice** · group: w · BLOCKED 2026-11-09: another lane — `RT-A` the fix\n")
    assert work_row.main(["close", "RT-A", "--who", "r", "--done", "3f9c2a1", "--date", "2026-11-09",
                          "--repo", str(mine)]) == 0
    text = (mine / NOTE).read_text(encoding="utf-8")
    assert ("- **`TASK-W` — Wait for the fix** · task: w · READY 2026-11-09 · unblocked 2026-11-09: `RT-A` closed "
            "DONE 3f9c2a1\n") in text
    assert "- **`RT-W1` — the slice** · group: w · READY 2026-11-09 · unblocked" in text
    assert "task `TASK-W`: READY 2026-11-09" in capsys.readouterr().out
    assert NOTE in git("show", "--name-only", "--format=", "main", cwd=origin)


# ── RT-QUEUE-TASKS-DOORS (the launcher's close_row_task_test at 41b1ed9d4f) ──────────────────────────

PARKED = "- **`TASK-P` — Pills on the board** · task: p · DEFERRED 2026-11-09: after release\n"
OWED = ("- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-09: owner decision — which pill? · "
        "Recommend: the round one\n")
SUBTASK = "- **`RT-S1` — first slice** · group: p · READY 2026-11-09\n"


def test_a_lane_claim_of_a_subtask_of_a_task_that_is_not_ready_is_refused(clones, tmp_path, monkeypatch, capsys):
    """KILLING MUTATION: skip ``refuse_claim_of_parked`` in ``main`` -> RT-S1 is claimed, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, PARKED + SUBTASK)
    claim = ["claim", "RT-S1", "--who", "lane", "--machine", "box", "--account", "me", "--worktree", "wt",
             "--repo", str(mine), "--no-commit"]
    assert work_row.main(claim) == work_row.EXIT_REFUSED
    assert "task_not_ready `RT-S1` is a subtask of task `TASK-P`" in capsys.readouterr().err
    assert "TAKEN" not in (mine / NOTE).read_text(encoding="utf-8")
    (mine / NOTE).write_text(HEAD + ROWS + PARKED.replace("DEFERRED 2026-11-09: after release", "READY 2026-11-09")
                             + SUBTASK, encoding="utf-8", newline="\n")
    assert work_row.main(claim) == 0
    assert "**TAKEN " in (mine / NOTE).read_text(encoding="utf-8")


def test_done_on_a_subtask_of_a_parked_or_owner_blocked_task_is_refused(clones, tmp_path, monkeypatch, capsys):
    """KILLING MUTATIONS: skip ``refuse_parked_task`` in ``main`` -> both DONE closes go, red; drop the owner-decision
    arm of ``task_refuses_done`` -> the OWED close goes, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    for task in (PARKED, OWED):
        _seed(mine, task + SUBTASK)
        done = ["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--repo", str(mine), "--no-commit"]
        assert work_row.main(done) == work_row.EXIT_REFUSED, task
        assert "which is " in capsys.readouterr().err
        assert "RT-S1" in (mine / NOTE).read_text(encoding="utf-8")
    owner = ["close", "RT-S1", "--who", "r", "--owner", "not needed", "--repo", str(mine), "--no-commit"]
    assert work_row.main(owner) == 0, "an owner close still goes"


def test_no_startable_subtask_blocks_the_task_on_the_first_waiting_one(clones, tmp_path, monkeypatch, capsys):
    """D3 amended. KILLING MUTATION: return None where ``task_status_after_close`` builds the block -> TASK-P stays
    READY, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, "- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09 · unblocked 2026-11-08: old\n"
                + SUBTASK + "- **`RT-S2` — waits** · group: p · BLOCKED 2026-11-09: another lane — `RT-B` first\n"
                "- **`RT-S3` — parked** · group: p · DEFERRED 2026-11-09: later\n")
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--date", "2026-11-09",
                          "--repo", str(mine), "--no-commit"]) == 0
    assert ("- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-09: another lane — `RT-S2` every live "
            "subtask waits (1 on other work); the task turns READY when one of them does\n"
            ) in (mine / NOTE).read_text(encoding="utf-8")
    assert "task `TASK-P`: BLOCKED 2026-11-09" in capsys.readouterr().out


def test_an_owner_block_of_the_tasks_own_stays_when_a_subtask_wakes(clones, tmp_path, monkeypatch):
    """KILLING MUTATION: drop the owner guard in ``task_status_after_close`` -> TASK-P turns READY, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, OWED + "- **`RT-S1` — waits** · group: p · BLOCKED 2026-11-09: another lane — `RT-A` the fix\n")
    assert work_row.main(["close", "RT-A", "--who", "r", "--done", "3f9c2a1", "--repo", str(mine),
                          "--no-commit"]) == 0
    text = (mine / NOTE).read_text(encoding="utf-8")
    assert OWED in text and "- **`RT-S1` — waits** · group: p · READY" in text


def test_a_write_whose_changed_rows_break_the_task_rules_is_refused(clones, tmp_path, monkeypatch, capsys):
    """RT-QUEUE-TASK-RULES-AT-WRITE. KILLING MUTATIONS: drop ``refuse_task_defects`` in ``main``'s edit arm ->
    RT-LONE is appended, red; drop it in the close arm -> the close whose task step rewrites TASK-Q's line (a
    technical title it carried) lands, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, "- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n")
    lone = "- **`RT-LONE` — lone** · READY 2026-11-09"
    assert work_row.main(["append", "RT-LONE", "--who", "r", "--row", lone, "--repo", str(mine),
                          "--no-commit"]) == work_row.EXIT_REFUSED
    assert "(ROW HAS NO TASK" in capsys.readouterr().err and "RT-LONE" not in (mine / NOTE).read_text(encoding="utf-8")
    sub = "- **`RT-SUB` — slice** · group: p · READY 2026-11-09"
    assert work_row.main(["append", "RT-SUB", "--who", "r", "--row", sub, "--repo", str(mine), "--no-commit"]) == 0
    # A close whose task step rewrites a task line carrying an old TASK TITLE defect: the changed line is refused.
    _seed(mine, "- **`TASK-Q` — Fix `x.py` here** · task: q · READY 2026-11-09\n" + SUBTASK.replace("group: p", "group: q")
          + "- **`RT-S2` — waits** · group: q · BLOCKED 2026-11-09: another lane — `RT-B` first\n")
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--repo", str(mine),
                          "--no-commit"]) == work_row.EXIT_REFUSED
    assert "(TASK TITLE" in capsys.readouterr().err and "RT-S1" in (mine / NOTE).read_text(encoding="utf-8")
