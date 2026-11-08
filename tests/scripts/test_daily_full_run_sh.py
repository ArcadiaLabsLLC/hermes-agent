"""`scripts/daily_full_run.sh` — the once-a-day breadth run (FH-DAILY-FULL-RUN).

Each test copies the script (and `scripts/prepush.sh`, whose gate lists it reads) into a
throwaway directory; the test runner and the doc-cite interpreter are stubs that record their
argv and exit as told, so the step order, the logs, the timeouts and the summary are read off the
real script without running the suite.
"""

from __future__ import annotations

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


def _stub(path: Path, log: Path, body: str = "") -> Path:
    path.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\n{body}\nexit 0\n', encoding="utf-8", newline="\n")
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


def _run(tree: Path, *args: str, runner_body: str = "", cite_body: str = "", env_extra: dict[str, str] | None = None):
    log = tree.parent / "calls.log"
    env = {**os.environ,
           "DAILY_RUNNER": str(_stub(tree.parent / "runner.sh", log, runner_body)),
           "DAILY_PYTHON": str(_stub(tree.parent / "cite.sh", log, cite_body)),
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
    body = ('case "$*" in *tests/tooling*|*tests/*) ;; *) echo "FAILED tests/a/test_x.py::test_one - boom";'
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
