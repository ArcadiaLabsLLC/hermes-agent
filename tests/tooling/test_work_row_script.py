"""``scripts/work_row.py`` — a session's by-ID row op: commit by pathspec, push; a lost push race is retried by
re-applying the op on the new tip, and a close refuses a commit that is not on the target branch."""

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


def _other_session_pushes(other: Path, subject: str = "other session") -> None:
    (other / NOTE).write_text(HEAD + ROWS.replace("second", "renamed"), encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", subject, cwd=other)
    git("push", "-q", "origin", "main", cwd=other)


def test_a_lost_push_race_is_retried_on_the_new_tip(clones, capsys):
    """FH-WORK-ROW-CLOSE-CHECKS-SHA-ON-MAIN: a claim whose push lost the race exited 3 and the lane fetched and
    re-ran by hand (~2 min a row on a busy main). It now re-applies the op by ID on the fetched tip.
    KILLING MUTATION: ``main`` returns the first ``EXIT_NON_FAST_FORWARD`` (no retry) -> exit 3, the claim absent
    from origin, red. A staged change that is not the op's stays staged through the retry."""
    origin, mine, other = clones
    _other_session_pushes(other)
    (mine / "README.md").write_text("staged, not this commit's\n", encoding="utf-8")
    git("add", "README.md", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert "non-fast-forward" not in capsys.readouterr().err
    assert git("log", "-2", "--format=%s", "main", cwd=origin).split("\n")[:2] == [
        "queue: claim RT-A r-lane", "other session"]
    note = git("show", f"main:{NOTE}", cwd=origin)
    assert "**TAKEN " in note and "renamed" in note
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "HEAD", cwd=mine)
    assert git("diff", "--cached", "--name-only", cwd=mine).strip() == "README.md"
    assert git("status", "--porcelain", "--untracked-files=no", cwd=mine).strip() == "M  README.md"


def test_two_closes_racing_into_one_archive_file_both_land(clones):
    """Two lanes closing at once both append at the end of the month's archive file; the loser's close used to
    need a hand-made redo from a fresh ``origin/main``. The retry re-applies it, so both lines are kept."""
    origin, mine, other = clones
    git("config", "user.name", "Other Lane", cwd=other)
    git("config", "user.email", "other@test.invalid", cwd=other)
    assert work_row.main(["close", "RT-B", "--who", "o-lane", "--owner", "not needed", "--date", "2026-11-03",
                          "--repo", str(other)]) == 0
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--owner", "dropped", "--date", "2026-11-03",
                          "--repo", str(mine)]) == 0
    archive = git("show", "main:Harness_Brain/80 — Archive/Queues/q-2026-11.md", cwd=origin)
    assert archive.count("- **`RT-B` — second**") == 1 and archive.count("- **`RT-A` — first**") == 1
    assert archive.index("`RT-B`") < archive.index("`RT-A`")
    live = git("show", f"main:{NOTE}", cwd=origin)
    assert "RT-A" not in live and "RT-B" not in live
    assert git("status", "--porcelain", cwd=mine).strip() == ""


def test_a_claim_that_lost_to_another_lanes_claim_is_refused_not_doubled(clones, capsys):
    origin, mine, other = clones
    git("config", "user.name", "Other Lane", cwd=other)
    git("config", "user.email", "other@test.invalid", cwd=other)
    assert work_row.main(["claim", "RT-A", "--who", "o-lane", "--repo", str(other)]) == 0
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == work_row.EXIT_REFUSED
    assert "already_taken" in capsys.readouterr().err
    note = git("show", f"main:{NOTE}", cwd=origin)
    assert note.count("**TAKEN ") == 1 and " o-lane on " in note
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "HEAD", cwd=mine)
    assert git("status", "--porcelain", cwd=mine).strip() == ""


def test_a_lost_race_with_other_unpushed_commits_exits_3_and_rewrites_nothing(clones, capsys):
    """The retry is only for a checkout whose one unpushed commit is the op: anything else is the session's
    to rebase. Mutation: drop the ``HEAD~1`` ancestor check -> the local commit is reset away, red."""
    origin, mine, other = clones
    _other_session_pushes(other)
    (mine / "README.md").write_text("a lane's own unpushed work\n", encoding="utf-8")
    git("commit", "-q", "-am", "lane work", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 3
    assert "fetch, then re-run" in capsys.readouterr().err
    assert git("log", "-2", "--format=%s", cwd=mine).split("\n")[:2] == ["queue: claim RT-A r-lane", "lane work"]
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "other session"


def test_a_close_on_a_commit_that_never_reached_main_is_refused(clones, capsys):
    """FH-WORK-ROW-CLOSE-CHECKS-SHA-ON-MAIN: a rejected push hidden behind a pipe let ``close`` archive a row DONE
    on a commit that was not on ``origin/main``. KILLING MUTATION: ``unlanded_sha`` returns None -> the first
    close exits 0 and the row is archived on the unpushed commit, red."""
    origin, mine, other = clones
    (mine / "README.md").write_text("the fix\n", encoding="utf-8")
    git("commit", "-q", "-am", "the fix", cwd=mine)
    sha = git("rev-parse", "--short=10", "HEAD", cwd=mine).strip()
    before = (mine / NOTE).read_bytes()
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", sha, "--repo", str(mine)]) == work_row.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "sha_not_on_main" in err and "push it first" in err
    assert (mine / NOTE).read_bytes() == before
    assert git("log", "-1", "--format=%s", cwd=mine).strip() == "the fix"
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--refuted", "0123abc", "--repo", str(mine)]) == work_row.EXIT_REFUSED
    git("push", "-q", "origin", "HEAD:main", cwd=mine)
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", sha, "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == f"queue(q): close RT-A DONE {sha}"
    # A commit a peer pushed is found by the one fetch; ``here`` names no commit to check.
    git("pull", "-q", "--ff-only", cwd=other)
    (other / "README.md").write_text("a peer's fix\n", encoding="utf-8")
    git("commit", "-q", "-am", "peer fix", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    peer = git("rev-parse", "--short=10", "HEAD", cwd=other).strip()
    assert work_row.main(["close", "RT-B", "--who", "r-lane", "--refuted", peer, "--repo", str(mine), "--no-commit"]) == 0


def test_two_pushes_arriving_together_count_as_a_lost_race(clones):
    """The remote answers two simultaneous pushes ``! [remote rejected] … (cannot lock ref … is at X but expected
    Y)``, not ``! [rejected]``; it is the same lost race and is retried. Mutation: drop ``cannot lock ref`` from
    ``NON_FAST_FORWARD`` -> exit 4, no fetch, red."""
    _, mine, _ = clones
    calls: list[list[str]] = []
    before = (mine / NOTE).read_bytes()

    def fake(args, repo):
        calls.append(list(args))
        if args[0] == "restore":  # what the real one does to the op's paths
            (mine / NOTE).write_bytes(before)
        if args[0] == "push" and sum(call[0] == "push" for call in calls) == 1:
            return subprocess.CompletedProcess(args, 1, "", " ! [remote rejected]       HEAD -> main (cannot lock ref "
                                               "'refs/heads/main': is at 4fcd07dd64 but expected db4a7c9713)")
        return subprocess.CompletedProcess(args, 0, "abc1234\n" if args[0] == "rev-parse" else "", "")

    assert work_row.main(["claim", "RT-B", "--who", "r-lane", "--repo", str(mine)], git=fake) == 0
    assert [call[0] for call in calls].count("push") == 2 and ["fetch", "-q", "origin", "main"] in calls


def test_a_push_that_lands_first_time_never_fetches_or_resets(clones):
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
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--allow-unlanded", "--date", "2026-11-03",
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
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--allow-unlanded", "--date", "2026-11-03",
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
    assert work_row.main(["close", "RT-A", "--who", "r-lane", "--done", "3f9c2a1", "--allow-unlanded", "--date", "2026-11-03",
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
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-09",
                          "--repo", str(mine)]) == 0
    assert "`TASK-P` — Pills" in (mine / NOTE).read_text(encoding="utf-8"), "RT-S2 is still open"
    assert work_row.main(["close", "RT-S2", "--who", "r", "--done", "5d6e7f8", "--allow-unlanded", "--date", "2026-11-09",
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
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--repo", str(mine),
                          "--no-commit"]) == 0
    assert "brain is not checked out beside this repository: left open" in capsys.readouterr().out
    assert "TASK-P" in (mine / NOTE).read_text(encoding="utf-8")
    git("checkout", "-q", "--", ".", cwd=mine)
    git("clean", "-qfd", cwd=mine)
    _siblings(tmp_path, "- **`L-S` — launcher slice** · group: p · READY 2026-11-09\n")
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--repo", str(mine),
                          "--no-commit"]) == 0
    assert "TASK-P" in (mine / NOTE).read_text(encoding="utf-8")


def test_a_woken_subtask_sets_its_blocked_task_ready(clones, tmp_path, monkeypatch, capsys):
    """D3 amended. KILLING MUTATION: never return READY in ``task_status_after_close`` -> TASK-W stays BLOCKED, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    origin, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, "- **`TASK-W` — Wait for the fix** · task: w · BLOCKED 2026-11-09: another lane — `RT-W1` first\n"
                "- **`RT-W1` — the slice** · group: w · BLOCKED 2026-11-09: another lane — `RT-A` the fix\n")
    assert work_row.main(["close", "RT-A", "--who", "r", "--done", "3f9c2a1", "--allow-unlanded", "--date", "2026-11-09",
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
        done = ["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--repo", str(mine), "--no-commit"]
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
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-09",
                          "--repo", str(mine), "--no-commit"]) == 0
    assert ("- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-09: another lane — `RT-S2` every live "
            "subtask waits (1 on other work); the task turns READY when one of them does\n"
            ) in (mine / NOTE).read_text(encoding="utf-8")
    assert "task `TASK-P`: BLOCKED 2026-11-09" in capsys.readouterr().out


def test_a_live_check_subtask_keeps_its_task_ready(clones, tmp_path, monkeypatch):
    """RT-QUEUE-LIVE-CHECK-STATUS. KILLING MUTATION: drop ``Status.LIVE_CHECK`` from ``grammar.STARTABLE`` -> TASK-P
    turns BLOCKED on RT-S3 with a live check left to run, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    task = "- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n"
    _seed(mine, task + SUBTASK
          + "- **`RT-S2` — the pill reads right** · group: p · LIVE CHECK 2026-11-12: open the board, read the pill\n"
          "- **`RT-S3` — waits** · group: p · BLOCKED 2026-11-09: another lane — `RT-B` first\n")
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--repo", str(mine),
                          "--no-commit"]) == 0
    assert task in (mine / NOTE).read_text(encoding="utf-8")
    claim = ["claim", "RT-S2", "--who", "lane", "--machine", "box", "--account", "me", "--worktree", "wt",
             "--repo", str(mine), "--no-commit"]
    assert work_row.main(claim) == 0 and "read the pill · **TAKEN " in (mine / NOTE).read_text(encoding="utf-8")


def test_a_decision_subtask_waits_on_the_owner_and_its_tasks_block_holds_no_other_close(
        clones, tmp_path, monkeypatch, capsys):
    """RT-QUEUE-LIVE-CHECK-STATUS. KILLING MUTATIONS: drop ``Status.DECISION`` from the ``waiting`` rows of
    ``task_status_after_close`` -> TASK-P stays READY with only a question left, red; drop the own-subtask arm of
    ``task_refuses_done`` -> the DONE close of RT-S3 under the block is refused, red; drop the ``DECISION`` arm of
    ``task_refuses_done`` -> a DONE close under a task that is itself a DECISION goes, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    question = "- **`RT-S2` — which pill** · group: p · DECISION 2026-11-12: round or square? · Recommend: round\n"
    _seed(mine, "- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n" + SUBTASK + question)
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-12",
                          "--repo", str(mine), "--no-commit"]) == 0
    blocked = ("- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-12: owner decision — `RT-S2` every "
               "live subtask waits (1 on the owner); the task turns READY when one of them does · "
               "Recommend: answer `RT-S2`\n")
    assert blocked in (mine / NOTE).read_text(encoding="utf-8")
    capsys.readouterr()
    _seed(mine, blocked + question + "- **`RT-S3` — a late slice** · group: p · READY 2026-11-12\n")
    done = ["close", "RT-S3", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-12", "--repo", str(mine),
            "--no-commit"]
    assert work_row.main(done) == 0, capsys.readouterr().err
    assert blocked in (mine / NOTE).read_text(encoding="utf-8")
    _seed(mine, "- **`TASK-P` — Pills on the board** · task: p · DECISION 2026-11-12: build pills at all?\n"
          + "- **`RT-S3` — a late slice** · group: p · READY 2026-11-12\n")
    assert work_row.main(done) == work_row.EXIT_REFUSED
    assert "which is DECISION 2026-11-12" in capsys.readouterr().err


def test_an_answered_question_readies_its_task_and_drops_the_tasks_recommend(clones, tmp_path, monkeypatch):
    """RT-QUEUE-LIVE-CHECK-STATUS. KILLING MUTATION: keep ``Recommend:`` segments in ``_rewrite_status`` -> the READY
    task still reads ``Recommend: answer `RT-S2```, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, "- **`TASK-P` — Pills on the board** · task: p · BLOCKED 2026-11-12: owner decision — `RT-S2` every "
                "live subtask waits (1 on the owner); the task turns READY when one of them does · "
                "Recommend: answer `RT-S2`\n"
                "- **`RT-S2` — which pill** · group: p · DECISION 2026-11-12: round or square? · Recommend: round\n"
                "- **`RT-S3` — the pill** · group: p · BLOCKED 2026-11-12: another lane — `RT-S2` the shape\n")
    assert work_row.main(["close", "RT-S2", "--who", "r", "--owner", "round", "--date", "2026-11-13",
                          "--repo", str(mine), "--no-commit"]) == 0
    text = (mine / NOTE).read_text(encoding="utf-8")
    assert ("- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-13 · unblocked 2026-11-13: `RT-S2` closed "
            "by the owner\n") in text


def test_an_owner_block_of_the_tasks_own_stays_when_a_subtask_wakes(clones, tmp_path, monkeypatch):
    """KILLING MUTATION: drop the owner guard in ``task_status_after_close`` -> TASK-P turns READY, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, OWED + "- **`RT-S1` — waits** · group: p · BLOCKED 2026-11-09: another lane — `RT-A` the fix\n")
    assert work_row.main(["close", "RT-A", "--who", "r", "--done", "3f9c2a1", "--allow-unlanded", "--repo", str(mine),
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
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--repo", str(mine),
                          "--no-commit"]) == work_row.EXIT_REFUSED
    assert "(TASK TITLE" in capsys.readouterr().err and "RT-S1" in (mine / NOTE).read_text(encoding="utf-8")
