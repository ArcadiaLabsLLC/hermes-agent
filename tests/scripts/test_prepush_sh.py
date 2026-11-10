"""`scripts/prepush.sh` — the one pre-push command (FH-PREPUSH-ONE-COMMAND), with a budget,
a heartbeat, a deadline and a notification per step (FH-PREPUSH-PROGRESS-BUDGET), one
whole-run cap and sharded touched files (FH-PREPUSH-CAP-TIGHT), and an overrun ledger
(FH-PREPUSH-OVERRUN-LEDGER).

Each test copies the script into a throwaway git repository whose
`origin/main` is pinned by `update-ref`, so the touched-test selection and the
exit code are read off the real script without running the suite: the runner
and the doc-cite interpreter are stubs that record their argv and exit as told.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "prepush.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

#: The bash each test runs: the root conftest's ``real_bash``, never a bare ``bash`` that
#: Windows resolves to System32's WSL launcher (FH-WINDOWS-PREPUSH-SHELL).
_BASH = "bash"


@pytest.fixture(autouse=True)
def _real_bash(monkeypatch, real_bash):
    monkeypatch.setattr(sys.modules[__name__], "_BASH", real_bash)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _stub(path: Path, code: int, log: Path, body: str = "") -> Path:
    path.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\n{body}\nexit {code}\n', encoding="utf-8",
                    newline="\n")  # LF on Windows too: a stub is a bash script, never CRLF
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "prepush.sh")
    shutil.copy2(SCRIPT.parent / "_fork_test_env.sh", root / "scripts" / "_fork_test_env.sh")
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
        "PREPUSH_GATES_RUNNER": str(repo.parent / "runner.sh"),  # the gates step's own runner, same stub
        "PREPUSH_PYTHON": str(_stub(repo.parent / "cite.sh", cite_code, log)),
        "PREPUSH_NOTIFY": str(_stub(repo.parent / "notify.sh", 0, repo.parent / "notified.log")),
        **(env_extra or {}),
    }
    proc = subprocess.run(
        [_BASH, str(repo / "scripts" / "prepush.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    return proc, calls


def test_plan_names_the_queue_gates_and_every_gate_exists_in_this_repo():
    proc = subprocess.run(
        [_BASH, str(SCRIPT), "--plan"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    named = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("tests/")]
    assert "tests/tooling/test_work_queue_row_grammar.py" in named
    assert "tests/tooling/test_queue_row_guard.py" in named
    missing = [p for p in named if not (REPO / p).is_file()]
    assert not missing, missing


def test_the_gates_step_runs_bundled_by_default():
    """FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP: one pytest per gate file cost ~3 s of Windows start-up
    each; the gates run through the fork's bundled runner instead. KILLING MUTATION: default
    ``GATES_RUNNER`` to ``run_tests.sh`` -> the plan names the per-file runner and this reds."""
    env = {k: v for k, v in os.environ.items() if k not in ("PREPUSH_RUNNER", "PREPUSH_GATES_RUNNER")}
    proc = subprocess.run(
        [_BASH, str(SCRIPT), "--plan"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "    runner: scripts/run_tests_bundled.sh" in proc.stdout.splitlines(), proc.stdout


def test_the_gates_step_runs_on_the_gates_runner_and_the_other_steps_do_not(repo: Path):
    """KILLING MUTATIONS: run the gates step on ``$RUNNER`` -> the gates argv lands in the
    per-file runner's log and the gates runner is never called; drop ``ETERNIA_HEAVY_SLOTS=off``
    -> the bundled gates wait on the machine-wide heavy-run slot and the ``slots=off`` line reds;
    drop ``--small`` -> the gates pay the landing gate's scope, plan and record, and the argv reds."""
    gates_log = repo.parent / "gates.log"
    gates = _stub(repo.parent / "gates.sh", 0, gates_log, f'echo "slots=${{ETERNIA_HEAVY_SLOTS:-}}" >> "{gates_log}"')
    proc, calls = _run(repo, env_extra={"PREPUSH_GATES_RUNNER": str(gates), "ETERNIA_HEAVY_SLOTS": "2"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gates_argv = gates_log.read_text(encoding="utf-8").split()
    assert "slots=off" in gates_argv and gates_argv[0] == "--small"
    assert "tests/tooling/test_queue_row_guard.py" in gates_argv
    assert "tests/tooling/test_queue_row_guard.py" not in calls
    assert "tests/a/test_committed.py" in calls and "tests/a/test_committed.py" not in gates_argv


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
    assert "step gates — budget 10s, deadline 20s" in proc.stdout
    assert "step doc-cite — budget 4s, deadline 10s" in proc.stdout
    assert "step touched (the slower lane) — budget 60s, deadline 120s" in proc.stdout
    assert "default path: gates + doc-cite, budget 14s" in proc.stdout
    assert "whole-run cap 240s" in proc.stdout


# Mutation: delete the heartbeat ``echo`` (or the ``_notify``) in ``_watch`` -> this reds. Positive
# control: the green run inside budget in ``test_exit_code_is_red_on_any_red`` prints none.
@pytest.mark.timeout(60)
def test_a_step_past_its_budget_heartbeats_and_notifies_once_and_still_passes(repo: Path):
    # The step outlives the 2 s heartbeat by 4 s: under Git Bash each watchdog fork costs real time
    # the nominal ``elapsed`` does not count (FH-WINDOWS-PREPUSH-SHELL).
    proc, _ = _run(repo, runner_body="sleep 6", env_extra={
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
    # ``$!`` is a pid in the SHELL's namespace (an MSYS pid under Git Bash, not a Windows one), so
    # the shell that spoke it answers whether it lives (FH-WINDOWS-PREPUSH-SHELL).
    probe = subprocess.run([_BASH, "-c", f"kill -0 {grandchild}"], capture_output=True,
                           stdin=subprocess.DEVNULL, check=False)
    assert probe.returncode != 0, f"grandchild {grandchild} survived the deadline kill"
    assert "prepush: RED" in _wait_for(repo.parent / "notified.log")


def test_a_budget_that_is_not_a_whole_number_of_seconds_refuses_before_running(repo: Path):
    proc, calls = _run(repo, env_extra={"PREPUSH_GATES_BUDGET": "1.5"})
    assert proc.returncode == 2 and calls == ""


def test_without_an_explicit_interpreter_the_doc_cite_step_finds_the_shared_venv_then_python3(repo: Path):
    """FH-PREPUSH-BARE-PYTHON-LINUX: a bare `python` is absent on the Linux box. Mutation: default `PY`
    back to `python` -> neither stub runs the doc-cite step (exit 127 or the wrong interpreter), red."""
    log = repo.parent / "calls.log"
    venv = repo.parent / "venv"
    (venv / "bin").mkdir(parents=True)
    _stub(venv / "bin" / "python", 0, log, f'echo "venv-python" >> "{log}"')
    env = {key: value for key, value in os.environ.items() if key not in {"PREPUSH_PYTHON", "HERMES_PYTHON"}}
    env = {**env, "PREPUSH_RUNNER": str(_stub(repo.parent / "runner.sh", 0, log)),
           "PREPUSH_GATES_RUNNER": str(repo.parent / "runner.sh"),
           "PREPUSH_NOTIFY": str(_stub(repo.parent / "notify.sh", 0, repo.parent / "notified.log")),
           "HERMES_TEST_VENV": str(venv)}
    run = lambda env: subprocess.run([_BASH, str(repo / "scripts" / "prepush.sh")], cwd=repo, env=env,
                                     capture_output=True, text=True, encoding="utf-8",
                                     stdin=subprocess.DEVNULL, check=False)
    proc = run(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "venv-python" in log.read_text(encoding="utf-8")
    log.unlink()
    shims = repo.parent / "shims"
    shims.mkdir()
    _stub(shims / "python3", 0, log, f'echo "python3-on-path" >> "{log}"')
    proc = run({**env, "HERMES_TEST_VENV": str(repo.parent / "no-venv"), "PATH": f"{shims}{os.pathsep}{env['PATH']}"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "python3-on-path" in log.read_text(encoding="utf-8")


def test_a_name_census_gate_runs_in_its_own_step_never_the_touched_lane(repo: Path):
    """FH-PREPUSH-TOUCHED-BUDGET-VS-NAME-CENSUS. KILLING MUTATION: route every path to ``LANE`` (drop
    the ``PREPUSH_CENSUS_GATES`` case) → the census gates ride the touched lane's argv and no census
    step runs: the plan line and the argv assertions red."""

    census = ("tests/tooling/test_no_ladder_routing.py", "tests/agent_runtime/test_duplicate_helper_bodies.py")
    for path in census:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("x = 5\n", encoding="utf-8")
    proc, calls = _run(repo, *census)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "step census — budget 30s, deadline 60s" in proc.stdout and "✔ census" in proc.stdout
    _gates, _cite, census_argv, lane_argv = (line.split() for line in calls.splitlines())
    assert sorted(p for p in census_argv if p.startswith("tests/")) == sorted(census)
    assert not set(census) & set(lane_argv) and "tests/a/test_committed.py" in lane_argv


def _ledger(repo: Path) -> list[dict]:
    path = repo / "_lane_logs" / "prepush_overruns.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


# FH-PREPUSH-CAP-TIGHT. KILLING MUTATION: lift the whole-run cap (``left`` never shortens the
# deadline) -> the 30 s sleep runs to its 60 s deadline, the run takes > 20 s and exits 1, not 3.
@pytest.mark.timeout(60)
def test_the_whole_run_cap_kills_the_running_step_starts_no_other_and_exits_3(repo: Path):
    started = time.monotonic()
    proc, calls = _run(repo, runner_body="sleep 30", env_extra={
        "PREPUSH_CAP": "3", "PREPUSH_GATES_BUDGET": "1", "PREPUSH_GATES_DEADLINE": "60",
        "PREPUSH_HEARTBEAT": "1", "PREPUSH_LIVE_LANES": "12"})
    assert time.monotonic() - started < 20, proc.stdout
    assert proc.returncode == 3, proc.stdout
    assert "✘ prepush: gates killed at the 3s whole-run cap" in proc.stdout
    assert "✘ prepush: doc-cite not started — the 3s whole-run cap is spent (during gates)" in proc.stdout
    assert "touched not started" in proc.stdout
    assert len(calls.splitlines()) == 1, calls  # only the capped step ever ran
    last = proc.stdout.rstrip().splitlines()[-1]
    assert last.startswith("✘ prepush: CAPPED") and "do not push" in last
    (row,) = _ledger(repo)
    assert row["step"] == "gates" and row["outcome"] == "capped" and row["cap_s"] == 3
    assert row["deadline_s"] == 3 and row["live_lanes"] == 12
    # The landing chain gates on the exit: a capped run never reaches the push.
    chain = subprocess.run([_BASH, "-c", f'"{_BASH}" scripts/prepush.sh && echo PUSHED'], cwd=repo,
                           env={**os.environ, "PREPUSH_CAP": "2", "PREPUSH_GATES_DEADLINE": "60",
                                "PREPUSH_RUNNER": str(repo.parent / "runner.sh"),
                                "PREPUSH_GATES_RUNNER": str(repo.parent / "runner.sh"),
                                "PREPUSH_PYTHON": str(repo.parent / "cite.sh"), "PREPUSH_NOTIFY": "off"},
                           capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, check=False)
    assert chain.returncode == 3 and "PUSHED" not in chain.stdout, chain.stdout


def test_a_cap_that_is_not_a_whole_number_refuses_before_running(repo: Path):
    proc, calls = _run(repo, env_extra={"PREPUSH_CAP": "0"})
    assert proc.returncode == 2 and calls == ""


# FH-PREPUSH-OVERRUN-LEDGER. KILLING MUTATION: skip the ledger write on a kill (drop the ``killed``
# outcome's ``_ledger`` call) -> the kill leaves no line and the summary names no overrun.
@pytest.mark.timeout(60)
def test_every_overrun_and_kill_is_a_ledger_line_and_the_summary_names_its_row(repo: Path):
    proc, _ = _run(repo, runner_body="sleep 3", env_extra={
        "PREPUSH_GATES_BUDGET": "1", "PREPUSH_GATES_DEADLINE": "30",
        "PREPUSH_TOUCHED_BUDGET": "1", "PREPUSH_TOUCHED_DEADLINE": "2", "PREPUSH_HEARTBEAT": "1",
        "PREPUSH_LIVE_LANES": "7"})
    assert proc.returncode == 1, proc.stdout
    rows = _ledger(repo)
    assert [(r["step"], r["outcome"]) for r in rows] == [("gates", "slow"), ("touched", "killed")], rows
    slow, killed = rows
    assert slow["budget_s"] == 1 and slow["deadline_s"] == 30 and slow["wall_s"] >= 3 and slow["exit"] == 0
    assert killed["deadline_s"] == 2 and killed["exit"] != 0
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()
    for row in rows:
        assert row["head"] == head and row["live_lanes"] == 7 and row["cap_s"] == 240
        assert row["load"] is None or isinstance(row["load"], float | int)
        assert row["ts"].endswith("Z")
    assert "prepush: 2 overrun(s)" in proc.stdout
    assert "overrun: gates slow:" in proc.stdout and "owes row FH-PREPUSH-GATES-OVER-BUDGET" in proc.stdout
    assert "overrun: touched killed:" in proc.stdout and "owes row FH-PREPUSH-TOUCHED-OVER-BUDGET" in proc.stdout
    # The ledger only grows: a second run appends, never rewrites.
    _run(repo, runner_body="sleep 2", env_extra={"PREPUSH_GATES_BUDGET": "1", "PREPUSH_HEARTBEAT": "1"})
    assert len(_ledger(repo)) == 3


def test_a_green_run_inside_budget_writes_no_ledger_line(repo: Path):
    proc, _ = _run(repo)
    assert proc.returncode == 0, proc.stdout
    assert _ledger(repo) == [] and "overrun(s)" not in proc.stdout and "overrun:" not in proc.stdout


# FH-PREPUSH-CAP-TIGHT, the touched lane's shards. KILLING MUTATION: send every file to ``PLAIN``
# (drop the ``SHARD_FILES`` branch) -> the slow file runs once whole and the shard argv never appears.
def test_a_touched_file_last_run_slow_runs_as_node_id_shards_unless_listed_unsharded(repo: Path):
    (repo / "test_durations.json").write_text(json.dumps({
        "tests/a/test_committed.py": 25.4, "tests/a/test_untracked.py": 3.0}), encoding="utf-8")
    proc, calls = _run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sharded: tests/a/test_committed.py into 3 (last run 26s)" in proc.stdout
    lanes = calls.splitlines()[2:]
    shards = sorted(line for line in lanes if "--hermes-shard=" in line)
    assert shards == [f"-j 1 tests/a/test_committed.py -- -p scripts._bundle_plugin.hermes_shard --hermes-shard={i}/3"
                      for i in range(3)], lanes
    (plain,) = [line for line in lanes if "--hermes-shard=" not in line]
    assert "tests/a/test_untracked.py" in plain.split() and "tests/a/test_committed.py" not in plain.split()
    # A file whose tests depend on each other's order is never split.
    (repo / "scripts" / "test_files_unsharded.txt").write_text(
        "# header\ntests/a/test_committed.py  # shard 1 red\n", encoding="utf-8")
    (repo.parent / "calls.log").unlink()
    proc, calls = _run(repo)
    assert proc.returncode == 0 and "sharded:" not in proc.stdout
    assert "--hermes-shard" not in calls and "tests/a/test_committed.py" in calls.splitlines()[-1].split()


# FH-PREPUSH-TOUCHED-NAMED-HEAVY-OVER-BUDGET: the runner on Windows keys its record by backslash paths, and
# a forward-slash lookup found none, so nothing ever sharded there. Killing mutation in the script's comment.
def test_a_windows_keyed_duration_record_still_shards(repo: Path):
    (repo / "test_durations.json").write_text(json.dumps({r"tests\a\test_committed.py": 25.4}), encoding="utf-8")
    proc, calls = _run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sharded: tests/a/test_committed.py into 3 (last run 26s)" in proc.stdout
    assert calls.count("--hermes-shard=") == 3, calls


def test_a_red_shard_reds_the_touched_step(repo: Path):
    (repo / "test_durations.json").write_text(json.dumps({"tests/a/test_committed.py": 40}), encoding="utf-8")
    proc, _ = _run(repo, runner_body='case "$*" in *--hermes-shard=2/4*) exit 1 ;; esac')
    assert proc.returncode == 1, proc.stdout
    assert "touched (exit 1)" in proc.stdout.splitlines()[-1]
