"""The per-commit version-info cache (lane q-version): git runs once per commit, not per process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli import version_info, version_info_cache

ROOT = Path(__file__).resolve().parents[2]
_GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

_spawns: list[list[str]] = []


def _audit(event: str, args: tuple) -> None:
    if event == "subprocess.Popen":
        argv = args[1]
        # Windows audits the joined command line, POSIX the list.
        argv = [str(a) for a in argv] if isinstance(argv, (list, tuple)) else str(argv).split()
        if argv and "git" in str(argv[0]).lower():
            _spawns.append([str(a) for a in argv])


sys.addaudithook(_audit)


def git(repo: Path, *args: str) -> str:
    return subprocess.run([*_GIT, *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo: Path, text: str) -> None:
    (repo / "a.txt").write_text(text, encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", text)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, "release")
    git(repo, "tag", "v1.2.3")
    commit(repo, "next")
    monkeypatch.setattr(version_info, "_resolve_stamp_file", lambda: None)
    monkeypatch.setattr(version_info, "_resolve_repo_dir", lambda: repo)
    monkeypatch.setattr(version_info, "_cached_version_info", None)
    version_info_cache._reset_for_tests()
    yield repo
    version_info_cache._reset_for_tests()


def fresh_process_info():
    """What a new process resolves: no in-process state, the git-dir cache file kept."""
    version_info_cache._reset_for_tests()
    version_info._reset_version_info_cache()
    _spawns.clear()
    info = version_info.get_version_info()
    return info, [argv for argv in _spawns]


def non_status(spawns):
    """Spawns other than the live dirty probe (a child process reports joined strings)."""
    return [argv for argv in spawns if "status" not in (argv.split() if isinstance(argv, str) else argv)]


def cache_file(repo: Path) -> Path:
    return repo / ".git" / version_info_cache.CACHE_NAME


def test_a_second_process_on_an_unchanged_head_spawns_only_the_live_dirty_probe(repo):
    cold, cold_spawns = fresh_process_info()
    warm, warm_spawns = fresh_process_info()

    assert cold.base_version == "1.2.3" and cold.distance == 1
    assert len(non_status(cold_spawns)) >= 4
    assert non_status(warm_spawns) == []
    assert len(warm_spawns) == 1  # dirty stays live
    assert warm == cold
    assert warm.commit == git(repo, "rev-parse", "HEAD")
    assert warm.branch == git(repo, "branch", "--show-current")


def test_the_cache_is_shared_by_real_processes(repo, tmp_path):
    child = (
        "import json, sys, pathlib\n"
        "spawns = []\n"
        "sys.addaudithook(lambda e, a: spawns.append(a[1] if isinstance(a[1], str) "
        "else ' '.join(map(str, a[1]))) if e == 'subprocess.Popen' else None)\n"
        "from hermes_cli import version_info as v\n"
        "v._resolve_stamp_file = lambda: None\n"
        f"v._resolve_repo_dir = lambda: pathlib.Path({str(repo)!r})\n"
        "info = v.get_version_info()\n"
        "print(json.dumps({'derived': info.derived_version, 'spawns': spawns}))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HERMES_HOME": str(tmp_path / "home")}

    def run():
        out = subprocess.run([sys.executable, "-c", child], cwd=ROOT, env=env, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out.strip().splitlines()[-1])

    first, second = run(), run()
    assert first["derived"] == second["derived"]
    assert len(non_status(first["spawns"])) >= 4
    assert non_status(second["spawns"]) == []


def test_a_new_commit_invalidates(repo):
    fresh_process_info()
    commit(repo, "third")

    info, spawns = fresh_process_info()

    assert info.distance == 2
    assert info.commit == git(repo, "rev-parse", "HEAD")
    assert any("rev-list" in argv for argv in spawns)


def test_a_new_tag_invalidates(repo):
    fresh_process_info()
    git(repo, "tag", "v1.3.0")

    info, spawns = fresh_process_info()

    assert info.base_version == "1.3.0" and info.distance == 0
    assert any("tag" in argv for argv in non_status(spawns))


def test_a_corrupt_cache_falls_back_to_git_and_is_rewritten(repo):
    cold, _ = fresh_process_info()
    cache_file(repo).write_text("{not json", encoding="utf-8")

    info, spawns = fresh_process_info()

    assert info == cold
    assert len(non_status(spawns)) >= 4
    assert json.loads(cache_file(repo).read_text(encoding="utf-8"))["fields"]["base_version"] == "1.2.3"


def test_an_unwritable_cache_falls_back_every_time(repo, monkeypatch):
    def refuse(*args):
        raise PermissionError("read-only git dir")

    monkeypatch.setattr(version_info_cache.os, "replace", refuse)
    cold, _ = fresh_process_info()
    assert not cache_file(repo).exists()
    assert not list((repo / ".git").glob(f"{version_info_cache.CACHE_NAME}.*.tmp"))
    again, spawns = fresh_process_info()

    assert again == cold
    assert len(non_status(spawns)) >= 4


def test_refresh_rereads_head_and_uses_the_cache_when_unchanged(repo):
    fresh_process_info()
    head = git(repo, "rev-parse", "HEAD")
    _spawns.clear()

    identity = version_info.get_code_identity(refresh=True)

    assert non_status(_spawns) == []
    assert identity["sha"] == head

    commit(repo, "moved under the process")
    assert version_info.get_code_identity(refresh=True)["sha"] == git(repo, "rev-parse", "HEAD")


def test_release_version_reads_the_cache_without_git(repo):
    fresh_process_info()
    version_info._reset_version_info_cache()
    version_info_cache._reset_for_tests()
    _spawns.clear()

    assert version_info.release_version() == "1.2.3"
    assert _spawns == []


def test_release_version_without_a_cache_resolves_once_and_fills_it(repo):
    version_info._reset_version_info_cache()

    assert version_info.release_version() == "1.2.3"
    assert version_info_cache.cached_base_version(repo) == "1.2.3"


def test_head_is_read_from_a_linked_worktree_and_packed_refs(repo, tmp_path):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    git(repo, "pack-refs", "--all")

    head = version_info_cache.read_head(linked)
    main_head = version_info_cache.read_head(repo)

    assert head is not None and head.commit == git(linked, "rev-parse", "HEAD")
    assert head.branch == "side"
    assert head.git_dir != head.common_dir
    assert main_head is not None and main_head.commit == git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--detach")
    detached = version_info_cache.read_head(repo)
    assert detached is not None and detached.branch is None
