"""`scripts/prepush.sh` — the one pre-push command (FH-PREPUSH-ONE-COMMAND), with a budget,
a heartbeat, a deadline and a notification per step (FH-PREPUSH-PROGRESS-BUDGET).

Each test copies the script into a throwaway git repository whose
`origin/main` is pinned by `update-ref`, so the touched-test selection and the
exit code are read off the real script without running the suite: the runner
and the doc-cite interpreter are stubs that record their argv and exit as told.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
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


def _stub(path: Path, code: int, log: Path, body: str = "") -> Path:
    path.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\n{body}\nexit {code}\n', encoding="utf-8")
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


def _run(repo: Path, *args: str, runner_code: int = 0, cite_code: int = 0, runner_body: str = "",
         env_extra: dict[str, str] | None = None):
    log = repo.parent / "calls.log"
    env = {
        **os.environ,
        "PREPUSH_RUNNER": str(_stub(repo.parent / "runner.sh", runner_code, log, runner_body)),
        "PREPUSH_PYTHON": str(_stub(repo.parent / "cite.sh", cite_code, log)),
        "PREPUSH_NOTIFY": str(_stub(repo.parent / "notify.sh", 0, repo.parent / "notified.log")),
        **(env_extra or {}),
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
    gates_argv, _cite, lane_argv = (line.split() for line in calls.splitlines())
    assert "tests/tooling/test_queue_row_guard.py" in gates_argv
    assert "tests/a/test_committed.py" in lane_argv
    assert "tests/a/test_untracked.py" in lane_argv
    assert "tests/a/test_base.py" not in lane_argv
    assert "tests/a/helper.py" not in lane_argv
    # The positive control for "each file once": a named path that is also touched.
    proc, calls = _run(repo, "tests/a/test_committed.py")
    assert calls.splitlines()[-1].split().count("tests/a/test_committed.py") == 1


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
    # Every step runs even when the first is red: one push, the whole answer.
    assert len(calls.splitlines()) == 3
    assert ("RED" in proc.stdout) == bool(expected)
    # A red notifies once at the end; a green run inside budget notifies nothing.
    notified = repo.parent / "notified.log"
    if expected:
        assert "prepush: RED" in _wait_for(notified), proc.stdout
    else:
        time.sleep(0.5)  # the notifier is detached; give a wrong one the time to land
        assert not notified.exists(), proc.stdout
        assert "…" not in proc.stdout  # no heartbeat inside budget


def test_a_missing_named_path_refuses_before_running(repo: Path):
    proc, calls = _run(repo, "tests/a/test_nope.py")
    assert proc.returncode == 2
    assert calls == ""


def _wait_for(path: Path, seconds: float = 5.0) -> str:
    """The notifier is detached on purpose (never waited on), so its record lands a beat later."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8")
        time.sleep(0.05)
    return ""


def test_the_plan_declares_every_steps_budget_and_deadline(repo: Path):
    proc, _ = _run(repo, "--plan")
    assert "step gates — budget 10s, deadline 120s" in proc.stdout
    assert "step doc-cite — budget 4s, deadline 60s" in proc.stdout
    assert "step touched (the slower lane) — budget 60s, deadline 900s" in proc.stdout
    assert "default path: gates + doc-cite, budget 14s" in proc.stdout


# Mutation: delete the heartbeat ``echo`` (or the ``_notify``) in ``_watch`` -> this reds. Positive
# control: the green run inside budget in ``test_exit_code_is_red_on_any_red`` prints none.
@pytest.mark.timeout(60)
def test_a_step_past_its_budget_heartbeats_and_notifies_once_and_still_passes(repo: Path):
    proc, _ = _run(repo, runner_body="sleep 3", env_extra={
        "PREPUSH_GATES_BUDGET": "1", "PREPUSH_GATES_DEADLINE": "30", "PREPUSH_HEARTBEAT": "1"})
    assert proc.returncode == 0, proc.stdout
    assert "… prepush: gates still running past its 1s budget (deadline 30s)" in proc.stdout
    assert "… prepush: gates still running (2s, budget 1s, deadline 30s)" in proc.stdout
    assert "prepush: gates over budget" in _wait_for(repo.parent / "notified.log")
    assert "… prepush: doc-cite" not in proc.stdout  # only the slow step speaks
    assert proc.stdout.rstrip().endswith("✔ prepush: green")


# Mutation: delete the ``kill -TERM/-KILL -- -pgid`` in ``_watch`` -> the run waits out the 60 s
# sleep and the grandchild survives. The grandchild proves the kill takes the step's whole group.
@pytest.mark.timeout(60)
def test_a_step_at_its_deadline_is_killed_with_its_tree_and_the_run_fails_naming_it(repo: Path):
    pid_file = repo.parent / "grandchild.pid"
    started = time.monotonic()
    proc, _ = _run(repo, runner_body=f'sleep 60 & echo $! > "{pid_file}"; wait', env_extra={
        "PREPUSH_GATES_BUDGET": "1", "PREPUSH_GATES_DEADLINE": "2", "PREPUSH_HEARTBEAT": "1",
        "PREPUSH_TOUCHED_BUDGET": "1", "PREPUSH_TOUCHED_DEADLINE": "2"})
    assert time.monotonic() - started < 30, proc.stdout
    assert proc.returncode == 1, proc.stdout
    assert "✘ prepush: gates killed at its 2s deadline" in proc.stdout
    assert "gates (killed at its 2s deadline)" in proc.stdout.splitlines()[-1]
    grandchild = int(pid_file.read_text(encoding="utf-8").split()[0])
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)
    assert "prepush: RED" in _wait_for(repo.parent / "notified.log")


def test_a_budget_that_is_not_a_whole_number_of_seconds_refuses_before_running(repo: Path):
    proc, calls = _run(repo, env_extra={"PREPUSH_GATES_BUDGET": "1.5"})
    assert proc.returncode == 2 and calls == ""
