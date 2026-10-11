"""``--since-merge``: a release merge's gate tests what the merge produced (D3.07).

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md`` § D3.07.
A scratch repo carries an "upstream" branch and a fork ``main`` with one
conftest hunk; upstream is merged into the fork, a ``fix(merge)`` commit and a
working-tree edit follow. The change set is the merge's combined diff plus
what came after it; an upstream-only change the merge took verbatim is not in it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

scope = bundled.scope

_UPSTREAM_CONFTEST = [f"upstream line {i}" for i in range(1, 21)]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _write(repo: Path, rel: str, lines: list[str]) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _released_fork(repo: Path, *, rewrite_fork_hunk_in_merge: bool = False) -> str:
    """The scratch history; returns the merge's sha."""

    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "tests/conftest.py", _UPSTREAM_CONFTEST)
    _write(repo, "pkg/a.py", ["a = 1"])
    _write(repo, "pkg/both.py", [f"b{i} = {i}" for i in range(1, 21)])
    _write(repo, "tests/pkg/test_a.py", ["def test_a():", "    pass"])
    _commit(repo, "upstream v1")
    _git(repo, "branch", "upstream")

    # the fork: one conftest hunk, one edit to a shared module, one fork-only file
    _write(repo, "tests/conftest.py", _UPSTREAM_CONFTEST[:10] + ["# fork hunk", "FORK = True"] + _UPSTREAM_CONFTEST[10:])
    _write(repo, "pkg/both.py", ["b1 = 1", "b2 = 2", "b3 = 'fork'"] + [f"b{i} = {i}" for i in range(4, 21)])
    _write(repo, "fork/f.py", ["f = 1"])
    _commit(repo, "fork work")

    # upstream's release: edits far from the fork's hunks, an upstream-only change, a new file
    _git(repo, "checkout", "-q", "upstream")
    _write(repo, "tests/conftest.py", ["upstream line 1 v2"] + _UPSTREAM_CONFTEST[1:19] + ["upstream line 20 v2"])
    _write(repo, "pkg/a.py", ["a = 2"])
    _write(repo, "pkg/both.py", [f"b{i} = {i}" for i in range(1, 18)] + ["b18 = 'upstream'", "b19 = 19", "b20 = 20"])
    _write(repo, "pkg/new.py", ["new = 1"])
    _commit(repo, "upstream v2")
    _git(repo, "tag", "v2")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "--no-commit", "v2")
    if rewrite_fork_hunk_in_merge:
        text = (repo / "tests/conftest.py").read_text(encoding="utf-8").replace("FORK = True", "FORK = 'merged'")
        (repo / "tests/conftest.py").write_text(text, encoding="utf-8", newline="\n")
    _commit(repo, "merge: upstream v2")
    merge = _git(repo, "rev-parse", "HEAD")

    _write(repo, "pkg/fix.py", ["fix = 1"])
    _commit(repo, "fix(merge): a repair after the merge")
    _write(repo, "fork/f.py", ["f = 2"])  # a working-tree edit, uncommitted
    return merge


def test_the_merge_change_is_its_combined_diff_plus_what_came_after(tmp_path):
    repo = tmp_path / "repo"
    merge = _released_fork(repo)

    changed = scope.changed_paths_for_merge(repo, merge)

    assert changed == {"tests/conftest.py", "pkg/both.py", "pkg/fix.py", "fork/f.py"}
    # the discriminator: the first-parent diff the old rule used carries upstream-only paths
    first_parent = set(_git(repo, "diff", "--name-only", f"{merge}^1", merge).splitlines())
    assert {"pkg/a.py", "pkg/new.py"} <= first_parent
    assert not {"pkg/a.py", "pkg/new.py"} & changed


def test_a_non_merge_or_a_merge_head_does_not_descend_from_is_refused(tmp_path):
    repo = tmp_path / "repo"
    merge = _released_fork(repo)
    with pytest.raises(RuntimeError, match="is not a merge commit"):
        scope.changed_paths_for_merge(repo, _git(repo, "rev-parse", "HEAD"))
    _git(repo, "checkout", "-q", "-f", "upstream")
    with pytest.raises(RuntimeError, match="is not an ancestor of HEAD"):
        scope.changed_paths_for_merge(repo, merge)


def _reach(repo: Path, change: set[str]) -> dict[str, list[str]]:
    files = [repo / "tests/pkg/test_a.py"]
    sel = bundled.select_scope(files, repo, {"tests/pkg/test_a.py"}, change)
    return {"conftest": _rels(repo, sel.conftest), "excluded": _rels(repo, sel.excluded)}


def _rels(repo: Path, paths) -> list[str]:
    return [p.resolve().relative_to(repo.resolve()).as_posix() for p in paths]


def test_a_conftest_whose_fork_hunk_the_merge_left_unchanged_does_not_reach(tmp_path):
    repo = tmp_path / "repo"
    merge = _released_fork(repo)

    change = scope.merge_change(repo, merge)

    assert _reach(repo, change.paths) == {"conftest": [], "excluded": ["tests/pkg/test_a.py"]}
    assert change.standing == ["tests/conftest.py"]
    assert change.paths == {"pkg/both.py", "pkg/fix.py", "fork/f.py"}
    assert scope.conftest_hunk_unchanged(repo, "tests/conftest.py", merge)
    assert "not reaching: tests/conftest.py" in change.account()
    assert "2 path(s) in its combined diff (against its first parent: 4) + 2 after it" in change.account()


def test_a_conftest_whose_fork_hunk_the_merge_rewrote_still_reaches(tmp_path):
    repo = tmp_path / "repo"
    merge = _released_fork(repo, rewrite_fork_hunk_in_merge=True)

    assert not scope.conftest_hunk_unchanged(repo, "tests/conftest.py", merge)
    change = scope.merge_change(repo, merge)

    assert change.standing == []
    assert "tests/conftest.py" in change.paths
    assert _reach(repo, change.paths) == {"conftest": ["tests/pkg/test_a.py"], "excluded": []}


def test_a_conftest_edited_after_the_merge_still_reaches(tmp_path):
    repo = tmp_path / "repo"
    merge = _released_fork(repo)
    conftest = repo / "tests/conftest.py"
    conftest.write_text(conftest.read_text(encoding="utf-8") + "LATER = 1\n", encoding="utf-8", newline="\n")

    change = scope.merge_change(repo, merge)

    assert change.standing == []
    assert _reach(repo, change.paths)["conftest"] == ["tests/pkg/test_a.py"]
