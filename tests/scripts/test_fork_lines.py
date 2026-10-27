"""``scripts/code_health/fork_lines.py``: a line is the fork's iff it is absent from the
upstream base blob (or its file is not upstream at all).

Plan: ``docs/agent-runtime-harness/archive/fork-seam-line-lint-2026-10-21.md`` F1.
"""

from __future__ import annotations

import pytest

from scripts.code_health.fork_lines import ForkLines, ForkLinesUnavailable, added_lines
from tests.scripts._fork_repo import git, make_fork_repo


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    base = make_fork_repo(root)
    return root, base


def test_a_line_added_after_the_base_is_a_fork_line(repo):
    root, _ = repo
    lines = ForkLines.load(root)
    assert lines.is_fork_line("up.py", 2)
    assert lines.lines["up.py"] == frozenset({2})


def test_a_line_present_at_the_base_is_not_a_fork_line(repo):
    """Line 3 (``A = 1``) is upstream's, renumbered; old line 3 (``B``) was deleted there."""
    root, _ = repo
    lines = ForkLines.load(root)
    assert not lines.is_fork_line("up.py", 1)
    assert not lines.is_fork_line("up.py", 3)
    assert not lines.is_fork_line("up.py", 4)


def test_a_file_absent_at_the_base_is_wholly_the_forks(repo):
    root, _ = repo
    lines = ForkLines.load(root)
    assert lines.owner("fork.py") == "fork"
    assert lines.is_fork_line("fork.py", 1)
    assert lines.is_fork_line(root / "fork.py", 999)


def test_an_untouched_upstream_file_has_no_fork_lines(tmp_path):
    root = tmp_path / "repo"
    make_fork_repo(root, up_fork="import os\nA = 1\nB = 2\nC = 3\n")
    lines = ForkLines.load(root)
    assert lines.owner("up.py") == "upstream"
    assert not any(lines.is_fork_line("up.py", n) for n in range(1, 5))


def test_the_working_tree_is_judged_not_the_commit(repo):
    root, _ = repo
    (root / "up.py").write_text("import os\nX = 0\nA = 1\nC = 3\nZ = 9\n", encoding="utf-8",
                                newline="\n")
    assert ForkLines.load(root).lines["up.py"] == frozenset({2, 5})


def test_an_absolute_path_is_judged_relative_to_the_root(repo):
    root, _ = repo
    lines = ForkLines.load(root)
    assert lines.is_fork_line(root / "up.py", 2)
    assert not lines.is_fork_line(root / "up.py", 3)


def test_the_base_is_the_upstream_merge_base_when_the_ref_exists(repo):
    root, base = repo
    (root / "tests" / "fixtures" / "upstream_manifest.txt").write_text("up.py\n", encoding="utf-8")
    with pytest.raises(ForkLinesUnavailable):
        ForkLines.load(root)
    git(root, "update-ref", "refs/remotes/upstream/main", base)
    assert ForkLines.load(root).base == base


def test_an_explicit_base_wins(repo):
    root, _ = repo
    head = git(root, "rev-parse", "HEAD")
    assert ForkLines.load(root, base_ref=head).lines == {}


def test_the_parser_reads_only_the_new_side_of_a_hunk():
    text = (
        "diff --git a/up.py b/up.py\n--- a/up.py\n+++ b/up.py\n"
        "@@ -1,0 +2 @@\n+X = 0\n@@ -3 +3,0 @@\n-B = 2\n@@ -7,2 +8,3 @@\n-a\n-b\n+a\n+b\n+c\n"
        "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    )
    assert added_lines(text) == {"up.py": {2, 8, 9, 10}}


def test_the_summary_names_the_base_and_the_seams(repo):
    root, base = repo
    summary = ForkLines.load(root).summary()
    assert f"base={base[:10]}" in summary
    assert "seam_files=1 fork_lines_in_seams=1" in summary
