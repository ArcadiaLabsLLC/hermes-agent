"""`scripts/prepush.sh` — the one pre-push command (FH-PREPUSH-ONE-COMMAND).

Each test copies the script into a throwaway git repository whose
`origin/main` is pinned by `update-ref`, so the touched-test selection and the
exit code are read off the real script without running the suite: the runner
and the doc-cite interpreter are stubs that record their argv and exit as told.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "prepush.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _stub(path: Path, code: int, log: Path) -> Path:
    path.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexit {code}\n', encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "prepush.sh")
    (root / "tests" / "a").mkdir(parents=True)
    (root / "tests" / "a" / "test_base.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    (root / "tests" / "a" / "test_committed.py").write_text("x = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "touch")
    (root / "tests" / "a" / "test_untracked.py").write_text("x = 3\n", encoding="utf-8")
    (root / "tests" / "a" / "helper.py").write_text("x = 4\n", encoding="utf-8")
    return root


def _run(repo: Path, *args: str, runner_code: int = 0, cite_code: int = 0):
    log = repo.parent / "calls.log"
    env = {
        **os.environ,
        "PREPUSH_RUNNER": str(_stub(repo.parent / "runner.sh", runner_code, log)),
        "PREPUSH_PYTHON": str(_stub(repo.parent / "cite.sh", cite_code, log)),
    }
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "prepush.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    return proc, calls


def test_plan_names_the_queue_gates_and_every_gate_exists_in_this_repo():
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--plan"],
        cwd=REPO,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    named = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("tests/")]
    assert "tests/tooling/test_work_queue_row_grammar.py" in named
    assert "tests/tooling/test_queue_row_guard.py" in named
    missing = [p for p in named if not (REPO / p).is_file()]
    assert not missing, missing


def test_touched_tests_are_the_changed_and_untracked_test_files(repo: Path):
    proc, calls = _run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    runner_argv = calls.splitlines()[0].split()
    assert "tests/a/test_committed.py" in runner_argv
    assert "tests/a/test_untracked.py" in runner_argv
    assert "tests/a/test_base.py" not in runner_argv
    assert "tests/a/helper.py" not in runner_argv
    # The positive control for "each file once": a named path that is also touched.
    proc, calls = _run(repo, "tests/a/test_committed.py")
    assert calls.splitlines()[-2].split().count("tests/a/test_committed.py") == 1


def test_plan_only_runs_nothing(repo: Path):
    proc, calls = _run(repo, "--plan")
    assert proc.returncode == 0
    assert calls == ""
    assert "tests/a/test_untracked.py" in proc.stdout


@pytest.mark.parametrize(
    ("runner_code", "cite_code", "expected"),
    [(0, 0, 0), (1, 0, 1), (0, 1, 1), (5, 3, 1)],
)
def test_exit_code_is_red_on_any_red(repo: Path, runner_code: int, cite_code: int, expected: int):
    proc, calls = _run(repo, runner_code=runner_code, cite_code=cite_code)
    assert proc.returncode == expected, proc.stdout
    # Both checks run even when the first is red: one push, the whole answer.
    assert len(calls.splitlines()) == 2
    assert ("RED" in proc.stdout) == bool(expected)


def test_a_missing_named_path_refuses_before_running(repo: Path):
    proc, calls = _run(repo, "tests/a/test_nope.py")
    assert proc.returncode == 2
    assert calls == ""
