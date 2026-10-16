"""Fork-owned tests moved out of ``tests/scripts/test_run_tests_parallel.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_run_tests_parallel import (  # noqa: F401 — upstream names the moved tests use
    _make_probe_dir,
    _probe_root,
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


@pytest.mark.skipif(sys.platform != "win32", reason="the drive-letter re-glue is the win32 branch of upstream's split")
def test_file_list_split_keeps_windows_drive_letters() -> None:
    """``--files`` is colon-joined; a bare split() shreds ``C:\\repo\\t.py``.

    Regression: the runner opened a file literally named ``C`` under the repo root. Upstream's
    ``_split_pathspec`` re-glues drive letters itself since v0.21.7, so the fork's
    ``_split_path_list`` carry retired; this pins the behaviour where it lives (Windows).
    """
    mod = _load_runner_module()

    assert mod._split_pathspec(r"C:\repo\tests\test_a.py") == [r"C:\repo\tests\test_a.py"]
    assert mod._split_pathspec(r"C:\repo\test_a.py:D:/repo/test_b.py") == [r"C:\repo\test_a.py", "D:/repo/test_b.py"]
    assert mod._split_pathspec("tests/a.py;tests/b.py") == ["tests/a.py", "tests/b.py"]


def test_a_file_list_longer_than_the_os_will_stat_still_splits() -> None:
    """The list CI passes (8 slices over ~3,040 files, ~30 KB) splits on every host.

    The retired fork carry probed ``Path(raw).exists()`` first and Linux's ``ENAMETOOLONG``
    raised through it (every CI slice red 2026-08-04 .. 09-05). Upstream's split never asks
    the OS; this keeps it that way, POSIX lists included.
    """
    mod = _load_runner_module()

    joined = ":".join(f"tests/dir{index}/test_module_{index}.py" for index in range(600))
    assert len(joined) > 4096, "the case needs a list past PATH_MAX"
    assert mod._split_pathspec(joined) == joined.split(":")
    assert mod._split_pathspec("tests/a.py:tests/b.py") == ["tests/a.py", "tests/b.py"]
    assert not hasattr(mod, "_split_path_list"), "the retired fork carry is back beside upstream's split"


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
    monkeypatch.delenv("HERMES_TEST_COVERAGE_RC", raising=False)

    probe = Path("tests/agent/test_x.py")
    assert mod._fork_pytest_argv(probe, ["-q"]) == [
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
    monkeypatch.setenv("HERMES_TEST_COVERAGE_RC", "/tmp/rc")

    probe = Path("tests/agent/test_x.py")
    assert mod._fork_pytest_argv(probe, ["-q"]) == [
        sys.executable, "-m", "coverage", "run", "--rcfile=/tmp/rc",
        "-m", "pytest", str(probe), "-q",
    ]


def test_a_blank_config_var_is_the_same_as_an_absent_one(monkeypatch) -> None:
    """An empty value must not produce ``--rcfile=``, which coverage refuses."""
    mod = _load_runner_module()
    monkeypatch.setenv("HERMES_TEST_COVERAGE_RC", "   ")

    assert "coverage" not in mod._fork_pytest_argv(Path("tests/agent/test_x.py"), [])


def test_timeout_configuration_header_does_not_trigger_timeout_retry():
    mod = _load_runner_module()
    output = "timeout: 30.0s\ntimeout method: thread\nAttributeError: renamed fixture owner"
    assert not mod._is_retryable_timeout_result(1, output, {"errors": 1})


@pytest.mark.platforms("windows")
@pytest.mark.timeout(75)
def test_windows_worker_does_not_inherit_runner_console(tmp_path):
    """A worker's console must exclude the runner, including venv launchers."""
    repo_root = _probe_root(tmp_path)
    probe = repo_root / "test_console.py"
    probe.write_text(
        "import ctypes, os\n"
        "def test_no_console():\n"
        "    pids = (ctypes.c_ulong * 32)()\n"
        "    count = ctypes.windll.kernel32.GetConsoleProcessList(pids, 32)\n"
        "    assert count <= 32\n"
        "    assert int(os.environ['PROBE_RUNNER_PID']) not in pids[:count]\n",
        encoding="utf-8",
    )
    (repo_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    result = subprocess.run(
        [sys.executable, "-c",
         "import os, runpy, sys; os.environ['PROBE_RUNNER_PID'] = str(os.getpid()); "
         "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')",
         str(repo_root / "scripts" / "run_tests_parallel.py"),
         "--paths", str(probe), "-j", "1", "--file-timeout", "30", "--file-retries", "0"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8",
        timeout=60, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_multiple_absolute_paths_split_on_pathsep(tmp_path: Path) -> None:
    """``--paths`` accepts ``os.pathsep``-joined absolute paths.

    On Windows the absolute paths contain drive-letter colons, so a naive
    ``split(":")`` shreds them into phantom roots and only one (or neither)
    of the two probe dirs would be discovered.
    """
    dir_a = _make_probe_dir(tmp_path)
    dir_b = tmp_path / "probe_b"
    dir_b.mkdir()
    (dir_b / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (dir_b / "test_flagprobe_b.py").write_text(
        "def test_gamma():\n    assert True\n"
    )
    repo_root = Path(__file__).resolve().parent.parent.parent
    runner = repo_root / "scripts" / "run_tests_parallel.py"
    proc = subprocess.run(
        [sys.executable, str(runner),
         "--paths", os.pathsep.join([str(dir_a), str(dir_b)]),
         "-j", "1", "--file-timeout", "30", "-q"],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=60,
    )
    assert proc.returncode == 0, proc.stdout
    assert "Discovered 2 test files" in proc.stdout, proc.stdout
