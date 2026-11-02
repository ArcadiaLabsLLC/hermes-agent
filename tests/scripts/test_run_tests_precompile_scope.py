"""FH-PREPUSH-GATES-COLD-BYTECODE-DEADLINE: ``scripts/run_tests.sh`` precompiles only what a run reads.

In a fresh landing worktree the whole-tree ``compileall`` outran prepush's 120 s gates deadline
before a gate ran. Two cuts: a small run naming only test files skips the pass (each process compiles
what it imports, cached on first import), and the pass never compiles the files pytest rewrites.

KILLING MUTATION: drop ``[ "$count" -le "$limit" ]`` from ``_is_small_file_run`` -> a 65-file run
counts as small and skips the pass, red.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / "scripts" / "run_tests.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _function() -> str:
    match = re.search(r"^_is_small_file_run\(\) \{\n.*?^\}\n", SCRIPT, re.MULTILINE | re.DOTALL)
    assert match, "run_tests.sh lost _is_small_file_run"
    return match.group(0)


def _small(*args: str, env: dict | None = None) -> bool:
    proc = subprocess.run(["bash", "-c", _function() + '_is_small_file_run "$@"', "_", *args],
                          cwd=REPO, env={"PATH": "/usr/bin:/bin", **(env or {})}, check=False)
    return proc.returncode == 0


def test_a_few_named_test_files_are_a_small_run():
    gates = ["tests/tooling/test_work_queue_row_grammar.py", "tests/test_line_endings.py"]
    assert _small(*gates)
    assert _small("-j", "8", *gates, "-q", "-k", "grammar")


def test_a_directory_a_file_list_or_many_files_is_a_whole_run():
    files = sorted(str(p.relative_to(REPO)) for p in (REPO / "tests" / "agent_runtime").glob("test_*.py"))[:65]
    assert len(files) == 65
    assert not _small(*files)
    assert _small(*files[:64])
    assert not _small("tests/agent_runtime")
    assert not _small("--files-from", "list.txt")
    assert not _small()
    assert not _small("tests/no_such_file.py")
    assert _small(*files, env={"HERMES_TEST_PRECOMPILE_MAX_FILES": "65"})


def test_the_whole_tree_pass_skips_what_pytest_rewrites():
    pattern = re.search(r"grep -Ev '([^']+)'", SCRIPT).group(1)
    rewritten = re.compile(pattern.replace(r"\\.", r"\."))
    for path in ("tests/test_x.py", "tests/a/conftest.py", "tests/a/thing_test.py", "conftest.py"):
        assert rewritten.search(path), path
    for path in ("agent_runtime/turn_attendance.py", "tests/agent_runtime/_serve_rpc_manifest.py",
                 "tests/fixtures/latest_test_data.py", "agent/testing.py"):
        assert not rewritten.search(path), path
