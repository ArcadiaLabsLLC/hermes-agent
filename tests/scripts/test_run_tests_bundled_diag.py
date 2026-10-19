"""Per-file diagnosis of a bundled run (owner, q-runner step 6, 2026-10-17).

The bundle plugin records, per file, its seconds by pytest phase, its slowest
phases, the processes its tests started by program kind with the main thread's
wait on them, the seconds inside a named callable (plugin discovery in the real
run) and its sleeps; ``scripts/run_tests_bundled_diag.py`` folds them into one
``diagnosis.jsonl`` line per file, the run's totals and the ``=== Diagnosis ===``
block. The plugin runs for real here, in a throwaway project.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

diag = bundled.diag
_PLUGIN_DIR = Path(bundled.__file__).resolve().parent / "_bundle_plugin"

_TEST_FILE = '''
import subprocess
import sys
import time

import pytest

import probe_target


@pytest.fixture
def slow_setup():
    time.sleep(0.15)
    yield


def test_slow_call(slow_setup):
    time.sleep(0.4)


def test_spawns():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    if GIT:
        subprocess.run([GIT, "--version"], capture_output=True, check=True)


def test_wrapped():
    probe_target.Manager().discover(0.2)
'''

_TARGET = '''
import time


class Manager:
    def discover(self, seconds):
        time.sleep(seconds)
'''


@pytest.mark.timeout(150)
def test_the_plugin_records_phases_spawns_the_wrapped_callable_and_sleeps(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    git = shutil.which("git")
    (root / "test_d.py").write_text(f"GIT = {git!r}\n" + _TEST_FILE, encoding="utf-8")
    (root / "probe_target.py").write_text(_TARGET, encoding="utf-8")
    events = tmp_path / "events.jsonl"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(_PLUGIN_DIR), str(root)])}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "hermes_bundle_report",
         f"--hermes-bundle-events={events}", "--hermes-diag-wrap=probe_target:Manager.discover", "test_d.py"],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = events.read_text(encoding="utf-8").splitlines()
    row = diag.fold(lines)["test_d.py"]
    assert row.collect > 0
    assert row.phases["setup"] >= 0.15, "a fixture's seconds are the setup phase's"
    assert row.phases["call"] >= 0.6
    assert row.slowest[0][1:] == ("test_d.py::test_slow_call", "call")
    assert row.spawn["python"][0] == 1 and row.spawn["python"][1] > 0, "the wait on the python child"
    if git:
        assert row.spawn["git"][0] == 1
    assert row.plugins >= 0.2, "the seconds inside the --hermes-diag-wrap callable"
    assert row.sleep >= 0.75, "the main thread's sleeps"
    tally = bundled.tally_events(lines).files["test_d.py"]
    assert tally.failed_nodeids == [], "a slow phase's node id is not a failure"


def _diagnosis() -> "diag.Diagnosis":
    d = diag.Diagnosis()
    d.add([
        json.dumps({"k": "collect", "f": "tests/a.py", "d": 1.0}),
        json.dumps({"k": "test", "f": "tests/a.py", "c": "passed", "d": 4.0, "w": "call", "n": "tests/a.py::t"}),
        json.dumps({"k": "diag", "f": "tests/a.py", "spawn": {"git": [3, 2.5]}, "wrapped": 0.0, "sleep": 0.0}),
        json.dumps({"k": "test", "f": "tests/b.py", "c": "", "d": 9.0, "w": "setup", "n": "tests/b.py::u"}),
        json.dumps({"k": "diag", "f": "tests/b.py", "spawn": {}, "wrapped": 6.0, "sleep": 1.0}),
        '{"k": "test", "f": "tests/b.py", "d": 1',  # a torn last line
    ])
    return d


def test_the_block_ranks_files_per_column_and_the_store_gets_one_line_per_file(tmp_path):
    d = _diagnosis()

    block = "\n".join(diag.render(d))
    assert "=== Diagnosis" in block
    assert "  setup:\n         9.0s  tests/b.py" in block
    assert "  spawn_git_s:\n         2.5s  tests/a.py  (3 spawned)" in block
    assert "  plugins:\n         6.0s  tests/b.py" in block

    record = diag.run_record(d)["diagnosis"]
    assert record["files"] == 2 and record["seconds"]["call"] == 4.0 and record["spawns"]["git"] == 3

    path = diag.append(tmp_path, "run-1", d)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["f"] for r in rows] == ["tests/a.py", "tests/b.py"]
    assert rows[0]["slowest"] == [["tests/a.py::t", "call", 4.0]] and rows[1]["plugins"] == 6.0
    assert path.name == "diagnosis.jsonl"


def test_an_empty_diagnosis_prints_and_records_nothing(tmp_path):
    assert diag.render(diag.Diagnosis()) == [] and diag.run_record(None) == {}
    assert diag.append(tmp_path, "r", diag.Diagnosis()) is None


def test_body_patch_and_teardown_error_columns_fold_from_the_events(tmp_path):
    """p10 S-A1: ``bp`` on a call line and a teardown ``error`` fold into three per-file test counts.
    Mutation: ``_on_test`` ignores ``bp`` -> ``body_patches == 0``."""
    d = diag.Diagnosis()
    d.add([
        json.dumps({"k": "test", "f": "tests/c.py", "c": "passed", "d": 0.1, "w": "call", "bp": [2, 0, 0]}),
        json.dumps({"k": "test", "f": "tests/c.py", "c": "passed", "d": 0.1, "w": "call", "bp": [0, 1, 3]}),
        json.dumps({"k": "test", "f": "tests/c.py", "c": "passed", "d": 0.1, "w": "call"}),
        json.dumps({"k": "test", "f": "tests/c.py", "c": "error", "d": 0.1, "w": "teardown", "n": "tests/c.py::x"}),
        json.dumps({"k": "test", "f": "tests/c.py", "c": "error", "d": 0.1, "w": "setup", "n": "tests/c.py::y"}),
    ])
    row = d.rows["tests/c.py"]
    assert (row.body_patches, row.late_fixture_patches, row.teardown_errors) == (2, 1, 1)
    assert row.teardown_error_ids == ["tests/c.py::x"]
    assert diag.run_record(d)["diagnosis"]["counts"] == {"body_patches": 2, "late_fixture_patches": 1,
                                                         "teardown_errors": 1}
    line = json.loads(diag.append(tmp_path, "r", d).read_text(encoding="utf-8").splitlines()[0])
    assert (line["body_patches"], line["late_fixture_patches"], line["teardown_errors"]) == (2, 1, 1)
    assert "  body_patches (tests):\n           2   tests/c.py" in "\n".join(diag.render(d))
