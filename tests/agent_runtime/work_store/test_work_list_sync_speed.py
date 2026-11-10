"""A lifecycle ``runtime.work.list`` stays fast as boards are bound, and returns what it always did.

RT-WORK-LIST-SYNC-SERIAL-BOARDS (launcher rows COMP-WORK-PILL-REFRESH-RECONCILIATION-PAST-HALF and
COMP-WORK-REFRESH-OWNER-SIZE-PAST-HALF): the list synced every bound board one after another and ran one
``git log`` per queue note on every call — 7.4–8.3 s for four boards and 960 rows on a loaded box. Now the
boards sync at once (one thread per git repository), a worktree already in place skips ``worktree prune``,
and a note's commit time is remembered per tip, advanced from the new commits when the tip moves.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import git_cmd
from agent_runtime.work import store as work_store
from agent_runtime.workspace_slots import bind, declare

T0 = "2026-11-10T10:00:00+00:00"
BRAIN = "Launcher_Brain/20 — Active Initiatives"
#: Every test builds bare origins and clones and lists through real git: slow on a loaded box.
pytestmark = pytest.mark.timeout(180)

HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _commit(clone: Path, message: str, when: int) -> None:
    env_date = f"{when} +0000"
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message],
                   cwd=clone, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_DATE": env_date, "GIT_COMMITTER_DATE": env_date})


def _row(row_id: str) -> str:
    return f"- **`{row_id}` — a row** · READY 2026-11-10\n"


def _repo(tmp_path: Path, name: str) -> SimpleNamespace:
    """A bare origin and a clone of it holding a brain of two queue notes, ``a.md`` and ``b.md``."""

    origin = tmp_path / f"{name}.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / name
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    (clone / BRAIN).mkdir(parents=True)
    for note in ("a", "b"):
        (clone / BRAIN / f"{note}.md").write_text(HEAD + _row(f"{name.upper()}-{note.upper()}1"), encoding="utf-8",
                                                  newline="\n")
    git("add", "-A", cwd=clone)
    _commit(clone, "seed", 1_700_000_000)
    git("push", "-q", "origin", "main", cwd=clone)
    return SimpleNamespace(origin=origin, clone=clone, url=f"https://example.com/{name}.git")


def _bound(workspace: str, **repos: SimpleNamespace) -> SimpleNamespace:
    declare(workspace, [{"name": name, "repo": {"clone_url": repo.url, "default_branch": "main"}}
                        for name, repo in repos.items()], issued_at=T0, machine="m")
    for name, repo in repos.items():
        bind(workspace, name, str(repo.clone), issued_at=T0)
    return SimpleNamespace(workspace_id=workspace)


def _git_calls(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    real = git_cmd.run_git

    def run(args, *rest, **kwargs):
        seen.append(list(args))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(git_cmd, "run_git", run)
    return seen


def _times(listed: dict, slot: str) -> dict[str, int | None]:
    (board,) = [b for b in listed["boards"] if b["slot"] == slot]
    out = {"<board>": board["committed_at"]}
    for queue in board["queues"]:
        (stamp,) = {row["updated_at"] for row in queue["rows"]}
        out[queue["note"].rsplit("/", 1)[-1]] = stamp
    return out


def test_bound_boards_sync_at_once_and_list_in_board_order(tmp_path, workspace, monkeypatch):
    """Mutation: run the batches one after another in ``synced`` (no pool) -> at most one sync at a time, red."""
    scope = _bound(workspace, alpha=_repo(tmp_path, "alpha"), beta=_repo(tmp_path, "beta"))
    work_store.list_work(scope, {})
    live, peak, lock = [0], [0], threading.Lock()
    real = work_store.Writer.sync

    def sync(self, *args, **kwargs):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        try:
            time.sleep(0.3)
            return real(self, *args, **kwargs)
        finally:
            with lock:
                live[0] -= 1

    monkeypatch.setattr(work_store.Writer, "sync", sync)
    listed = work_store.list_work(scope, {})
    assert peak[0] >= 2
    assert [board["slot"] for board in listed["boards"]] == ["alpha", "beta"]
    assert all(board["refused"] is None and board["readable"] for board in listed["boards"])


def test_boards_of_one_repository_sync_one_after_another(tmp_path, workspace, monkeypatch):
    """Two boards keyed by one checkout share its fetch: never synced at once.
    Mutation: group by ``board.key`` instead of ``checkout_key`` -> both sync together, red."""
    scope = _bound(workspace, alpha=_repo(tmp_path, "alpha"), beta=_repo(tmp_path, "beta"))
    work_store.list_work(scope, {})
    monkeypatch.setattr(work_store.Writer, "checkout_key", property(lambda self: "one-repository"))
    live, peak, lock = [0], [0], threading.Lock()
    real = work_store.Writer.sync

    def sync(self, *args, **kwargs):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        try:
            time.sleep(0.3)
            return real(self, *args, **kwargs)
        finally:
            with lock:
                live[0] -= 1

    monkeypatch.setattr(work_store.Writer, "sync", sync)
    listed = work_store.list_work(scope, {})
    assert peak[0] == 1 and [b["readable"] for b in listed["boards"]] == [True, True]


def test_a_board_this_thread_holds_syncs_here_not_in_a_waiting_thread(tmp_path, workspace, monkeypatch):
    """Mutation: drop the ``held_here`` arm -> a pool thread waits on this thread's admission, refused, red."""
    from agent_runtime import locks

    scope = _bound(workspace, alpha=_repo(tmp_path, "alpha"), beta=_repo(tmp_path, "beta"))
    work_store.list_work(scope, {})
    monkeypatch.setattr(locks, "_lock_timeout_seconds", lambda value: 0.5)
    held = work_store.synced(workspace).writers["alpha"]
    with held.admitted():
        listed = work_store.list_work(scope, {})
    assert [(b["slot"], b["refused"]) for b in listed["boards"]] == [("alpha", None), ("beta", None)]


def test_a_list_at_an_unmoved_tip_asks_git_no_log_and_no_prune(tmp_path, workspace, monkeypatch):
    """Mutation: drop the remembered times (always ``_log_committed_at``) -> a ``log`` per note, red;
    run ``worktree prune`` before the in-place check -> a prune per board, red."""
    scope = _bound(workspace, alpha=_repo(tmp_path, "alpha"), beta=_repo(tmp_path, "beta"))
    first = work_store.list_work(scope, {})
    calls = _git_calls(monkeypatch)
    again = work_store.list_work(scope, {})
    assert again["boards"] == first["boards"]
    assert [args for args in calls if args[0] == "log"] == []
    assert [args for args in calls if args[:2] == ["worktree", "prune"]] == []
    assert sum(1 for args in calls if args[0] == "fetch") == 2  # freshness unchanged: every board still fetches


def _push_from(tmp_path: Path, repo: SimpleNamespace, name: str) -> Path:
    other = tmp_path / name
    git("clone", "-q", str(repo.origin), str(other), cwd=tmp_path)
    return other


def test_a_moved_tip_lists_the_same_times_a_cold_read_gives(tmp_path, workspace, monkeypatch):
    """A teammate's commits move the tip: the touched note's time moves, the untouched one's stays, and both
    equal what a fresh ``git log -n 1`` says; a merge on the way falls back to the cold read.
    Mutation: keep the old time for a touched note in ``_advanced`` -> ``a.md`` lists the seed's time, red."""
    alpha = _repo(tmp_path, "alpha")
    scope = _bound(workspace, alpha=alpha)
    seed = _times(work_store.list_work(scope, {}), "alpha")
    assert seed == {"<board>": 1_700_000_000, "a.md": 1_700_000_000, "b.md": 1_700_000_000}

    mate = _push_from(tmp_path, alpha, "mate")
    (mate / BRAIN / "a.md").write_text(HEAD + _row("ALPHA-A1") + _row("ALPHA-A2"), encoding="utf-8", newline="\n")
    git("add", "-A", cwd=mate)
    _commit(mate, "a row", 1_700_000_500)
    (mate / "README.md").write_text("outside the brain\n", encoding="utf-8")
    git("add", "-A", cwd=mate)
    _commit(mate, "readme", 1_700_000_900)
    git("push", "-q", "origin", "main", cwd=mate)
    calls = _git_calls(monkeypatch)
    moved = _times(work_store.list_work(scope, {}), "alpha")
    assert moved == {"<board>": 1_700_000_500, "a.md": 1_700_000_500, "b.md": 1_700_000_000}
    assert [args for args in calls if args[0] == "log" and "-n" in args and args[args.index("-n") + 1] == "1"] == []

    git("checkout", "-q", "-b", "side", cwd=mate)
    (mate / BRAIN / "b.md").write_text(HEAD + _row("ALPHA-B1") + _row("ALPHA-B2"), encoding="utf-8", newline="\n")
    git("add", "-A", cwd=mate)
    _commit(mate, "b on a side", 1_700_001_000)
    git("checkout", "-q", "main", cwd=mate)
    (mate / "NOTES.md").write_text("main moves too\n", encoding="utf-8")
    git("add", "-A", cwd=mate)
    _commit(mate, "main", 1_700_001_100)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-ff", "-m", "merge", "side"],
                   cwd=mate, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_DATE": "1700001200 +0000",
                        "GIT_COMMITTER_DATE": "1700001200 +0000"})
    git("push", "-q", "origin", "main", cwd=mate)
    merged = _times(work_store.list_work(scope, {}), "alpha")
    worktree = work_store.synced(workspace).writers["alpha"].worktree
    cold = {name: int(git("log", "-n", "1", "--format=%ct", "origin/main", "--", path, cwd=worktree).strip())
            for name, path in (("<board>", BRAIN), ("a.md", f"{BRAIN}/a.md"), ("b.md", f"{BRAIN}/b.md"))}
    assert merged == cold and merged["b.md"] == 1_700_001_000


def test_a_long_run_of_new_commits_reads_each_note_again(tmp_path, workspace, monkeypatch):
    """Past ``ADVANCE_LIMIT`` new commits the remembered times are dropped, never half-advanced.
    Mutation: ignore the limit -> no cold ``log -n 1`` after two new commits, red."""
    from agent_runtime.work_store import writer as writer_module

    alpha = _repo(tmp_path, "alpha")
    scope = _bound(workspace, alpha=alpha)
    work_store.list_work(scope, {})
    monkeypatch.setattr(writer_module, "ADVANCE_LIMIT", 1)
    mate = _push_from(tmp_path, alpha, "mate")
    for n, stamp in ((1, 1_700_000_100), (2, 1_700_000_200)):
        (mate / BRAIN / "a.md").write_text(HEAD + _row("ALPHA-A1") + _row(f"ALPHA-A{n + 1}"), encoding="utf-8",
                                          newline="\n")
        git("add", "-A", cwd=mate)
        _commit(mate, f"a{n}", stamp)
    git("push", "-q", "origin", "main", cwd=mate)
    calls = _git_calls(monkeypatch)
    moved = _times(work_store.list_work(scope, {}), "alpha")
    assert moved == {"<board>": 1_700_000_200, "a.md": 1_700_000_200, "b.md": 1_700_000_000}
    assert len([args for args in calls if args[0] == "log" and args[1:3] == ["-n", "1"]]) == 3
