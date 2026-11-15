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
    cached = (
        scope.upstream_base, scope.upstream_blobs, scope.working_blob,
        scope.fork_authored_lines, scope.unattributable_here,
    )
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

    assert scope.unattributable_upstream_paths(repo) == frozenset(), "a FULL clone keeps failing closed"


def test_a_shallow_clone_sets_upstream_paths_aside_instead_of_failing_closed(repo, tmp_path_factory):
    """FH-VM-CLONE-SHALLOW-DOCKET-GATES: the base is outside a depth-1 clone, so ancestry
    cannot be asked; upstream-shipped paths are "not checked", not handed to the fork."""
    released = _commit(repo, "# release\n")
    _manifest(repo, released[:10])
    _git(repo, "add", "tests")
    _git(repo, "-c", "user.name=Scope test", "-c", "user.email=scope@example.invalid",
         "commit", "-qm", "manifest")
    _commit(repo, "# release\nfork.undo()\n")
    shallow = tmp_path_factory.mktemp("shallow") / "clone"
    _git(repo, "clone", "-q", "--depth", "1", repo.as_uri(), str(shallow))

    assert scope.is_shallow_clone(shallow) and not scope.is_shallow_clone(repo)
    assert scope.read_recorded_base(shallow) is None
    assert scope.unattributable_upstream_paths(shallow) == frozenset({"test_sample.py"})
    assert scope.unattributable_upstream_paths(repo) == frozenset(), "the full clone validates its base"


_GREP = "import inspect\ndef test_{name}():\n    assert 'needle' in inspect.getsource(object)\n"


@pytest.mark.parametrize("fork_file", [False, True])
def test_the_source_grep_gate_skips_what_a_shallow_clone_cannot_judge(
    repo, tmp_path_factory, monkeypatch, fork_file,
):
    """FH-SOURCE-GREP-GATE-REDS-UPSTREAM-LINES-ON-A-SHALLOW-CLONE, through a real depth-1
    clone: a finding in an upstream-shipped file is unjudged (a visible skip with the
    count), never red and never a silent green; the fork's own finding still fails."""
    from tests import test_no_source_grep_assertions as gate

    def commit(message):
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.name=Scope test", "-c", "user.email=scope@example.invalid",
             "commit", "-qm", message)
        return _git(repo, "rev-parse", "HEAD")

    (repo / "tests").mkdir()
    (repo / "tests/test_up.py").write_text(_GREP.format(name="up"), encoding="utf-8")
    released = commit("upstream release")
    manifest = repo / "tests/fixtures/upstream_manifest.txt"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f"# base {released[:10]}\ntests/test_up.py\n", encoding="utf-8")
    if fork_file:
        (repo / "tests/test_fork.py").write_text(_GREP.format(name="fork"), encoding="utf-8")
    commit("fork")
    shallow = tmp_path_factory.mktemp("shallow") / "clone"
    _git(repo, "clone", "-q", "--depth", "1", repo.as_uri(), str(shallow))

    def scan_in(root):
        monkeypatch.setattr(scope, "repo_root", lambda: root)
        monkeypatch.setattr(gate, "REPO_ROOT", root)
        monkeypatch.setattr(gate, "TESTS_ROOT", root / "tests")
        for fn in (scope.upstream_base, scope.upstream_blobs, scope.working_blob,
                   scope.fork_authored_lines, scope.unattributable_here):
            fn.cache_clear()
        return gate._scan()

    fork_key = "tests/test_fork.py::test_fork::'needle' in inspect.getsource(object)"
    up_key = "tests/test_up.py::test_up::'needle' in inspect.getsource(object)"
    found, _scanned, _locations, unjudged = scan_in(repo)
    assert (found, unjudged) == ([fork_key] if fork_file else [], []), "the full clone judges every line"

    result = scan_in(shallow)
    assert (result[0], result[3]) == ([fork_key] if fork_file else [], [up_key])
    monkeypatch.setattr(gate, "_MIN_SCANNED_FILES", 1)
    if fork_file:
        with pytest.raises(AssertionError, match="test_fork.py"):
            gate.test_no_new_positive_source_grep_assertion(result)
    else:
        with pytest.raises(pytest.skip.Exception, match="^1 unledgered positive source-grep"):
            gate.test_no_new_positive_source_grep_assertion(result)
