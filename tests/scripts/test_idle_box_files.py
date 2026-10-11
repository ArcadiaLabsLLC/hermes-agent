"""The idle-box list and its skip (design sweep D3.01, owner ruling 2026-10-10).

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md`` § D3.01.
The listed files run only on an idle box: every test in them carries the
``idle_box`` marker and skips unless ``HERMES_TEST_IDLE_BOX=1``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests._downstream import idle_box

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_listed_file_exists_and_is_a_fork_file():
    listed = idle_box.load_idle_box_files()
    assert listed, "scripts/test_idle_box_files.txt names no file"
    manifest = (_REPO_ROOT / "tests" / "fixtures" / "upstream_manifest.txt").read_text(encoding="utf-8").splitlines()
    assert not listed & {line.strip() for line in manifest}, "an upstream file is on the idle-box list"
    assert [rel for rel in sorted(listed) if not (_REPO_ROOT / rel).is_file()] == []


def test_the_three_timing_files_of_the_ruling_are_listed():
    assert {
        "tests/agent_runtime/test_send_window_receipt.py",
        "tests/agent_runtime/test_stream_gap_receipt.py",
        "tests/agent_runtime/test_turn_cost_guard_downstream.py",
    } <= idle_box.load_idle_box_files()


def _run_marked_test(tmp_path: Path, idle: bool) -> subprocess.CompletedProcess:
    test = tmp_path / "test_throwaway_idle_box.py"
    test.write_text(
        "import pytest\n\n@pytest.mark.idle_box\ndef test_timing():\n    assert True\n", encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if k != idle_box.IDLE_BOX_ENV}
    if idle:
        env[idle_box.IDLE_BOX_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(_REPO_ROOT), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests._downstream.idle_box", "-p", "no:cacheprovider",
         "-o", "addopts=", "--rootdir", str(tmp_path), "-rs", "-q", str(test)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def test_a_marked_test_skips_without_the_idle_box_env(tmp_path):
    proc = _run_marked_test(tmp_path, idle=False)
    assert "1 skipped" in proc.stdout, proc.stdout + proc.stderr
    assert "run scripts/run_tests_idle.sh" in proc.stdout


def test_a_marked_test_runs_with_the_idle_box_env(tmp_path):
    proc = _run_marked_test(tmp_path, idle=True)
    assert proc.returncode == 0 and "1 passed" in proc.stdout, proc.stdout + proc.stderr


def test_a_listed_files_tests_carry_the_marker():
    class _Item:
        def __init__(self, nodeid):
            self.nodeid, self.marks = nodeid, []

        def add_marker(self, mark):
            self.marks.append(mark)

    listed = _Item("tests/agent_runtime/test_send_window_receipt.py::test_x")
    other = _Item("tests/agent_runtime/test_other.py::test_y")
    idle_box.pytest_collection_modifyitems_idle_box([listed, other])
    assert (listed.marks, other.marks) == ([idle_box.IDLE_BOX_MARK], [])


def _fake_tree(root: Path) -> list[Path]:
    paths = []
    for rel in ("tests/pkg/test_timing.py", "tests/pkg/test_plain.py", "tests/pkg/test_upstream.py"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok():\n    pass\n", encoding="utf-8")
        paths.append(path)
    return paths


def test_the_runner_leaves_a_listed_file_to_the_idle_box_in_both_scopes(tmp_path):
    from scripts import run_tests_bundled as bundled

    files = _fake_tree(tmp_path)
    listed = {"tests/pkg/test_timing.py"}
    inherited = {"tests/pkg/test_upstream.py"}
    fork = bundled.select_scope(files, tmp_path, inherited, set(), idle_box=listed)
    full = bundled.select_scope(files, tmp_path, set(), set(), full=True, idle_box=listed)

    for sel in (fork, full):
        assert [p.name for p in sel.idle_box] == ["test_timing.py"]
        assert "test_timing.py" not in [p.name for p in sel.selected]
    assert [p.name for p in fork.fork_only] == ["test_plain.py"]


def test_a_named_listed_file_runs(tmp_path):
    from scripts import run_tests_bundled as bundled

    files = _fake_tree(tmp_path)
    sel = bundled.select_scope(files, tmp_path, set(), set(), named=[files[0]], idle_box={"tests/pkg/test_timing.py"})
    assert ([p.name for p in sel.named], sel.idle_box) == (["test_timing.py"], [])


def test_the_runner_and_the_plugin_read_one_list():
    from scripts import run_tests_bundled_scope as scope

    assert idle_box.load_idle_box_files() == scope.load_path_list(_REPO_ROOT / scope.IDLE_BOX_LIST)
    assert scope.load_path_list(_REPO_ROOT / "no-such-list.txt") == frozenset()
