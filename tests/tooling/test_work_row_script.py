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
    to rebase. Mutation: drop the ``HEAD~1`` ancestor check -> the local commit is reset away, red. The other
    commit changes nothing (a commit with work in it is refused before the op, the test below)."""
    origin, mine, other = clones
    _other_session_pushes(other)
    git("commit", "-q", "--allow-empty", "-m", "lane work", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 3
    assert "fetch, then re-run" in capsys.readouterr().err
    assert git("log", "-2", "--format=%s", cwd=mine).split("\n")[:2] == ["queue: claim RT-A r-lane", "lane work"]
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "other session"


def test_an_op_on_a_branch_with_unlanded_work_is_refused_naming_it(clones, capsys):
    """RT-QUEUE-ROW-OP-CARRIES-UNLANDED-COMMITS-TO-MAIN: every op pushed ``HEAD``, so a claim made on a lane branch
    holding an unchecked code commit took it to ``main`` with the row. Now it is refused before anything is
    written, naming the commit; ``--no-push`` still commits the op for the lane's own landing to push.
    KILLING MUTATION: ``carried_commits`` returns None at its first check -> exit 0 and origin's main carries
    "lane work", red (recorded in the commit)."""
    origin, mine, _ = clones
    before_tip = git("rev-parse", "main", cwd=origin)
    (mine / "README.md").write_text("a lane's own unchecked work\n", encoding="utf-8")
    git("commit", "-q", "-am", "lane work", cwd=mine)
    before = (mine / NOTE).read_bytes()
    for argv in (["claim", "RT-A"], ["close", "RT-A", "--owner", "dropped"]):
        assert work_row.main([*argv, "--who", "r-lane", "--repo", str(mine)]) == work_row.EXIT_REFUSED
        err = capsys.readouterr().err
        assert "unlanded_commits" in err and "lane work" in err and "--no-push" in err
        assert (mine / NOTE).read_bytes() == before
    assert git("rev-parse", "main", cwd=origin) == before_tip
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--no-push", "--repo", str(mine)]) == 0
    assert git("log", "-2", "--format=%s", cwd=mine).split("\n")[:2] == ["queue: claim RT-A r-lane", "lane work"]
    assert git("rev-parse", "main", cwd=origin) == before_tip


def test_an_op_after_a_local_merge_of_main_or_behind_a_peer_is_not_refused(clones):
    """Only work of the checkout's own is refused: a merge of the target that adds nothing, and a tracking ref a
    peer's push left behind (one fetch answers it), push as before."""
    origin, mine, other = clones
    _other_session_pushes(other)
    git("checkout", "-q", "-b", "wave/lane", cwd=mine)
    git("fetch", "-q", "origin", cwd=mine)
    git("merge", "-q", "--no-ff", "-m", "merge main", "origin/main", cwd=mine)
    git("checkout", "-q", "--detach", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue: claim RT-A r-lane"
    git("pull", "-q", "--ff-only", cwd=other)
    (other / "README.md").write_text("peer\n", encoding="utf-8")
    git("commit", "-q", "-am", "peer work", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    git("fetch", "-q", "origin", cwd=mine)
    git("checkout", "-q", "--detach", "origin/main", cwd=mine)
    git("update-ref", "refs/remotes/origin/main", "HEAD~1", cwd=mine)  # the tracking ref one push behind
    assert work_row.main(["claim", "RT-B", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue: claim RT-B r-lane"


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
    assert verbs == {"add", "commit", "diff", "push", "symbolic-ref"}
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


def test_handoff_adds_one_dated_segment_before_the_claim(clones, capsys):
    """RT-QUEUE-ROW-HANDOFF-HAS-NO-COMMAND. KILLING MUTATIONS: write the segment after the claim mark
    (``line + handoff``) -> the claim is no longer the row's last segment, red; drop the segment count in
    ``handoff_line`` -> a text carrying the separator is written as two segments, red."""
    origin, mine, _ = clones
    claimed = ("- **`RT-A` — first** · READY 2026-10-18 · **TAKEN 2026-11-12 lane on box as me in wt**\n"
               "- **`RT-B` — second** · READY 2026-10-18\n")
    (mine / NOTE).write_text(HEAD + claimed, encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", "claimed", cwd=mine)
    git("push", "-q", cwd=mine)
    handoff = ["handoff", "RT-A", "--who", "r-lane", "--date", "2026-11-12", "--repo", str(mine)]
    assert work_row.main([*handoff, "--text", "found  the cause; half built (seen live); likely fix: `x`"]) == 0
    assert (mine / NOTE).read_text(encoding="utf-8") == HEAD + (
        "- **`RT-A` — first** · READY 2026-10-18 · handoff 2026-11-12 (r-lane): found the cause; half built (seen "
        "live); likely fix: `x` · **TAKEN 2026-11-12 lane on box as me in wt**\n- **`RT-B` — second** · READY 2026-10-18\n")
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue: handoff RT-A r-lane"
    before = (mine / NOTE).read_text(encoding="utf-8")
    for bad in ("one · two", "", "an open `span"):
        assert work_row.main([*handoff, "--text", bad, "--no-commit"]) == work_row.EXIT_REFUSED, bad
    assert "a handoff is ONE segment" in capsys.readouterr().err
    assert (mine / NOTE).read_text(encoding="utf-8") == before


def test_no_push_commits_the_op_and_pushes_nothing(clones):
    """RT-QUEUE-ROW-OP-PUSHES-BEFORE-THE-LANES-CHECKS. KILLING MUTATION: drop the ``no_push`` return in
    ``commit_and_push`` -> the claim is on origin's main, red. The default still pushes
    (``test_claim_by_id_commits_by_pathspec_and_pushes``)."""
    origin, mine, _ = clones
    tip = git("rev-parse", "main", cwd=origin)
    assert work_row.main(["claim", "RT-A", "--who", "lane", "--machine", "box", "--account", "me", "--worktree", "wt",
                          "--repo", str(mine), "--no-push"]) == 0
    assert git("log", "-1", "--format=%s", cwd=mine).strip() == "queue: claim RT-A lane"
    assert git("status", "--porcelain", cwd=mine) == ""
    assert git("rev-parse", "main", cwd=origin) == tip


PLACED = ("---\ntype: queue\nprogram: test\n---\n\n## Tasks — the tasks\n\n"
          "- **`TASK-P` — Pills on the board** · task: p · READY 2026-11-09\n"
          "- **`TASK-Q` — Quiet mode** · task: q · READY 2026-11-09\n\n## Open\n\n"
          "- **`RT-S1` — first slice** · group: p · READY 2026-11-09\n"
          "- **`RT-Q1` — a quiet slice** · group: q · READY 2026-11-09\n\n## Later — 2026-11-10\n\n"
          "- **`RT-Q2` — another quiet slice** · group: q.x · READY 2026-11-09\n")


def test_append_puts_a_row_beside_its_tasks_other_rows(clones, tmp_path, monkeypatch, capsys):
    """RT-QUEUE-ROW-APPEND-LANDS-AT-THE-BOTTOM-OF-THE-NOTE (three filings of 2026-11-12 landed under an old dated
    heading; with no ``--note`` they went to the first queue note found). KILLING MUTATIONS: drop the own-rows arm
    of ``appended_text`` -> RT-S2 lands at the end of q.md, red; ``_home_note`` returns None -> it lands in a.md,
    red; drop the Tasks arm -> TASK-N lands at the end, red; ``_after_section`` returns the heading's own line for
    a section with rows -> RT-U lands above RT-Q2, red."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    first = mine / "Harness_Brain/20 — Active Initiatives/a.md"
    first.write_text(HEAD + "- **`TASK-Z` — Zed** · task: z · READY 2026-11-09\n"
                     "- **`RT-Z1` — a zed slice** · group: z · READY 2026-11-09\n", encoding="utf-8", newline="\n")
    (mine / NOTE).write_text(PLACED, encoding="utf-8", newline="\n")

    def append(row_id: str, tail: str, *more: str) -> int:
        return work_row.main(["append", row_id, "--who", "r", "--row", f"- **`{row_id}` — new** · {tail} · READY 2026-11-12",
                              "--repo", str(mine), "--no-commit", *more])

    def order(path: Path) -> list[str]:
        return [row.ref.id for row in work_row.parse_note(path.read_text(encoding="utf-8"), slot="", note="")]

    assert append("RT-S2", "group: p.x") == 0
    assert append("TASK-N", "task: n", "--note", NOTE) == 0
    assert append("RT-N1", "group: n", "--note", NOTE) == 0, "no row of its task yet: the end of the note"
    assert append("RT-U", "group: q", "--under", "Later") == 0
    assert order(mine / NOTE) == ["TASK-P", "TASK-Q", "TASK-N", "RT-S1", "RT-S2", "RT-Q1", "RT-Q2", "RT-N1", "RT-U"]
    assert (mine / NOTE).read_text(encoding="utf-8").endswith("· READY 2026-11-12\n")
    assert order(first) == ["TASK-Z", "RT-Z1"]
    assert append("RT-Z2", "group: z") == 0
    assert order(first) == ["TASK-Z", "RT-Z1", "RT-Z2"]
    assert append("RT-V", "group: q", "--under", "No such heading") == work_row.EXIT_REFUSED
    assert "--under: no heading of the note starts with `No such heading`" in capsys.readouterr().err


HELD = ("- **`RT-H` — the switch-over** · BLOCKED 2026-11-01: another lane — `RT-A` then `RT-B`, `RT-GONE` and "
        "`RT-C`: only when all are on main and `OWED_HANDLERS` is empty · filed by a lane\n"
        "- **`RT-C` — third** · READY 2026-10-18\n")


def test_a_close_keeps_a_row_other_rows_still_hold_blocked(clones, capsys):
    """RT-QUEUE-CLOSE-WAKES-ROW-STILL-HELD-BY-OTHERS (three closes of 2026-11-12 woke a row five others held).
    KILLING MUTATIONS: ``still_open = []`` in ``wake_dependents`` -> RT-H is READY after the first close, red;
    match only the list's first ID (``closed_id != listed[1][0]``) -> closing RT-C, a later blocker, leaves it on the list, red."""
    _, mine, _ = clones
    (mine / NOTE).write_text(HEAD + ROWS + HELD, encoding="utf-8", newline="\n")
    close = ["--who", "r", "--owner", "done elsewhere", "--date", "2026-11-03", "--repo", str(mine), "--no-commit"]

    def held_row() -> str:
        return next(line for line in (mine / NOTE).read_text(encoding="utf-8").split("\n") if "`RT-H`" in line)

    assert work_row.main(["close", "RT-A", *close]) == 0
    assert held_row() == ("- **`RT-H` — the switch-over** · BLOCKED 2026-11-01: another lane — `RT-B` then `RT-C`: only "
                          "when all are on main and `OWED_HANDLERS` is empty · filed by a lane"), "RT-GONE is no row"
    assert capsys.readouterr().out == ("`RT-H` stays BLOCKED: it also waits on `RT-B`, `RT-C`, still open (`RT-A` is "
                                       "off its list)\n")
    assert work_row.main(["close", "RT-C", *close]) == 0
    assert "another lane — `RT-B`: only when all" in held_row()
    capsys.readouterr()
    assert work_row.main(["close", "RT-B", *close]) == 0
    assert held_row() == ("- **`RT-H` — the switch-over** · READY 2026-11-03 · unblocked 2026-11-03: `RT-B` closed by "
                          "the owner · filed by a lane")
    assert capsys.readouterr().out == "woke `RT-H`: READY (it waited on `RT-B`)\n"


def test_no_wake_still_takes_the_archived_row_off_a_list_and_names_a_row_it_strands(clones, capsys):
    """The other half: a ``--no-wake`` close left a row naming an archived blocker first and the queue gate red on
    main (6d7b7e554f). KILLING MUTATIONS: ``if still_open and wake`` -> RT-H still names RT-A, red; drop the
    ``stranded`` report -> no warning for RT-W, red. RT-W itself is left as it stands: that is what the flag asks."""
    _, mine, _ = clones
    lone = "- **`RT-W` — waits on one** · BLOCKED 2026-11-01: hermes — `RT-A` first\n"
    (mine / NOTE).write_text(HEAD + ROWS + HELD + lone, encoding="utf-8", newline="\n")
    assert work_row.main(["close", "RT-A", "--who", "r", "--owner", "x", "--no-wake", "--repo", str(mine),
                          "--no-commit"]) == 0
    text = (mine / NOTE).read_text(encoding="utf-8")
    assert "· BLOCKED 2026-11-01: another lane — `RT-B` then `RT-C`: only when" in text
    assert lone in text
    said = capsys.readouterr()
    assert "`RT-H` stays BLOCKED" in said.out and "RT-W" not in said.out
    assert said.err.startswith("warning: `RT-W` is left BLOCKED on `RT-A`, which this close archives (--no-wake)")


def test_only_the_rows_a_block_opens_with_are_its_blockers():
    """KILLING MUTATION: let ``_NEXT_BLOCKER`` match a bare space before the next backticked name -> the prose's
    ``RT-B`` joins the list, red."""
    from agent_runtime.work_store.wake import blocker_list

    assert blocker_list("another lane — `RT-A` then `RT-B`, `RT-C`, and `RT-D` & `RT-E` + `RT-F`: why `RT-Z`") == (
        "another lane — ", ["RT-A", "RT-B", "RT-C", "RT-D", "RT-E", "RT-F"], ": why `RT-Z`")
    assert blocker_list("hermes — `RT-A` the fix, which `RT-B` also wants") == (
        "hermes — ", ["RT-A"], " the fix, which `RT-B` also wants")
    assert blocker_list("another lane — `RT-A` `RT-B`")[1] == ["RT-A"]
    assert blocker_list("owner decision — which one?") is None


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


FOLLOW_UPS = ("- **`TASK-P-FOLLOWUPS` — What the pills found on the way** · task: p-followups · READY 2026-11-09\n"
              "- **`RT-F1` — a loose end** · group: p-followups · READY 2026-11-09\n"
              "- **`RT-F2` — a parked one** · group: p-followups.x · DEFERRED 2026-11-09: later\n")


def test_closing_a_task_lists_its_open_follow_up_rows(clones, tmp_path, monkeypatch, capsys):
    """Launcher row QA-TASK-CLOSE-SHOWS-ITS-FOLLOW-UP-ROWS (its twin: ``close_row.dart::_listFollowUps``). KILLING
    MUTATION: drop ``follow_up_lines`` from ``close_task``'s return -> the read-them-together line and the three
    rows are not printed, red. A close that archives no task prints none of it."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path, "- **`L-F` — a launcher loose end** · group: p-followups · READY 2026-11-09\n")
    _seed(mine, TASK_ROWS + FOLLOW_UPS)
    close = ["--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-09", "--repo", str(mine)]
    assert work_row.main(["close", "RT-S1", *close]) == 0
    assert "follow-up" not in capsys.readouterr().out, "TASK-P is still open: nothing to read yet"
    assert work_row.main(["close", "RT-S2", *close]) == 0
    assert capsys.readouterr().out.split("\n")[-5:] == [
        "task `TASK-P` is closed with 3 follow-up row(s) open under `p-followups` — read them together now: one "
        "that is a defect in what this task built goes back into the task, which reopens for it",
        "  `RT-F1` — a loose end (hermes, q.md)",
        "  `RT-F2` — a parked one (hermes, q.md)",
        "  `L-F` — a launcher loose end (launcher, mission-control-queue.md)",
        ""]


def test_closing_a_task_with_no_follow_up_rows_prints_nothing_about_them(clones, tmp_path, monkeypatch, capsys):
    """KILLING MUTATION: return the read-them-together line from ``follow_up_lines`` when it found no row -> a
    line naming 0 rows is printed, red. Another task's follow-up rows are not this task's."""
    monkeypatch.delenv("ETERNIA_WORKSPACE_ROOTS", raising=False)
    _, mine, _ = clones
    _siblings(tmp_path)
    _seed(mine, TASK_ROWS.replace("- **`RT-S2` — second slice** · group: p.x · READY 2026-11-09\n", "")
          + FOLLOW_UPS.replace("p-followups", "pp-followups"))
    assert work_row.main(["close", "RT-S1", "--who", "r", "--done", "1a2b3c4", "--allow-unlanded", "--date", "2026-11-09",
                          "--repo", str(mine), "--no-commit"]) == 0
    assert capsys.readouterr().out == "closed task `TASK-P` DONE 2026-11-09 1a2b3c4: all 1 subtasks closed\n"


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
