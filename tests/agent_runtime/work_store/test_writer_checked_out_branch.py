"""A local board's write never moves a branch under the worktree that has it checked out.

RT-CREATE-BRAIN-MOVES-CHECKED-OUT-BRANCH (found live 2026-11-06, Eternia w1106b-live-a): Create brain on a
local slot whose checkout had ``main`` checked out moved ``refs/heads/main`` with ``update-ref``; the
checkout's index and files stayed behind and ``git status`` showed the new brain as staged deletions.
Real git on temp repos, no remote: the write now fast-forwards THROUGH that checkout, keeping the user's
own changes, or refuses ``worktree_dirty`` with ``main`` unmoved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.work import store as work_store
from agent_runtime.work_store.reasons import Reason, WorkRefused
from work_store_support import bind_here, declare_slots

ID = ("-c", "user.name=t", "-c", "user.email=t@t.invalid")
TODO = "Work_Brain/TODO.md"
QUEUE = "Work_Brain/20 — Active Initiatives/work-queue.md"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *ID, "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def status(repo: Path) -> list[str]:
    return sorted(git(repo, "-c", "core.quotePath=false", "status", "--porcelain").splitlines())


@pytest.fixture
def user(tmp_path, workspace) -> SimpleNamespace:
    """The user's own repository, no remote, ``main`` checked out, bound as a local slot ``mine``."""

    repo = tmp_path / "mine"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("mine\n", encoding="utf-8")
    (repo / "notes.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    declare_slots(workspace, {"name": "mine", "repo": {"local": True, "default_branch": "main"}})
    bind_here(workspace, mine=repo)
    return SimpleNamespace(repo=repo, scope=SimpleNamespace(workspace_id=workspace), seed=git(repo, "rev-parse", "HEAD"))


def create(user: SimpleNamespace) -> dict:
    return work_store.create_brain(user.scope, {"request_id": "brain-1", "slot": "mine"}, "operator")


def test_create_brain_fast_forwards_the_checkout_that_has_main_and_keeps_the_users_changes(user):
    """Killing mutation: ``advance`` back to a bare ``update-ref`` (``holder_of`` answers None) -> the
    checkout reads ``D  Work_Brain/TODO.md`` / ``D  …/work-queue.md`` and its files are absent."""

    (user.repo / "notes.txt").write_text("two\n", encoding="utf-8")
    git(user.repo, "add", "notes.txt")                                # a staged change of the user's
    (user.repo / "README.md").write_text("mine, edited\n", encoding="utf-8")  # an unstaged one
    (user.repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")   # an untracked file
    made = create(user)
    tip = git(user.repo, "rev-parse", "main").strip()
    assert made["receipt"]["commit"] == tip != user.seed.strip()
    assert git(user.repo, "rev-parse", "HEAD").strip() == tip
    assert status(user.repo) == [" M README.md", "?? scratch.txt", "M  notes.txt"]
    assert (user.repo / TODO).is_file() and (user.repo / QUEUE).is_file()
    assert (user.repo / "notes.txt").read_text(encoding="utf-8") == "two\n"


def test_a_change_in_the_fast_forwards_way_refuses_and_moves_nothing(user):
    """The user's own untracked ``Work_Brain/TODO.md``: refused ``worktree_dirty`` naming the checkout;
    ``main`` stays at the seed and the user's file is untouched. Killing mutation: ignore the merge's
    failure (return True) -> ``main`` stays but the write reports a commit the checkout never took."""

    (user.repo / "Work_Brain").mkdir()
    (user.repo / TODO).write_text("the user's own\n", encoding="utf-8")
    with pytest.raises(WorkRefused) as refused:
        create(user)
    assert refused.value.reason is Reason.WORKTREE_DIRTY and str(user.repo) in refused.value.detail
    assert git(user.repo, "rev-parse", "main") == user.seed
    assert (user.repo / TODO).read_text(encoding="utf-8") == "the user's own\n"
    assert status(user.repo) == ["?? Work_Brain/"]


def test_a_branch_being_rebased_refuses_and_moves_nothing(user):
    """``main`` mid-rebase (HEAD detached): moving it would break the rebase. Killing mutation: drop the
    ``detached`` arm of ``holder_of`` -> ``update-ref`` moves ``main`` under the rebase."""

    git(user.repo, "switch", "-q", "-c", "side", "HEAD")
    (user.repo / "side.txt").write_text("side\n", encoding="utf-8")
    git(user.repo, "add", "side.txt")
    git(user.repo, "commit", "-q", "-m", "side")
    git(user.repo, "switch", "-q", "main")
    (user.repo / "notes.txt").write_text("main's\n", encoding="utf-8")
    git(user.repo, "commit", "-q", "-am", "main")
    (user.repo / "side.txt").write_text("conflicts\n", encoding="utf-8")
    git(user.repo, "add", "side.txt")
    git(user.repo, "commit", "-q", "-m", "conflicting")
    before = git(user.repo, "rev-parse", "main")
    rebase = subprocess.run(["git", *ID, "-C", str(user.repo), "rebase", "-q", "side"], capture_output=True, text=True)
    assert rebase.returncode != 0  # stopped on the conflict, main is being rebased
    with pytest.raises(WorkRefused) as refused:
        create(user)
    assert refused.value.reason is Reason.WORKTREE_DIRTY and "rebased" in refused.value.detail
    assert git(user.repo, "rev-parse", "main") == before


def test_a_branch_no_worktree_holds_still_moves_by_compare_and_swap(user):
    """The checkout sits on another branch: ``main`` moves by ``update-ref`` and the checkout is untouched."""

    git(user.repo, "switch", "-q", "-c", "elsewhere")
    made = create(user)
    assert git(user.repo, "rev-parse", "main").strip() == made["receipt"]["commit"]
    assert git(user.repo, "rev-parse", "HEAD") == user.seed
    assert status(user.repo) == [] and not (user.repo / "Work_Brain").exists()
