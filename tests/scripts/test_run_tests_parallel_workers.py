"""The runner's automatic worker count is capped, and the choice is announced."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "run_tests_parallel.py"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("run_tests_parallel_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("cpu_count", "expected"), [(32, 8), (8, 8), (4, 4), (1, 1), (None, 4)])
def test_default_jobs_is_cpu_count_capped_at_eight(runner, cpu_count, expected):
    assert runner._adaptive_default_jobs(cpu_count) == expected


def test_adaptive_choice_is_announced_when_nothing_set_it(runner, monkeypatch, capsys):
    monkeypatch.delenv("HERMES_TEST_WORKERS", raising=False)
    runner._announce_adaptive_jobs(["tests/foo"], 8)
    out = capsys.readouterr().out
    assert "Adaptive worker default:" in out
    assert "cap=8, selected=8" in out


@pytest.mark.parametrize("args", [["-j", "3"], ["-j3"], ["--jobs", "3"], ["--jobs=3"]])
def test_explicit_jobs_flag_is_not_announced(runner, monkeypatch, capsys, args):
    monkeypatch.delenv("HERMES_TEST_WORKERS", raising=False)
    runner._announce_adaptive_jobs(args, 3)
    assert capsys.readouterr().out == ""


def test_env_override_is_not_announced(runner, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TEST_WORKERS", "3")
    runner._announce_adaptive_jobs([], 3)
    assert capsys.readouterr().out == ""
