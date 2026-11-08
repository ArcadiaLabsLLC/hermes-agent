"""`scripts/daily_full_run.sh` — the once-a-day breadth run (FH-DAILY-FULL-RUN).

Each test copies the script (and `scripts/prepush.sh`, whose gate lists it reads) into a
throwaway directory; the test runner and the doc-cite interpreter are stubs that record their
argv and exit as told, so the step order, the logs, the timeouts and the summary are read off the
real script without running the suite.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

#: The root conftest's ``real_bash``, never a bare ``bash`` that Windows resolves to WSL.
_BASH = "bash"


@pytest.fixture(autouse=True)
def _real_bash(monkeypatch, real_bash):
    monkeypatch.setattr(sys.modules[__name__], "_BASH", real_bash)


def _stub(path: Path, log: Path, body: str = "", prelude: str = "") -> Path:
    path.write_text(f'#!/usr/bin/env bash\n{prelude}\necho "$@" >> "{log}"\n{body}\nexit 0\n', encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in ("daily_full_run.sh", "prepush.sh"):
        shutil.copy2(REPO / "scripts" / name, root / "scripts" / name)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, stdin=subprocess.DEVNULL)
    return root


#: the stub interpreter's answer for ``scripts/daily_suite_files.py <list-out>``: a one-file list and
#: one node row's ``--deselect``; it is not logged, so ``calls`` holds only the steps.
_SUITE_LIST = ('case "$1" in *daily_suite_files.py) printf \'tests/a/test_x.py\\n\' > "$2";'
               ' echo "--deselect=tests/n/test_z.py::test_flaky[p0]"; exit 0 ;; esac')


def _run(tree: Path, *args: str, runner_body: str = "", cite_body: str = "", suite_list: str = _SUITE_LIST,
         env_extra: dict[str, str] | None = None):
    log = tree.parent / "calls.log"
    env = {**os.environ,
           "DAILY_RUNNER": str(_stub(tree.parent / "runner.sh", log, runner_body)),
           "DAILY_PYTHON": str(_stub(tree.parent / "cite.sh", log, cite_body, prelude=suite_list)),
           **(env_extra or {})}
    proc = subprocess.run([_BASH, str(tree / "scripts" / "daily_full_run.sh"), *args], cwd=tree, env=env,
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, check=False)
    return proc, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])


def test_the_dry_run_names_every_step_with_its_timeout_and_runs_nothing(tree: Path):
    out = tree.parent / "out"
    proc, calls = _run(tree, "--dry-run", f"--out={out}")
    assert proc.returncode == 0, proc.stderr
    for step, seconds in (("suite", 5400), ("gates", 300), ("doc-cite", 120), ("census", 600), ("tooling", 2400)):
        assert f"step {step} — timeout {seconds}s" in proc.stdout
    assert "tests/tooling/test_work_queue_row_grammar.py" in proc.stdout  # prepush's own gate list
    assert "tests/tooling/test_no_ladder_routing.py tests/agent_runtime/test_duplicate_helper_bodies.py" in proc.stdout
    assert calls == [] and not out.exists()


def test_a_green_run_exits_0_with_one_log_per_step_and_a_summary(tree: Path):
    out = tree.parent / "out"
    proc, calls = _run(tree, f"--out={out}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 5
    for step in ("suite", "gates", "doc-cite", "census", "tooling"):
        assert (out / f"{step}.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=0")
    assert (out / "summary.txt").read_text(encoding="utf-8").rstrip().endswith("✔ daily_full_run: green (5 step(s))")


# KILLING MUTATION: skip a step after an earlier red (``[ "${#REDS[@]}" -gt 0 ] && continue`` at the
# loop's top) -> only the suite runs, four logs are missing and this reds.
def test_every_step_runs_after_a_red_and_the_summary_names_each_red_and_its_files(tree: Path):
    out = tree.parent / "out"
    body = ('case "$*" in *--files-from=*) echo "FAILED tests/a/test_x.py::test_one - boom";'
            ' echo "  ║ FAILED tests/b/test_y.py::test_two"; exit 1 ;; esac')
    proc, calls = _run(tree, f"--out={out}", runner_body=body, cite_body="exit 3")
    assert proc.returncode == 1, proc.stdout
    assert len(calls) == 5, calls  # suite, gates, doc-cite, census, tooling: none skipped
    assert (out / "suite.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=1")
    assert (out / "doc-cite.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=3")
    assert (out / "tooling.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=0")
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "✘ suite red (exit 1)" in summary and "✘ doc-cite red (exit 3)" in summary
    assert "owes a row filed today" in summary
    assert "    red: tests/a/test_x.py" in summary and "    red: tests/b/test_y.py" in summary
    assert summary.rstrip().endswith("✘ daily_full_run: RED — suite doc-cite — file each red as a row the same day")
    assert "✔ gates" in summary and "✔ census" in summary


@pytest.mark.timeout(60)
def test_a_step_past_its_timeout_is_killed_named_and_the_run_goes_on(tree: Path):
    out = tree.parent / "out"
    started = time.monotonic()
    proc, calls = _run(tree, f"--out={out}", runner_body='case "$*" in *test_queue_row_guard*) sleep 30 ;; esac',
                       env_extra={"DAILY_GATES_TIMEOUT": "1"})
    assert time.monotonic() - started < 25, proc.stdout
    assert proc.returncode == 1, proc.stdout
    assert (out / "gates.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=124")
    assert "✘ gates timed out at 1s" in (out / "summary.txt").read_text(encoding="utf-8")
    assert len(calls) == 5


def test_only_runs_the_named_steps_and_refuses_an_unknown_one(tree: Path):
    out = tree.parent / "out"
    proc, calls = _run(tree, f"--out={out}", "--only=doc-cite")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1 and "doc_cite_adjacency.py" in calls[0]
    assert sorted(p.name for p in out.iterdir()) == ["doc-cite.log", "summary.txt"]
    proc, _ = _run(tree, "--only=nope")
    assert proc.returncode == 2
    proc, _ = _run(tree, "--bogus")
    assert proc.returncode == 2


# KILLING MUTATION: the suite step without its list (``suite) CMD=(bash "$RUNNER" -j "$JOBS") ;;``, the
# 2026-11-08 shape that ran all 902 skip-listed files and reported 12 of them red) -> this reds.
def test_the_suite_runs_the_skip_list_free_list_and_deselects_each_node_row(tree: Path):
    out = tree.parent / "out"
    proc, calls = _run(tree, f"--out={out}", "--only=suite")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls == [f"-j 24 --files-from={out}/suite.files --deselect=tests/n/test_z.py::test_flaky[p0]"]
    assert (out / "suite.files").read_text(encoding="utf-8") == "tests/a/test_x.py\n"


# KILLING MUTATION: the suite step's no-list guard off (``if [ "$step" = suite ] && [ "$SUITE_PLAN_RC"
# -ne 0 ]; then`` -> ``if false; then``) -> the runner runs with an unbuilt list and this reds.
def test_a_suite_list_that_cannot_be_built_reds_the_suite_and_never_runs_it(tree: Path):
    out = tree.parent / "out"
    proc, calls = _run(tree, f"--out={out}", "--only=suite,tooling",
                       suite_list='case "$1" in *daily_suite_files.py) exit 2 ;; esac')
    assert proc.returncode == 1, proc.stdout
    assert calls == ["-j 24 tests/tooling"], calls  # the suite never ran; the next step still did
    assert (out / "suite.log").read_text(encoding="utf-8").rstrip().endswith("EXIT=2")
    assert "✘ suite red (no suite list, exit 2)" in (out / "summary.txt").read_text(encoding="utf-8")


def _suite_files_module():
    spec = importlib.util.spec_from_file_location("daily_suite_files", REPO / "scripts" / "daily_suite_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# KILLING MUTATION: keep every discovered file (``if rel in listed:`` -> ``if False:`` in
# scripts/daily_suite_files.py) -> the skip-listed files are back in the list and this reds.
def test_the_suite_list_is_the_runners_discovery_minus_every_skip_list_file_row():
    module = _suite_files_module()
    kept, deselects, dropped = module.suite_plan(REPO)
    plan = sys.modules["run_tests_bundled_plan"]
    rows = plan.load_skip_list(REPO / plan.SKIP_LIST)
    file_rows = {row.file for row in rows.values() if not row.node}
    discovered = [p.relative_to(REPO).as_posix() for p in sys.modules["run_tests_parallel"]._discover_files([REPO / "tests"])]
    assert dropped > 0 and not file_rows & set(kept)
    assert sorted(kept + [rel for rel in discovered if rel in file_rows]) == sorted(discovered)
    assert "tests/scripts/test_daily_full_run_sh.py" in kept  # a fork file always runs
    assert "tests/hermes_cli/test_source_check.py" not in kept  # a P0 freeze file never does
    assert deselects == [f"--deselect={row.path}" for row in rows.values() if row.node]
