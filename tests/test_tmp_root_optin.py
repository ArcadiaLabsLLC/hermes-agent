"""The opt-in test-temp root (suite-perf Stage 7) redirects, degrades, prunes.

The function under test is conftest's `_maybe_redirect_test_tmp`, exercised
against a passed-in environ so these tests never move the RUNNING session's
temp out from under it.
"""

import os
import time

import pytest

from tests._downstream.conftest_plugin import (
    _maybe_redirect_test_tmp,
    _release_test_tmp_run_dir,
)


def test_absent_var_changes_nothing():
    env = {}
    assert _maybe_redirect_test_tmp(env) is None
    assert env == {}


def test_missing_directory_degrades_to_todays_behavior(tmp_path):
    env = {"HERMES_TEST_TMP_ROOT": str(tmp_path / "does-not-exist")}
    assert _maybe_redirect_test_tmp(env) is None
    assert "TMP" not in env


def test_real_root_redirects_all_three_keys_into_a_fresh_run_dir(tmp_path):
    env = {"HERMES_TEST_TMP_ROOT": str(tmp_path)}
    run_dir = _maybe_redirect_test_tmp(env)
    assert run_dir is not None
    assert os.path.isdir(run_dir)
    assert os.path.dirname(run_dir) == str(tmp_path)
    assert env["TMP"] == env["TEMP"] == env["TMPDIR"] == run_dir


def test_two_runs_get_distinct_dirs(tmp_path):
    a = _maybe_redirect_test_tmp({"HERMES_TEST_TMP_ROOT": str(tmp_path)})
    b = _maybe_redirect_test_tmp({"HERMES_TEST_TMP_ROOT": str(tmp_path)})
    assert a != b


def test_aged_run_dirs_are_pruned_and_fresh_ones_kept(tmp_path):
    old = tmp_path / "run-old"
    fresh = tmp_path / "run-fresh"
    old.mkdir()
    fresh.mkdir()
    aged = time.time() - 8 * 24 * 3600
    os.utime(old, (aged, aged))
    _maybe_redirect_test_tmp({"HERMES_TEST_TMP_ROOT": str(tmp_path)})
    assert not old.exists()
    assert fresh.exists()


def _age(path, days=8):
    aged = time.time() - days * 24 * 3600
    os.utime(path, (aged, aged))


def test_an_aged_run_dir_holding_a_read_only_file_is_pruned(tmp_path):
    """Git writes its objects read-only; on Windows ``rmtree(ignore_errors=True)``
    leaves such a tree behind, and every later process re-walked it (lane SPEED,
    2026-09-24: 322 such trees re-failed by each of ~1,840 processes)."""
    old = tmp_path / "run-old"
    obj = old / "repo" / ".git" / "objects" / "7f"
    obj.mkdir(parents=True)
    blob = obj / "4e9e16"
    blob.write_text("x", encoding="utf-8")
    os.chmod(blob, 0o444)
    _age(old)
    _maybe_redirect_test_tmp({"HERMES_TEST_TMP_ROOT": str(tmp_path)})
    assert not old.exists()


def test_the_sweep_runs_once_per_interval_not_once_per_process(tmp_path):
    env = {"HERMES_TEST_TMP_ROOT": str(tmp_path)}
    _maybe_redirect_test_tmp(env)  # first process: sweeps, stamps
    late = tmp_path / "run-late"
    late.mkdir()
    _age(late)
    _maybe_redirect_test_tmp(dict(env))  # a sibling process inside the interval
    assert late.exists(), "a second process re-swept inside the interval"
    # Positive control: the same tree IS pruned once the stamp is due again,
    # so the survival above is the throttle, not a sweep that cannot see it.
    _age(tmp_path / ".prune-stamp", days=1)
    _maybe_redirect_test_tmp(dict(env))
    assert not late.exists()


def test_a_run_dir_older_than_a_day_is_pruned_and_a_younger_one_kept(tmp_path):
    two_days = tmp_path / "run-two-days"
    half_day = tmp_path / "run-half-day"
    two_days.mkdir()
    half_day.mkdir()
    _age(two_days, days=2)
    _age(half_day, days=0.5)
    _maybe_redirect_test_tmp({"HERMES_TEST_TMP_ROOT": str(tmp_path)})
    assert not two_days.exists()
    assert half_day.exists()


def test_a_green_session_removes_its_own_run_dir_and_a_red_one_keeps_it(tmp_path):
    env = {"HERMES_TEST_TMP_ROOT": str(tmp_path)}
    green = _maybe_redirect_test_tmp(dict(env))
    red = _maybe_redirect_test_tmp(dict(env))
    unfinished = _maybe_redirect_test_tmp(dict(env))
    for run_dir in (green, red, unfinished):
        (tmp_path / os.path.basename(run_dir) / "leftover.txt").write_text("x", encoding="utf-8")

    assert _release_test_tmp_run_dir(green, 0) is True
    assert _release_test_tmp_run_dir(red, 1) is False
    assert _release_test_tmp_run_dir(unfinished, None) is False

    assert not os.path.exists(green)
    assert os.path.isdir(red) and os.path.isdir(unfinished)


def _pytest_child(tmp_root, *argv):
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, HERMES_TEST_TMP_ROOT=str(tmp_root))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_dirs(root):
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("run-"))


@pytest.mark.timeout(120)
def test_a_real_green_session_leaves_no_run_dir_behind(tmp_path):
    """The join: pytest's hook records the status, the at-exit handler acts on it."""
    green_root = tmp_path / "green"
    green_root.mkdir()
    done = _pytest_child(green_root, "tests/test_tmp_root_optin.py::test_absent_var_changes_nothing")
    assert done.returncode == 0, done.stdout[-2000:]
    assert _run_dirs(green_root) == []
    # Positive control: a session that never finishes (usage error before the
    # session runs) keeps its dir, so the empty root above is the release, not
    # a redirect that never happened.
    kept_root = tmp_path / "kept"
    kept_root.mkdir()
    _pytest_child(kept_root, "--no-such-option")
    assert len(_run_dirs(kept_root)) == 1
