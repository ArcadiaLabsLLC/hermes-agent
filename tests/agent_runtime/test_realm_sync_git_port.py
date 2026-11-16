"""The realm-sync git port's contract (``agent_runtime.realm_sync.git_port.SyncGit``), held per backend.

Every test runs once per backend through the ``sync_git_backend`` fixture and asks
``agent_runtime.realm_sync.git.sync_git`` for the port, so a second backend answers the same
contract (plan ``docs/agent-runtime-harness/planned/phone-realm-sync-dulwich-2026-11-16.md`` §3, §5).
Real repositories in ``tmp_path``; the FIXTURES build remotes and teammates' commits with the git
program, the code under test answers through the port.

Killing mutation (recorded in the S1 commit): swap ``ahead`` and ``behind`` in
``git_binary.BinarySyncGit.state`` -> ``test_state_counts_ahead_and_behind_apart`` reds.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime.realm_sync.git import SYNC_IDENTITY, sync_git
from agent_runtime.realm_sync.git_port import FetchOutcome, PushOutcome, RepoState
from agent_runtime.realm_sync.models import RealmSyncError

pytestmark = pytest.mark.usefixtures("sync_git_backend")
# A test the DULWICH arm cannot run yet is named in ``conftest.DULWICH_NOT_YET`` (shrink-only).

_TEAMMATE = ("-c", "user.name=Teammate", "-c", "user.email=teammate@example.invalid")


def _sh(cwd: Path, *args: str) -> str:
    """The FIXTURE's git (a teammate's machine), never the code under test."""

    proc = subprocess.run(["git", *_TEAMMATE, "-c", "init.defaultBranch=main", *args], cwd=cwd,
                          capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit_file(cwd: Path, rel: str, text: str, message: str) -> str:
    path = cwd / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _sh(cwd, "add", "--", rel)
    _sh(cwd, "commit", "-q", "-m", message)
    return _sh(cwd, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare remote holding one commit on ``main`` (``realms/r/a.txt``)."""

    bare = tmp_path / "remote.git"
    _sh(tmp_path, "init", "-q", "--bare", str(bare))
    seed = tmp_path / "seed"
    _sh(tmp_path, "clone", "-q", str(bare), str(seed))
    _commit_file(seed, "realms/r/a.txt", "one\n", "seed")
    _sh(seed, "push", "-q", "origin", "HEAD:main")
    return bare


def _teammate_publishes(tmp_path: Path, bare: Path, rel: str, text: str, name: str = "mate") -> str:
    mate = tmp_path / name
    if not mate.exists():
        _sh(tmp_path, "clone", "-q", str(bare), str(mate))
    else:
        _sh(mate, "pull", "-q", "--ff-only")
    sha = _commit_file(mate, rel, text, f"{name} {rel}")
    _sh(mate, "push", "-q", "origin", "HEAD:main")
    return sha


def _clone(tmp_path: Path, bare: Path) -> Path:
    """The member's clone, made by the FIXTURE's git (``test_clone_tracks_the_remote_branch`` holds the verb)."""

    repo = tmp_path / "member"
    _sh(tmp_path, "clone", "-q", str(bare), str(repo))
    return repo


def _member_commits(repo: Path, rel: str, text: str, message: str = "member") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git = sync_git(repo)
    git.add([rel])
    git.commit(message)


def test_init_names_no_commit_and_rename_points_head(tmp_path):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    assert (repo / ".git").is_dir()
    assert git.resolve("HEAD") is None
    git.rename_branch("main")
    assert git.current_branch() == "main"
    assert git.remotes() == ()
    assert git.upstream() is None


def test_rename_moves_a_branch_that_has_commits(tmp_path):
    repo = tmp_path / "fresh"
    repo.mkdir()
    _sh(repo, "init", "-q", "-b", "master")
    sha = _commit_file(repo, "x.txt", "x\n", "first")
    git = sync_git(repo)
    git.rename_branch("main")
    assert git.current_branch() == "main"
    assert git.resolve("refs/heads/main") == sha
    assert git.resolve("refs/heads/master") is None


def test_clone_tracks_the_remote_branch(tmp_path, remote):
    repo = tmp_path / "member"
    git = sync_git(repo)
    git.clone(str(remote), None)
    assert (repo / "realms/r/a.txt").read_text(encoding="utf-8") == "one\n"
    assert git.current_branch() == "main"
    assert git.upstream() == "origin/main"
    assert git.remotes() == ("origin",)
    assert git.remote_url("origin") == str(remote)
    assert git.has_remote_refs()
    assert git.state() == RepoState(ahead=0, behind=0, conflicts=(), dirty=False)


def test_clone_of_nothing_refuses_typed(tmp_path):
    with pytest.raises(RealmSyncError) as refused:
        sync_git(tmp_path / "member").clone(str(tmp_path / "no-such.git"), None)
    assert refused.value.code == "sync_remote_unreachable"


def test_remote_remove_drops_the_tracking_refs(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    git = sync_git(repo)
    git.remote_remove("origin")
    assert git.remotes() == ()
    assert git.remote_url("origin") is None
    assert not git.has_remote_refs()
    assert git.resolve("refs/remotes/origin/main") is None
    with pytest.raises(RealmSyncError):
        git.remote_remove("origin")
    git.remote_remove("origin", missing_ok=True)
    git.remote_add("origin", str(remote))
    assert git.remote_url("origin") == str(remote)
    assert not git.has_remote_refs()  # added, never fetched


def test_state_counts_ahead_and_behind_apart(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    _teammate_publishes(tmp_path, remote, "realms/r/b.txt", "b\n")
    _teammate_publishes(tmp_path, remote, "realms/r/c.txt", "c\n")
    _member_commits(repo, "realms/r/mine.txt", "mine\n")
    git = sync_git(repo)
    _sh(repo, "fetch", "-q")
    state = git.state()
    assert (state.ahead, state.behind) == (1, 2)
    assert state.as_dict() == {"ahead": 1, "behind": 2, "conflicts": [], "dirty": False}


def test_state_without_upstream_counts_what_no_remote_holds(tmp_path, remote):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    git.rename_branch("main")
    _member_commits(repo, "x.txt", "x\n", "one")
    _member_commits(repo, "y.txt", "y\n", "two")
    assert git.state().ahead == 0  # no remote at all: nothing waits
    git.remote_add("origin", str(remote))
    assert git.upstream() is None
    assert git.state().ahead == 2


def test_changed_lists_tracked_and_untracked(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    git = sync_git(repo)
    assert git.changed() == ()
    (repo / "realms/r/a.txt").write_text("two\n", encoding="utf-8")
    (repo / "loose").mkdir()
    (repo / "loose/new.txt").write_text("n\n", encoding="utf-8")
    assert {(c.path, c.untracked) for c in git.changed()} == {("realms/r/a.txt", False), ("loose/", True)}
    assert {(c.path, c.untracked) for c in git.changed(untracked_all=True)} == {
        ("realms/r/a.txt", False), ("loose/new.txt", True)}
    assert [c.path for c in git.changed(["realms"])] == ["realms/r/a.txt"]
    assert git.state().dirty
    assert git.is_tracked("realms/r/a.txt")
    assert not git.is_tracked("loose/new.txt")


def test_commit_is_the_sync_identity_with_trailers(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    (repo / "realms/r/a.txt").write_text("two\n", encoding="utf-8")
    git = sync_git(repo)
    git.add(["realms"])
    git.commit("Publish realm sync r", ["Published-by: m-1"])
    author = _sh(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%B")
    name, email = (pair.partition("=")[2] for pair in SYNC_IDENTITY)
    who, committer, body = author.split("|", 2)
    assert who == committer == f"{name} <{email}>"
    assert body.strip() == "Publish realm sync r\n\nPublished-by: m-1"
    assert git.changed() == ()
    assert git.state().ahead == 1


def test_pull_fast_forward_takes_the_teammates_commit(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    sha = _teammate_publishes(tmp_path, remote, "realms/r/b.txt", "b\n")
    git = sync_git(repo)
    git.pull_fast_forward(None)
    assert git.resolve("HEAD") == sha
    assert (repo / "realms/r/b.txt").read_text(encoding="utf-8") == "b\n"


def test_merge_remote_theirs_takes_theirs_on_the_same_line(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    _teammate_publishes(tmp_path, remote, "realms/r/a.txt", "theirs\n")
    _member_commits(repo, "realms/r/a.txt", "ours\n")
    git = sync_git(repo)
    outcome = git.merge_remote_theirs(None)
    assert outcome.conflicts == ()
    assert (repo / "realms/r/a.txt").read_text(encoding="utf-8") == "theirs\n"
    assert git.state() == RepoState(ahead=2, behind=0, conflicts=(), dirty=False)


def test_merge_remote_theirs_lists_a_shape_conflict(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    mate = tmp_path / "mate"
    _sh(tmp_path, "clone", "-q", str(remote), str(mate))
    _sh(mate, "rm", "-q", "realms/r/a.txt")
    _sh(mate, "commit", "-q", "-m", "delete")
    _sh(mate, "push", "-q", "origin", "HEAD:main")
    _member_commits(repo, "realms/r/a.txt", "ours\n")
    outcome = sync_git(repo).merge_remote_theirs(None)
    assert outcome.conflicts == ("realms/r/a.txt",)
    assert sync_git(repo).state().conflicts == ("realms/r/a.txt",)


def test_push_sets_upstream_and_a_diverged_push_is_rejected(tmp_path, remote):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    git.rename_branch("main")
    bare = tmp_path / "empty.git"
    _sh(tmp_path, "init", "-q", "--bare", str(bare))
    git.remote_add("origin", str(bare))
    _member_commits(repo, "x.txt", "x\n")
    assert git.push(None, set_upstream=True).outcome is PushOutcome.PUSHED
    assert git.upstream() == "origin/main"
    assert git.state().ahead == 0

    theirs = _teammate_publishes(tmp_path, bare, "y.txt", "y\n")
    _member_commits(repo, "z.txt", "z\n")
    report = git.push(None, set_upstream=False)
    assert report.outcome is PushOutcome.REJECTED
    assert report.safe_details["git_args"] == ["push"]
    assert _sh(tmp_path, "--git-dir", str(bare), "rev-parse", "main") == theirs


def test_push_to_nowhere_refuses_typed(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    git = sync_git(repo)
    _member_commits(repo, "realms/r/x.txt", "x\n")
    _sh(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(RealmSyncError) as refused:
        git.push(None, set_upstream=False)
    assert refused.value.code == "sync_remote_unreachable"


def test_ancestry_and_history(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    git = sync_git(repo)
    first = git.resolve("HEAD")
    _member_commits(repo, "realms/r/b.txt", "b\n", "second")
    _member_commits(repo, "outside.txt", "o\n", "not the realm")
    head = git.resolve("HEAD")
    assert git.is_ancestor(first, "HEAD")
    assert not git.is_ancestor(head, first)
    entries = git.log(["HEAD"], "realms/r", 10)
    assert [e.paths for e in entries] == [("realms/r/b.txt",), ("realms/r/a.txt",)]
    assert entries[1].sha == first
    assert entries[0].author == SYNC_IDENTITY[0].partition("=")[2]
    assert entries[0].at[:4].isdigit()
    assert len(git.log(["HEAD"], "realms/r", 1)) == 1
    assert git.newest("HEAD", "realms/r") == entries[0].sha
    assert git.newest("HEAD", "realms/none") is None


# -- the adopter's, leave's, re-key's and restore-a-version's steps (S2) -------------------------------


def test_fetch_of_a_branch_an_empty_remote_lacks(tmp_path, remote):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    assert not git.is_repo()
    git.init()
    assert git.is_repo()
    empty = tmp_path / "empty.git"
    _sh(tmp_path, "init", "-q", "--bare", str(empty))
    git.remote_add("origin", str(empty))
    assert git.fetch(None, branch="main") is FetchOutcome.EMPTY_REMOTE
    git.remote_remove("origin")
    git.remote_add("origin", str(remote))
    assert git.fetch(None, branch="main") is FetchOutcome.FETCHED
    assert git.resolve("refs/remotes/origin/main") is not None
    git.remote_remove("origin")
    git.remote_add("origin", str(tmp_path / "gone.git"))
    with pytest.raises(RealmSyncError):
        git.fetch(None, branch="main")


def test_reset_hard_takes_the_remote_and_set_upstream_tracks_it(tmp_path, remote):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    git.rename_branch("main")
    git.remote_add("origin", str(remote))
    _sh(repo, "fetch", "-q", "origin", "main")
    git.reset_hard("origin/main")
    assert (repo / "realms/r/a.txt").read_text(encoding="utf-8") == "one\n"
    assert git.upstream() is None
    git.set_upstream("main")
    assert git.upstream() == "origin/main"
    assert git.merge_base("HEAD", "origin/main") == git.resolve("HEAD")


def test_push_to_a_named_branch_sets_its_upstream(tmp_path):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    git.rename_branch("main")
    _member_commits(repo, "x.txt", "x\n")
    bare = tmp_path / "empty.git"
    _sh(tmp_path, "init", "-q", "--bare", str(bare))
    git.remote_add("origin", str(bare))
    assert git.push(None, set_upstream=True, branch="main").outcome is PushOutcome.PUSHED
    assert git.upstream() == "origin/main"
    assert _sh(tmp_path, "--git-dir", str(bare), "rev-parse", "main") == git.resolve("HEAD")


def test_unrelated_histories_merge_with_ours_on_overlap(tmp_path, remote):
    repo = tmp_path / "fresh"
    repo.mkdir()
    git = sync_git(repo)
    git.init()
    git.rename_branch("main")
    _member_commits(repo, "mine/b.txt", "b\n")
    _member_commits(repo, ".gitattributes", "ours\n")
    git.remote_add("origin", str(remote))
    git.fetch(None, branch="main")
    assert git.merge_base("HEAD", "origin/main") is None
    assert git.tree_paths("HEAD") == {"mine/b.txt", ".gitattributes"}
    assert git.tree_paths("origin/main") == {"realms/r/a.txt"}
    assert git.tree_paths("refs/heads/none") == frozenset()
    git.merge_unrelated_ours("origin/main")
    assert git.tree_paths("HEAD") == {"mine/b.txt", ".gitattributes", "realms/r/a.txt"}
    assert git.is_ancestor("origin/main", "HEAD")


def test_move_and_add_all_under_stage_the_deletions(tmp_path, remote):
    """A re-key moves ``realms/<old>`` to ``realms/<new>`` and deletes a file under it: both reach the commit."""

    repo = _clone(tmp_path, remote)
    _member_commits(repo, "realms/r/gone.txt", "g\n")
    git = sync_git(repo)
    git.move("realms/r", "realms/s")
    (repo / "realms/s/gone.txt").unlink()
    (repo / "outside.txt").write_text("o\n", encoding="utf-8")
    git.add(["realms"], all_under=True)
    git.commit("re-key", paths=["realms"])
    assert git.tree_paths("HEAD") == {"realms/s/a.txt"}
    assert [c.path for c in git.changed()] == ["outside.txt"]


def test_add_of_a_path_that_is_gone_stages_its_deletion(tmp_path, remote):
    """Publish and re-key name a realm subtree that may no longer exist on disk; git 2.x stages its removal.

    dulwich 1.2.21's ``porcelain.add`` stages deletions under a directory it is given, but is never given
    one that is gone: the DULWICH arm's own removal is what this pins."""

    repo = _clone(tmp_path, remote)
    _member_commits(repo, "realms/q/b.txt", "b\n")
    git = sync_git(repo)
    (repo / "realms/q/b.txt").unlink()
    (repo / "realms/q").rmdir()
    git.add(["realms/q"])
    git.commit("drop q")
    assert git.tree_paths("HEAD") == {"realms/r/a.txt"}
    assert git.changed() == ()


def test_read_tree_at_writes_one_versions_subtree(tmp_path, remote):
    repo = _clone(tmp_path, remote)
    git = sync_git(repo)
    first = git.resolve("HEAD")
    _member_commits(repo, "realms/r/a.txt", "two\n")
    dest = tmp_path / "out"
    dest.mkdir()
    tree = git.read_tree_at(first, "realms/r", dest)
    assert tree is not None and (tree / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert git.read_tree_at(first, "realms/none", dest) is None
    assert git.resolve("deadbeef" * 5) is None
    assert git.resolve(first[:12]) == first
    assert (repo / "realms/r/a.txt").read_text(encoding="utf-8") == "two\n"  # no ref moved
