"""``scripts/run_tests_idle.sh`` refuses to run while a suite is running (design sweep D3.01).

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md`` § D3.01
stage 3. Owner ruling 2026-10-10: the timing files run on an idle box only. A
test always runs under pytest, so the box is never idle here; the positive
control is that a planted ``pytest`` process is NAMED in the refusal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_bash() -> str:
    bash = shutil.which("bash")
    if bash is None or "system32" in bash.lower():  # WSL's launcher is not the repo's shell
        pytest.skip("no POSIX bash on PATH")
    return bash


def test_the_idle_lane_refuses_and_names_a_running_pytest():
    bash = _git_bash()
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", "fake-pytest-sentinel"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        proc = subprocess.run(
            [bash, str(_REPO_ROOT / "scripts" / "run_tests_idle.sh"), "--check"],
            cwd=_REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env=dict(os.environ),
            check=False,
        )
    finally:
        sentinel.kill()
        sentinel.wait(timeout=30)

    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "refusing: the box is not idle" in proc.stderr
    named = [line for line in proc.stderr.splitlines() if "fake-pytest-sentinel" in line]
    assert named and named[0].split()[0] == str(sentinel.pid), proc.stderr


def _check(bash: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bash, str(_REPO_ROOT / "scripts" / "run_tests_idle.sh"), "--check"],
        cwd=_REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env={**os.environ, **env}, check=False,
    )


def test_a_loaded_host_is_not_idle_and_the_refusal_carries_the_measured_load(tmp_path):
    """FH-IDLE-BOX-CHECK-IGNORES-HOST-LOAD: no suite process alive is not enough on a box
    shared with other repos' lanes; the 1-min load average must be under the ceiling too.

    Whether another suite process is alive depends on the box, so the claim is the exit
    code and the LOAD line; the positive control is the same run at load 0.40, which
    carries no load line."""

    bash = _git_bash()
    cores = os.cpu_count() or 1
    loaded = tmp_path / "loaded"
    loaded.write_text(f"{cores * 2}.00 1.00 1.00 3/400 12345\n", encoding="utf-8")
    calm = tmp_path / "calm"
    calm.write_text("0.40 0.30 0.20 1/400 12345\n", encoding="utf-8")

    hot = _check(bash, HERMES_IDLE_LOADAVG_FILE=str(loaded))
    cool = _check(bash, HERMES_IDLE_LOADAVG_FILE=str(calm))

    assert hot.returncode == 3, hot.stdout + hot.stderr
    assert f"host is loaded: 1-min load average {cores * 2}.00 on " in hot.stderr
    assert "ceiling" in hot.stderr
    assert "host is loaded" not in cool.stderr, cool.stderr


def test_a_malformed_load_fraction_fails_the_run_rather_than_using_the_default():
    bash = _git_bash()
    for bad in ("abc", "0", "-1"):
        proc = _check(bash, HERMES_IDLE_LOAD_FRACTION=bad)
        assert proc.returncode == 2 and "HERMES_IDLE_LOAD_FRACTION" in proc.stderr, (bad, proc.stderr)
