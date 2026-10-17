"""``--confirm-red <file>``: one named red, alone, on HEAD and on the base — never the suite.

Owner ruling 2026-10-16. ``scripts/run_tests_bundled_confirm.py`` prints caused /
pre-existing / load; the worktree it cuts for the base sits beside the primary
checkout and is gone afterwards.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

confirm = bundled._confirm
Verdict = confirm.Verdict
Attempt = confirm.Attempt
F = "tests/test_x.py"


def test_green_alone_on_head_is_load_whatever_the_base_says():
    assert confirm.judge(Attempt("HEAD", 0), None) == (Verdict.LOAD, frozenset())


def test_red_on_head_and_green_on_the_base_is_caused():
    head = Attempt("HEAD", 1, frozenset({f"{F}::a"}))
    assert confirm.judge(head, Attempt("base", 0)) == (Verdict.CAUSED, frozenset({f"{F}::a"}))
    assert confirm.judge(head, None)[0] is Verdict.CAUSED, "a file the base does not have is the branch's"


def test_a_node_red_only_on_head_is_caused_and_a_shared_set_is_pre_existing():
    head = Attempt("HEAD", 1, frozenset({f"{F}::a", f"{F}::b"}))
    assert confirm.judge(head, Attempt("base", 1, frozenset({f"{F}::a"}))) == (Verdict.CAUSED, frozenset({f"{F}::b"}))
    assert confirm.judge(head, Attempt("base", 1, frozenset({f"{F}::a", f"{F}::b", f"{F}::c"}))) == (
        Verdict.PRE_EXISTING, frozenset())


def test_failing_ids_come_from_the_short_summary():
    output = f"..F\nFAILED {F}::test_a - AssertionError\nERROR {F}::test_b\n1 failed\n"
    assert confirm.failing_ids(output) == frozenset({f"{F}::test_a", f"{F}::test_b"})


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    primary = tmp_path / "hermes"
    (primary / "tests").mkdir(parents=True)
    _git(primary, "init", "-q")
    (primary / F).write_text("def test_a(): pass\n", encoding="utf-8")
    _git(primary, "add", "-A")
    _git(primary, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "base")
    return primary


@pytest.mark.parametrize("base_red,expected", [(False, Verdict.CAUSED), (True, Verdict.PRE_EXISTING)])
def test_confirm_runs_the_file_alone_on_head_then_in_a_base_worktree_beside_the_primary(clone, base_red, expected):
    seen = []

    def runner(file: Path, cwd: Path, timeout: float):
        seen.append(cwd)
        assert file == cwd / F and file.is_file()
        on_head = cwd == clone
        red = on_head or base_red
        return (1, f"FAILED {F}::test_a\n") if red else (0, "1 passed\n")

    lines = []
    verdict = confirm.confirm(F, clone, clone, base="HEAD", runner=runner, out=lines.append)
    assert verdict is expected
    assert seen[0] == clone and seen[1].parent == clone.parent / "worktrees" and seen[1].name.startswith("confirm-red-")
    assert not seen[1].exists(), "the base worktree is removed after the run"
    assert len(_git(clone, "worktree", "list").splitlines()) == 1
    assert lines[-1 if expected is Verdict.CAUSED else -2].strip() in (
        f"caused: {F}::test_a", "verdict: pre-existing")


def test_a_green_head_never_cuts_a_worktree(clone):
    calls = []
    verdict = confirm.confirm(F, clone, clone, base="HEAD", runner=lambda f, c, t: calls.append(c) or (0, ""),
                              out=lambda line: None)
    assert verdict is Verdict.LOAD and calls == [clone]


def test_the_runner_takes_confirm_red_as_its_own_flag():
    ours, passthrough = bundled._split_argv(["--confirm-red", F, "--confirm-base", "origin/main", "-q"])
    assert ours == ["--confirm-red", F, "--confirm-base", "origin/main"] and passthrough == ["-q"]
