"""Fork-owned tests moved out of ``tests/scripts/test_run_tests_parallel.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from test_run_tests_parallel import (  # noqa: F401 — upstream names the moved tests use
    _make_probe_dir,
)


def test_a_probe_dir_roots_the_inner_pytest_on_itself(tmp_path: Path) -> None:
    """The reason this file could run at all inside its own budget.

    Every subprocess test here hands the inner pytest a probe under the system
    temp. With no ini file at or above it, pytest's rootdir lands ABOVE the
    probe and the collection tree is rooted over the whole shared temp
    directory — measured 2026-09-04 at 58.5 s and a `FileNotFoundError` on
    another test process's hermetic home, deleted underneath the walk, against
    1.0 s once the probe carries its own `pytest.ini`.

    ANTI-VACUITY: the rootdir is read out of pytest's own header rather than
    inferred from the file existing, so a `pytest.ini` that pytest declined to
    honour would fail this.
    """

    probe_dir = _make_probe_dir(tmp_path)

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", str(probe_dir)],
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    rootdir = [
        line.split(":", 1)[1].strip()
        for line in proc.stdout.splitlines()
        if line.startswith("rootdir:")
    ]
    assert proc.returncode == 0, proc.stdout
    assert rootdir == [str(probe_dir)], proc.stdout
    assert "2 tests collected" in proc.stdout, proc.stdout


def _load_runner_module():
    """Import scripts/run_tests_parallel.py as a module for unit-level checks."""
    import importlib.util

    repo_root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_rtp_under_test", repo_root / "scripts" / "run_tests_parallel.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TIMEOUT_OUTPUT = "(timed out after 5s; process tree terminated)\n(no output)"


def test_timeout_shape_is_not_retried_in_pool(tmp_path: Path, monkeypatch) -> None:
    """A timeout-shaped result is left for the 1-worker straggler pass."""
    mod = _load_runner_module()
    probe = tmp_path / "test_hang.py"
    calls: list[Path] = []

    def fake_once(file, pytest_args, repo_root, file_timeout):
        calls.append(file)
        return file, 124, _TIMEOUT_OUTPUT, {"passed": 0, "failed": 0}, 5.0

    monkeypatch.setattr(mod, "_run_one_file_once", fake_once)

    _f, rc, output, _summary, _wall = mod._run_one_file(
        probe, [], tmp_path, 5.0, 1
    )

    assert rc == 124
    assert len(calls) == 1, "in-pool retry must not fire for a timeout shape"
    assert "FLAKY" not in output
    assert mod._FLAKY_RESULTS == []
    # …and the straggler pass does claim it.
    assert mod._is_retryable_timeout_result(rc, output, {"passed": 0, "failed": 0})


def test_non_timeout_failure_still_retries_in_pool(tmp_path: Path, monkeypatch) -> None:
    """A plain assertion failure keeps upstream's one-shot flake self-heal."""
    mod = _load_runner_module()
    probe = tmp_path / "test_flake.py"
    calls: list[Path] = []

    def fake_once(file, pytest_args, repo_root, file_timeout):
        calls.append(file)
        if len(calls) == 1:
            return file, 1, "E assert False", {"passed": 0, "failed": 1}, 1.0
        return file, 0, "1 passed", {"passed": 1, "failed": 0}, 1.0

    monkeypatch.setattr(mod, "_run_one_file_once", fake_once)

    _f, rc, output, _summary, wall = mod._run_one_file(probe, [], tmp_path, 5.0, 1)

    assert rc == 0
    assert len(calls) == 2, "the flake retry must still fire for non-timeouts"
    assert "FLAKY" in output
    assert wall == 2.0  # both attempts' wall time is accumulated
    assert [f for f, _out in mod._FLAKY_RESULTS] == [probe]


def test_adaptive_default_jobs_is_capped() -> None:
    """The fork's worker cap survives alongside upstream's retry knob."""
    mod = _load_runner_module()

    assert mod._DEFAULT_MAX_WORKERS == 8
    assert mod._DEFAULT_FILE_RETRIES == 1
    # Small boxes are not inflated; big boxes are capped.
    assert mod._adaptive_default_jobs(2) == 2
    assert mod._adaptive_default_jobs(64) == mod._DEFAULT_MAX_WORKERS
    assert mod._adaptive_default_jobs(None) == 4


def test_file_list_split_keeps_windows_drive_letters(tmp_path: Path) -> None:
    """``--files`` is colon-joined; a bare split() shreds ``C:\\repo\\t.py``.

    Regression: the runner opened a file literally named ``C`` under the repo
    root, so every Windows caller of ``--files`` (CI matrix jobs, the flake
    tests below) died before running anything.
    """
    mod = _load_runner_module()

    assert mod._split_path_list(r"C:\repo\tests\test_a.py") == [
        r"C:\repo\tests\test_a.py"
    ]
    assert mod._split_path_list(r"C:\repo\test_a.py:D:/repo/test_b.py") == [
        r"C:\repo\test_a.py",
        "D:/repo/test_b.py",
    ]
    # POSIX lists are untouched.
    assert mod._split_path_list("tests/a.py:tests/b.py") == [
        "tests/a.py",
        "tests/b.py",
    ]
    assert mod._split_discovery_roots("tests:packages") == ["tests", "packages"]


def test_a_file_list_longer_than_the_os_will_stat_still_splits(monkeypatch) -> None:
    """The list CI actually passes, and the reason nobody saw it break.

    ``--files`` carries one colon-joined slice — 8 slices over ~3,040 files is
    roughly 30 KB of argument — and the split began with an ``exists()`` probe
    for the "the argument IS one path with a colon in it" case. A joined list is
    not a path, and the two hosts disagree about how to say so: Linux's
    ``stat()`` answers ``ENAMETOOLONG`` for anything past ``PATH_MAX`` and
    ``pathlib`` does not ignore that errno, so the probe RAISED; Windows folds
    the same overflow into its ignored winerror set and answers ``False``.

    So every CI matrix slice died in ``_split_path_list`` before collecting a
    test — measured on nekwo/hermes-agent, all 8 slices red with
    ``OSError: [Errno 36] File name too long`` on every main push from
    2026-08-04 (the first run after the probe landed) through 2026-09-05 — while
    the identical call was green on every developer's Windows box.

    Both halves are asserted because either alone is a half-test: the real
    over-long list is what CI passes and is enough on POSIX, and the forced
    ``OSError`` is what makes a Windows author trip here too rather than
    shipping the same asymmetry again.
    """
    mod = _load_runner_module()

    joined = ":".join(f"tests/dir{index}/test_module_{index}.py" for index in range(600))
    assert len(joined) > 4096, "the case needs a list past PATH_MAX"
    assert mod._split_path_list(joined) == joined.split(":")

    def _too_long(self) -> bool:
        raise OSError(36, "File name too long")

    monkeypatch.setattr(mod.Path, "exists", _too_long)
    assert mod._split_path_list("tests/a.py:tests/b.py") == ["tests/a.py", "tests/b.py"]
    assert mod._split_discovery_roots("tests:packages") == ["tests", "packages"]


def _drive_main_over_one_file(
    mod, monkeypatch, tmp_path: Path, attempts: list[tuple[int, str, dict]]
) -> int:
    """Run the runner's ``main`` over one probe file, scripting each attempt.

    In-process on purpose: the thing under test is the SUMMARY's accounting,
    and driving it through a real pytest subprocess would pay ~30 s of this
    repo's collection per attempt to observe an integer.
    """
    probe = tmp_path / "test_straggler_probe.py"
    probe.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    calls: list[Path] = []

    def fake_once(file, pytest_args, repo_root, file_timeout):
        rc, output, summary = attempts[min(len(calls), len(attempts) - 1)]
        calls.append(file)
        return file, rc, output, summary, 1.0

    monkeypatch.setattr(mod, "_run_one_file_once", fake_once)
    # The real one writes test_durations.json into the checkout.
    monkeypatch.setattr(mod, "_save_durations", lambda *a, **k: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run_tests_parallel.py", "--files", str(probe), "-j", "1",
         "--file-retries", "0", "--file-timeout", "5"],
    )
    return mod.main()


_KILLED_ATTEMPT = (124, _TIMEOUT_OUTPUT, {"passed": 0, "failed": 0})


def test_a_straggler_retry_that_passes_is_not_reported_as_zero_collected(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The straggler's collection counts, or the run contradicts itself.

    Observed 2026-09-02 on ``tests/hermes_cli/test_harness_characters_cli.py``:
    the file tripped the per-file wall clock at 8 workers, collected nothing
    into the killed attempt, then passed at 1-worker isolation — and the run
    printed ``RETRY PASS … (95 tests)`` and ``Summary: 95 tests passed, 0
    failed`` followed by ``✗ NO TESTS RAN — 0 collected``. ``tests_collected``
    was accumulated ONLY inside the pool's ``_on_done`` callback, so every
    outcome the straggler pass recovered was invisible to the nothing-ran
    guard. A banner that says "not a pass" over a pass is one an operator
    learns to ignore, which is the whole reason the guard exists.
    """
    mod = _load_runner_module()

    code = _drive_main_over_one_file(
        mod, monkeypatch, tmp_path,
        [_KILLED_ATTEMPT, (0, "95 passed", {"passed": 95, "failed": 0})],
    )
    out = capsys.readouterr().out

    assert "RETRY PASS" in out, out
    assert "95 tests passed" in out, out
    assert "NO TESTS RAN" not in out, out
    assert code == 0, out


def test_a_straggler_that_recovers_nothing_still_trips_the_guard(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """ANTI-VACUITY: the guard is quieted by a real COLLECTION, not by the
    straggler pass having run. Same shape, but the retry is killed too, so the
    run really did collect nothing and must still say so."""
    mod = _load_runner_module()

    code = _drive_main_over_one_file(
        mod, monkeypatch, tmp_path, [_KILLED_ATTEMPT, _KILLED_ATTEMPT]
    )
    out = capsys.readouterr().out

    assert "RETRY FAIL" in out, out
    assert "NO TESTS RAN" in out, out
    assert code == 1, out


def test_a_straggler_that_recovers_only_skips_still_counts_as_collection(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The pool callback counts skips, xfails and errors as collection, and the
    straggler must count them the same way: a platform-gated file that reports
    "2 skipped" on its isolation re-run DID collect, and the guard exists for a
    run that collected nothing at all."""
    mod = _load_runner_module()

    code = _drive_main_over_one_file(
        mod, monkeypatch, tmp_path,
        [_KILLED_ATTEMPT, (0, "2 skipped", {"passed": 0, "failed": 0, "skipped": 2})],
    )
    out = capsys.readouterr().out

    assert "NO TESTS RAN" not in out, out
    assert code == 0, out


def test_an_untraced_run_spawns_exactly_what_it_always_did(monkeypatch) -> None:
    """No config var, no wrapper — the argv is byte-identical to the old one.

    The seam has to be free when nobody asked for it: a runner that could be
    traced by accident would report suite numbers measured under an
    instrumented interpreter, which is a different run from the one everyone
    else's results came from.
    """
    mod = _load_runner_module()
    monkeypatch.delenv(mod._COVERAGE_RC_ENV, raising=False)

    probe = Path("tests/agent/test_x.py")
    assert mod._pytest_argv(probe, ["-q"]) == [
        sys.executable, "-m", "pytest", str(probe), "-q",
    ]


def test_the_config_var_wraps_each_file_in_coverage_run(monkeypatch) -> None:
    """``coverage run`` goes BEFORE ``-m pytest``, and carries the rcfile.

    Position is the whole assertion. ``python -m pytest -m coverage run`` would
    hand pytest a ``-m`` marker expression and trace nothing, and the run would
    still be green — the failure mode the report cannot see from its own side,
    because it would simply find no data and blame the suite.
    """
    mod = _load_runner_module()
    monkeypatch.setenv(mod._COVERAGE_RC_ENV, "/tmp/rc")

    probe = Path("tests/agent/test_x.py")
    assert mod._pytest_argv(probe, ["-q"]) == [
        sys.executable, "-m", "coverage", "run", "--rcfile=/tmp/rc",
        "-m", "pytest", str(probe), "-q",
    ]


def test_a_blank_config_var_is_the_same_as_an_absent_one(monkeypatch) -> None:
    """An empty value must not produce ``--rcfile=``, which coverage refuses."""
    mod = _load_runner_module()
    monkeypatch.setenv(mod._COVERAGE_RC_ENV, "   ")

    assert "coverage" not in mod._pytest_argv(Path("tests/agent/test_x.py"), [])


def test_timeout_configuration_header_does_not_trigger_timeout_retry():
    mod = _load_runner_module()
    output = "timeout: 30.0s\ntimeout method: thread\nAttributeError: renamed fixture owner"
    assert not mod._is_retryable_timeout_result(1, output, {"errors": 1})
