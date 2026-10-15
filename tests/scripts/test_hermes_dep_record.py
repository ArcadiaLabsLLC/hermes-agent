"""Fast-gate §1 stage 1: the dependency recorder, run for real in a throwaway bundle.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §1. A file's
record must name every module, data file and directory it touched and whether it
spawned a process — a missed dependency is a false green once the cache skips.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

cache = bundled.cache
_PLUGIN_DIR = Path(bundled.__file__).resolve().parent / "_bundle_plugin"

_FILE_A = '''
import os
import helper_mod

def test_reads_and_lists():
    with open(os.path.join(os.path.dirname(__file__), "data", "fixture.txt"), encoding="utf-8") as fh:
        assert fh.read() == "x"
    assert os.listdir(os.path.join(os.path.dirname(__file__), "listed")) == ["one.txt"]
    assert helper_mod.VALUE == 1
'''

_FILE_B = '''
import subprocess
import sys
import helper_mod  # already loaded by test_a: no import event fires for it here

def test_spawns():
    subprocess.run([sys.executable, "-c", "import child_mod"], check=True)
    assert helper_mod.VALUE == 1
'''


_FILE_C = '''
import subprocess
import sys

def test_spawns_isolated():
    subprocess.run([sys.executable, "-I", "-c", "pass"], check=True)  # -I ignores PYTHONPATH: no record
'''


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "listed").mkdir()
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "helper_mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "data" / "fixture.txt").write_text("x", encoding="utf-8")
    (root / "listed" / "one.txt").write_text("1", encoding="utf-8")
    (root / "test_a.py").write_text(_FILE_A, encoding="utf-8")
    (root / "test_b.py").write_text(_FILE_B, encoding="utf-8")
    (root / "test_c.py").write_text(_FILE_C, encoding="utf-8")
    (root / "child_mod.py").write_text("CHILD = 1\n", encoding="utf-8")
    return root


def _record(root: Path, deps_dir: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(_PLUGIN_DIR), str(root)])}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "hermes_dep_record",
         f"--hermes-gate-deps={deps_dir}", "test_a.py", "test_b.py", "test_c.py"],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return cache.DepsCollector(deps_dir).poll()


@pytest.mark.timeout(150)
def test_each_file_records_its_module_fixture_directory_and_spawns(tmp_path):
    root = _bundle(tmp_path)
    files = _record(root, tmp_path / "deps")

    a, b = files["test_a.py"], files["test_b.py"]
    assert "data/fixture.txt" in a.paths, "the fixture A opened is missing from its record"
    assert "test_a.py" in a.paths
    assert "listed" in a.dirs
    assert "helper_mod.py" in a.mods
    assert (a.spawn_py, a.spawn_other, a.spawned) == (0, 0, False)

    assert b.spawn_py == 1 and b.spawned
    # superset by design: B imported helper_mod after A loaded it, and still depends on it
    assert "helper_mod.py" in b.mods


def test_paths_outside_the_root_or_under_caches_are_dropped(tmp_path):
    spec = importlib.util.spec_from_file_location("hermes_dep_trail_under_test", _PLUGIN_DIR / "hermes_dep_trail.py")
    rec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rec)
    keep = rec.PathFilter(str(tmp_path))
    assert keep.rel(tmp_path / "pkg" / "mod.py") == "pkg/mod.py"
    assert keep.rel(tmp_path / "pkg" / "__pycache__" / "mod.cpython-314.pyc") is None
    assert keep.rel(tmp_path / ".git" / "HEAD") is None
    assert keep.rel(tmp_path.parent / "elsewhere.py") is None
    assert keep.rel(3) is None  # an fd, not a path
    assert rec.is_python(sys.executable) and not rec.is_python("git")


def test_the_store_keeps_one_module_set_per_digest_and_reads_back_the_newest_line(tmp_path):
    store = cache.GateStore(tmp_path / "store")
    deps = cache.FileDeps(paths={"tests/t.py"}, dirs={"pkg"}, mods={"pkg/a.py", "pkg/b.py"}, spawn_py=1)
    store.write_deps({"tests/t.py": deps, "tests/u.py": deps}, "run-1")
    store.write_deps({"tests/t.py": cache.FileDeps(paths={"tests/t.py"}, mods={"pkg/a.py"})}, "run-2")

    loaded = store.load_deps()
    assert loaded["tests/t.py"].run == "run-2" and loaded["tests/u.py"].run == "run-1"
    sets = store.load_modsets()
    assert len(sets) == 2
    assert sets[loaded["tests/u.py"].mods[0]] == ["pkg/a.py", "pkg/b.py"]


def test_the_store_is_the_primary_checkouts_unless_overridden(tmp_path):
    primary, worktree = tmp_path / "primary", tmp_path / "landing"
    assert cache.gate_store_dir(worktree, primary) == primary / ".pytest_cache" / "hermes_gate"
    assert cache.gate_store_dir(primary, None) == primary / ".pytest_cache" / "hermes_gate"
    assert cache.gate_store_dir(worktree, primary, str(tmp_path / "x")) == tmp_path / "x"


@pytest.mark.timeout(150)
def test_a_python_child_records_itself_and_covers_its_parent_but_an_isolated_child_does_not(tmp_path):
    root = _bundle(tmp_path)
    files = _record(root, tmp_path / "deps")

    b, c = files["test_b.py"], files["test_c.py"]
    assert b.child_records == 1 and "child_mod.py" in b.mods, "the child's import is the parent file's dependency"
    assert b.child_covered and not cache.uncovered_spawn(b.spawn_py, b.spawn_other, b.child_records)
    assert c.spawn_py == 1 and c.child_records == 0
    assert not c.child_covered, "a child run with -I leaves no record: its parent keeps the ALL sentinel"


def test_a_spawn_event_names_its_program_for_every_event_shape():
    spec = importlib.util.spec_from_file_location("hermes_dep_trail_programs", _PLUGIN_DIR / "hermes_dep_trail.py")
    trail = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trail)
    assert trail.spawned_program("subprocess.Popen", (None, ["git", "status"], None, None)) == "git"
    assert trail.spawned_program("subprocess.Popen", (sys.executable, ["x"], None, None)) == sys.executable
    assert trail.spawned_program("subprocess.Popen", (None, '"python" -c pass', None, None)) == "python"
    assert trail.spawned_program("os.exec", ("/bin/sh", ["sh"], {})) == "/bin/sh"
    assert trail.spawned_program("os.spawn", (0, "node", ["node"], {})) == "node"
    assert trail.spawned_program("os.system", ("echo hi",)) == ""


_FX_CONFTEST = '''
import pytest

@pytest.fixture(autouse=True)
def auto():
    return 0

@pytest.fixture
def used():
    return 1

@pytest.fixture
def dyn():
    return 2

@pytest.fixture
def unused():
    return 3
'''

_FILE_FX = '''
import os

def test_uses(used, request):
    assert request.getfixturevalue("dyn") == 2

def test_reads_conftest_as_data():
    with open(os.path.join(os.path.dirname(__file__), "conftest.py"), encoding="utf-8") as fh:
        assert "unused" in fh.read()
'''


@pytest.mark.timeout(150)
def test_a_record_names_the_fixtures_set_up_and_the_paths_the_file_opened_itself(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "conftest.py").write_text(_FX_CONFTEST, encoding="utf-8")
    (root / "test_fx.py").write_text(_FILE_FX, encoding="utf-8")
    deps_dir = tmp_path / "deps"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(_PLUGIN_DIR), str(root)])}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "hermes_dep_record",
         f"--hermes-gate-deps={deps_dir}", "test_fx.py"],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    deps = cache.DepsCollector(deps_dir).poll()["test_fx.py"]
    assert deps.fx is not None
    assert {"auto", "used", "dyn", "request"} <= set(deps.fx), "autouse, requested and getfixturevalue all count"
    assert "unused" not in deps.fx
    assert "conftest.py" in deps.own, "a data read of the conftest must keep its whole-blob key"
