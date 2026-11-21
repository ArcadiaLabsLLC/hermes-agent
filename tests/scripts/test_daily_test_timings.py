"""`scripts/daily_test_timings.py` — the daily full run's per-test timings (FH-DAILY-RUN-TIMES-EVERY-TEST).

The plugin half runs in a real ``python -m pytest`` child over two throwaway test files in one process
(as a bundle of the bundled runner does; a per-file run is the one-file case), one of whose tests kills
its own process mid-test the way a file timeout or pytest-timeout's thread dump does. The report half
is read off ``fold`` and ``summary_lines`` directly.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("daily_test_timings", REPO / "scripts" / "daily_test_timings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FIRST = '''
import time, pytest

def test_fast():
    pass

def test_fails():
    assert False

def test_skipped():
    pytest.skip("not here")

@pytest.mark.xfail(strict=True)
def test_expected_failure():
    assert False

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")

def test_teardown_errors(broken_teardown):
    pass

def test_sleeps():
    time.sleep(0.2)
'''

_SECOND = '''
import os

def test_before_the_kill():
    pass

def test_killed_mid_test():
    os._exit(9)  # the process dies inside the test: no report, no teardown, no end line

def test_never_reached():
    pass
'''


@pytest.mark.timeout(120)
def test_a_test_that_never_finishes_is_named_unfinished(tmp_path: Path):
    files = tmp_path / "t"
    files.mkdir()
    (files / "test_first.py").write_text(_FIRST, encoding="utf-8")
    (files / "test_second.py").write_text(_SECOND, encoding="utf-8")
    where = tmp_path / "timings.d"
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "scripts.daily_test_timings",
         f"--daily-test-timings={where}", "--rootdir", str(files), "-c", os.devnull,
         str(files / "test_first.py"), str(files / "test_second.py")],
        cwd=files, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=100, check=False)
    assert proc.returncode == 9, proc.stdout + proc.stderr  # the kill, not a pytest exit code
    module = _module()
    folded = module.fold(where, now=10**10)
    outcomes = {r["nodeid"].split("::")[-1]: r["outcome"] for r in folded["results"]}
    assert outcomes == {"test_fast": "passed", "test_fails": "failed", "test_skipped": "skipped",
                        "test_expected_failure": "xfailed", "test_teardown_errors": "error",
                        "test_sleeps": "passed", "test_before_the_kill": "passed"}
    sleeps = next(r for r in folded["results"] if r["nodeid"].endswith("test_sleeps"))
    assert sleeps["seconds"] >= 0.2 and folded["results"][0] is sleeps  # slowest first
    [hung] = folded["unfinished"]
    assert hung["nodeid"].endswith("test_second.py::test_killed_mid_test")
    assert hung["finished_on_retry"] is False and len(list(where.glob("*.jsonl"))) == 1
    lines = module.summary_lines(folded, "out/suite.timings.json")
    assert lines[0] == "    timings: 7 test(s) timed, 0 over 10s, 1 never finished — out/suite.timings.json"
    assert lines[1].startswith(f"    NEVER FINISHED (hung or killed): {hung['nodeid']} — started ")


def test_without_the_option_the_plugin_writes_nothing(tmp_path: Path):
    (tmp_path / "test_one.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "scripts.daily_test_timings",
         "--rootdir", str(tmp_path), "-c", os.devnull, str(tmp_path / "test_one.py")],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(REPO)}, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=60, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not list(tmp_path.rglob("*.jsonl"))


def _lines(*records: dict) -> str:
    return "".join(json.dumps(r) + "\n" for r in records)


# KILLING MUTATION: compare with ``>`` instead of ``>=`` in the ``slow`` list -> a test of exactly the
# threshold is no longer named and this reds; drop the attempt dedupe (``ranked = folded["results"]``)
# -> the retried test is named twice and this reds.
def test_the_summary_names_each_test_once_at_its_slowest_attempt_and_the_threshold_is_inclusive(tmp_path: Path):
    module = _module()
    at = module.SLOW_TEST_SECONDS
    (tmp_path / "1.jsonl").write_text(_lines(
        {"e": "start", "id": "t.py::test_retried", "t": 1.0},
        {"e": "end", "id": "t.py::test_retried", "s": at + 5, "o": "failed", "t": 2.0},
        {"e": "start", "id": "t.py::test_at", "t": 1.0},
        {"e": "end", "id": "t.py::test_at", "s": at, "o": "passed", "t": 2.0},
        {"e": "start", "id": "t.py::test_under", "t": 1.0},
        {"e": "end", "id": "t.py::test_under", "s": at - 0.01, "o": "passed", "t": 2.0},
    ), encoding="utf-8")
    (tmp_path / "2.jsonl").write_text(_lines(
        {"e": "start", "id": "t.py::test_retried", "t": 3.0},
        {"e": "end", "id": "t.py::test_retried", "s": 1.0, "o": "passed", "t": 4.0},
        {"e": "start", "id": "t.py::test_gone", "t": 5.0},
    ) + '{"e":"end","id":"t.py::te', encoding="utf-8")  # a line cut short by a kill mid-write is skipped
    folded = module.fold(tmp_path, now=65.0)
    assert folded["tests"] == 4 and folded["slow"] == 2
    lines = module.summary_lines(folded, "x.json")
    assert lines[1] == "    NEVER FINISHED (hung or killed): t.py::test_gone — started 00:00:05Z, ran ≥60s, pid 2"
    assert [line for line in lines if " over " in line and line.startswith("    over")] == [
        f"    over {at:g}s: {at + 5:.2f}s failed t.py::test_retried (2 attempts)",
        f"    over {at:g}s: {at:.2f}s passed t.py::test_at"]
    assert sum("test_retried" in line for line in lines) == 2  # once over the threshold, once in the slowest


def test_a_hang_that_passed_on_a_retry_is_still_named_and_says_so(tmp_path: Path):
    module = _module()
    (tmp_path / "1.jsonl").write_text(_lines({"e": "start", "id": "t.py::test_flaky_hang", "t": 0.0}), encoding="utf-8")
    (tmp_path / "2.jsonl").write_text(_lines(
        {"e": "start", "id": "t.py::test_flaky_hang", "t": 400.0},
        {"e": "end", "id": "t.py::test_flaky_hang", "s": 0.5, "o": "passed", "t": 400.5}), encoding="utf-8")
    lines = module.summary_lines(module.fold(tmp_path, now=400.5), "x.json")
    assert lines[1].endswith("pid 1; it passed or failed on a later attempt")


def test_the_report_cli_writes_the_json_and_exits_0_even_with_nothing_recorded(tmp_path: Path):
    out = tmp_path / "suite.timings.json"
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "daily_test_timings.py"), str(tmp_path / "none"), str(out)],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["tests"] == 0
    assert proc.stdout.startswith("    timings: none recorded")
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "daily_test_timings.py")], capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=60, check=False).returncode == 2


# FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET: the fold also keeps the clone's shared per-file
# record, which prepush's touched step reads when a tree has none of its own. KILLING MUTATIONS: start the
# merge from nothing (``merged = {}``) -> the file this fold did not run is dropped and this reds; drop the
# never-finished loop in ``file_timings`` -> the killed file is recorded as 2 s and this reds.
def test_the_fold_keeps_each_files_seconds_slowest_test_and_count_in_the_shared_record(tmp_path: Path):
    where = tmp_path / "timings.d"
    where.mkdir()
    (where / "1.jsonl").write_text(_lines(
        {"e": "start", "id": "tests/a/test_x.py::test_one", "t": 1.0},
        {"e": "end", "id": "tests/a/test_x.py::test_one", "s": 30.0, "o": "failed", "t": 31.0},
        {"e": "start", "id": "tests/a/test_x.py::test_two[p]", "t": 31.0},
        {"e": "end", "id": "tests/a/test_x.py::test_two[p]", "s": 12.5, "o": "passed", "t": 43.5},
        {"e": "start", "id": "tests/b/test_killed.py::test_quick", "t": 50.0},
        {"e": "end", "id": "tests/b/test_killed.py::test_quick", "s": 2.0, "o": "passed", "t": 52.0},
        {"e": "start", "id": "tests/b/test_killed.py::test_hangs", "t": 52.0},
    ), encoding="utf-8")
    (where / "2.jsonl").write_text(_lines(  # the retry: test_one counts at its slowest attempt
        {"e": "start", "id": "tests/a/test_x.py::test_one", "t": 60.0},
        {"e": "end", "id": "tests/a/test_x.py::test_one", "s": 3.0, "o": "passed", "t": 63.0},
    ), encoding="utf-8")
    record = tmp_path / "hermes-test-timings.json"
    record.write_text('{"schema": 1, "updated": "x", "files": {\n  "tests/c/test_old.py": [40.0, 10.0, 4]\n}}\n',
                      encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "daily_test_timings.py"), str(where),
                           str(tmp_path / "out.json"), "--shared-record", str(record)],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert f"    shared timings: 2 file(s) into {record}" in proc.stdout.splitlines()
    files = json.loads(record.read_text(encoding="utf-8"))["files"]
    assert files["tests/a/test_x.py"] == [42.5, 30.0, 2]
    assert files["tests/c/test_old.py"] == [40.0, 10.0, 4]  # not run today: kept
    killed = files["tests/b/test_killed.py"]
    assert killed[2] == 2 and killed[0] > 2.0  # the hung test counts at what it ran before the kill
    # One file per line, the shape prepush's one-line grep reads.
    assert '  "tests/a/test_x.py": [42.5, 30.0, 2],' in record.read_text(encoding="utf-8").splitlines()
