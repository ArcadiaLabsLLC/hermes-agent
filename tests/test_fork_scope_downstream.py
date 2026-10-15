"""Release attribution must not depend on the workstation's remote-ref freshness."""

from pathlib import Path
import subprocess

import pytest

from tests import _fork_scope as scope


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()


def _commit(root: Path, text: str) -> str:
    (root / "test_sample.py").write_text(text, encoding="utf-8")
    _git(root, "add", "test_sample.py")
    _git(root, "-c", "user.name=Scope test", "-c", "user.email=scope@example.invalid",
         "commit", "-qm", "sample")
    return _git(root, "rev-parse", "HEAD")


def _manifest(root: Path, base: str) -> None:
    path = root / "tests/fixtures/upstream_manifest.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# base {base}\ntest_sample.py\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    monkeypatch.setattr(scope, "repo_root", lambda: tmp_path)
    cached = (scope.upstream_base, scope.upstream_blobs, scope.working_blob, scope.fork_authored_lines)
    for fn in cached:
        fn.cache_clear()
    yield tmp_path
    for fn in cached:
        fn.cache_clear()


@pytest.mark.parametrize("remote", ["missing", "stale", "ahead"])
def test_recorded_release_separates_upstream_and_fork_lines(repo, remote):
    old = _commit(repo, "# older release\n")
    released = _commit(repo, "# newer release\nupstream.undo()\n")
    _manifest(repo, released[:10])
    if remote == "stale":
        _git(repo, "update-ref", "refs/remotes/upstream/main", old)
    elif remote == "ahead":
        # A remote tip has this extra line, but this checkout has not integrated it.
        _git(repo, "checkout", "-qb", "future")
        future = _commit(repo, "# newer release\nupstream.undo()\nfork.undo()\n")
        _git(repo, "update-ref", "refs/remotes/upstream/main", future)
        _git(repo, "checkout", "--detach", released)
    (repo / "test_sample.py").write_text(
        "# newer release\nupstream.undo()\nfork.undo()\n", encoding="utf-8",
    )

    assert scope.upstream_base() == released
    assert scope.is_fork_touched("test_sample.py")
    assert not scope.is_fork_authored("test_sample.py", 2)
    assert scope.is_fork_authored("test_sample.py", 3)
    assert scope.is_fork_authored("fork_only.py", 1)


@pytest.mark.parametrize("invalid", ["missing", "malformed", "unknown", "nonancestor", "blob"])
def test_unusable_release_base_fails_closed(repo, invalid):
    head = _commit(repo, "# release\n")
    if invalid == "malformed":
        _manifest(repo, "not-a-commit")
    elif invalid == "unknown":
        _manifest(repo, "f" * 40)
    elif invalid == "blob":
        _manifest(repo, _git(repo, "rev-parse", "HEAD:test_sample.py"))
    elif invalid == "nonancestor":
        future = _commit(repo, "# not integrated\n")
        _git(repo, "checkout", "--detach", head)
        _manifest(repo, future)

    assert scope.upstream_base() is None
    assert scope.upstream_blobs() is None
    assert scope.is_fork_authored("test_sample.py", 1)

