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
        )
    finally:
        sentinel.kill()
        sentinel.wait(timeout=30)

    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "refusing: the box is not idle" in proc.stderr
    named = [line for line in proc.stderr.splitlines() if "fake-pytest-sentinel" in line]
    assert named and named[0].split()[0] == str(sentinel.pid), proc.stderr
