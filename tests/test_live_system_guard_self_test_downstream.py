"""Fork-owned half of ``tests/test_live_system_guard_self_test.py``.

The fork's ``_live_system_guard`` (``tests/conftest.py``) also refuses to START
a hermes backend (ML-14 / B20(i)): ``gateway run``, ``serve``, ``dashboard``,
``harness serve`` in every argv spelling. Every blocked case raises BEFORE the
spawn; the pass-through cases are its anti-vacuity. Upstream's fail-closed
``_refuse_to_fire_live_weapons`` is imported by name so it guards these too.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.test_live_system_guard_self_test import (  # noqa: F401 — upstream autouse fixture
    _refuse_to_fire_live_weapons,
)


def test_subprocess_run_hermes_gateway_run_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["hermes", "gateway", "run", "--profile", "x"])

def test_subprocess_run_hermes_serve_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["hermes", "serve", "--port", "8090"])

def test_subprocess_run_python_m_hermes_cli_dashboard_blocked():
    """The argv an old desktop app shell sends."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", "dashboard", "--no-open"]
        )

def test_subprocess_popen_harness_serve_blocked():
    """``harness serve`` puts the subcommand PAST position 1 — still caught."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(
            [sys.executable, "-m", "hermes_cli.main", "harness", "serve", "--ndjson"]
        )

def test_subprocess_run_flag_before_subcommand_blocked():
    """``hermes --profile work gateway run`` — a flag and its value first."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["hermes", "--profile", "work", "gateway", "run"])

def test_subprocess_run_absolute_path_hermes_serve_blocked():
    """A venv's ``bin/hermes`` is the same entry point under another spelling."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["/home/dev/.venv/bin/hermes", "serve"])

def test_subprocess_run_bash_c_hermes_gateway_blocked():
    """The wrapper shape: argv[0] is bash, the backend is in its argument."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["bash", "-c", "hermes gateway run"])

def test_os_system_hermes_dashboard_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.system("hermes dashboard --no-open")

# The pass-through cases spawn an entry point named ``hermes`` that does not
# exist: the guard reads it as the hermes entry point, and a pass-through is
# proved by the OS refusing the spawn (FileNotFoundError), never by a process
# running. (``python -c pass hermes …`` cannot prove it: since 10aa344964 the
# guard stops at CODE, so its tail is inert whatever the classifier says.)


def _absent_hermes(tmp_path) -> str:
    return str(tmp_path / "hermes")


def test_non_backend_hermes_subcommand_passes_through(tmp_path):
    """``hermes status``-shaped argv is not a backend spawn and must run."""
    with pytest.raises(FileNotFoundError):
        subprocess.run([_absent_hermes(tmp_path), "status"])
    with pytest.raises(RuntimeError, match="live-system guard"):  # control: same entry point, a backend verb
        subprocess.run([_absent_hermes(tmp_path), "serve"])

def test_hermes_profile_verb_passes_through(tmp_path):
    """Nor is ``hermes profile list`` — the arm is keyed to the subcommand."""
    with pytest.raises(FileNotFoundError):
        subprocess.run([_absent_hermes(tmp_path), "profile", "list"])

@pytest.mark.spawns_gateway_lookalike
def test_gateway_lookalike_marker_allows_only_gateway_shape(tmp_path):
    with pytest.raises(FileNotFoundError):  # the marker lets the gateway shape through to the OS
        subprocess.run([_absent_hermes(tmp_path), "gateway", "run"])
    for subcommand in ("serve", "dashboard"):
        with pytest.raises(RuntimeError, match="live-system guard"):
            subprocess.run([_absent_hermes(tmp_path), subcommand])
