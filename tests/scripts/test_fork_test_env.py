"""The fork's env-extension door: scripts/fork_test_env.txt names what crosses `env -i`.

Fork-hygiene CLASS row (2026-10-15): run_tests.sh's allowlist is upstream-owned, so
every fork test variable needed a wrapper or another upstream hunk. The door is a
tracked NAME list read by ``scripts/_fork_test_env.sh``; it is run for real here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# A bare "bash" from Python on Windows is WSL (Running the tests.md); name Git Bash.
BASH = r"C:\Program Files\Git\bin\bash.exe" if sys.platform == "win32" else "bash"


def _extend(tmp_path: Path, listing: str, env: dict) -> subprocess.CompletedProcess:
    lst = tmp_path / "list.txt"
    lst.write_text(listing, encoding="utf-8", newline="\n")
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    script = f'. "{door}"; TEST_ENV=(PRE=1); fork_test_env_extend "{lst.as_posix()}"; rc=$?; ' \
             'printf "%s\\n" "${TEST_ENV[@]}"; exit $rc'
    return subprocess.run([BASH, "-c", script], env={**os.environ, **env}, capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_a_listed_set_variable_crosses_and_nothing_else_does(tmp_path):
    proc = _extend(
        tmp_path,
        "# reason\nFORK_DOOR_A  # why A\n\nFORK_DOOR_UNSET\n",
        {"FORK_DOOR_A": "a b", "FORK_DOOR_NOT_LISTED": "x"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["PRE=1", "FORK_DOOR_A=a b"]


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
@pytest.mark.parametrize("bad", ["HERMES_*", "1ABC", "A-B"])
def test_a_line_that_is_not_a_name_fails_the_run(tmp_path, bad):
    proc = _extend(tmp_path, f"{bad}\n", {})
    assert proc.returncode == 2
    assert "not a variable name" in proc.stderr


def test_run_tests_sources_the_door_and_the_shipped_list_holds_only_names():
    script = (REPO / "scripts" / "run_tests.sh").read_text(encoding="utf-8")
    assert 'fork_test_env_extend "$SCRIPT_DIR/fork_test_env.txt" || exit 2' in script
    names = [
        line.split("#", 1)[0].strip()
        for line in (REPO / "scripts" / "fork_test_env.txt").read_text(encoding="utf-8").splitlines()
    ]
    assert [n for n in names if n] == ["HERMES_TEST_IDLE_BOX"]


def _door(script: str, env: dict) -> subprocess.CompletedProcess:
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    full = f'_has_pytest() {{ [ -n "$1" ] && [ -x "$1" ]; }}; . "{door}"; {script}'
    base = {k: v for k, v in os.environ.items() if k not in ("HERMES_PYTHON", "CI", "__HERMES_ACTIVATED")}
    return subprocess.run([BASH, "-c", full], env={**base, **env}, capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_no_hermes_python_and_no_shared_venv_refuses(tmp_path):
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": (tmp_path / "none").as_posix()})
    assert proc.returncode == 1 and "no shared test venv" in proc.stderr


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_no_hermes_python_uses_the_shared_venv(tmp_path):
    exe = tmp_path / "venv" / "bin" / "python"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": (tmp_path / "venv").as_posix()})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == f"HP={(tmp_path / 'venv').as_posix()}/bin/python"


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_an_interpreter_inside_the_store_root_is_refused(tmp_path):
    py = Path(sys.executable).as_posix()
    root = Path(sys.executable).resolve().parent.as_posix()  # a stand-in store root holding this interpreter
    refused = _door("fork_refuse_live_home_interpreter", {"PYTHON": py, "REAL_HERMES_ROOT": root})
    assert refused.returncode == 1 and "inside the live Hermes home" in refused.stderr
    allowed = _door("fork_refuse_live_home_interpreter", {"PYTHON": py, "REAL_HERMES_ROOT": tmp_path.as_posix()})
    assert allowed.returncode == 0, allowed.stderr


def test_run_tests_calls_both_moved_policies():
    script = (REPO / "scripts" / "run_tests.sh").read_text(encoding="utf-8")
    assert script.index(". \"$SCRIPT_DIR/_fork_test_env.sh\"") < script.index("fork_shared_test_venv_fallback")
    assert "fork_refuse_live_home_interpreter" in script
