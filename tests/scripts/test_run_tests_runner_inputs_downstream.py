"""Every fork module the test runner imports is a key input of the green-result cache.

``scripts/run_tests_parallel.py`` is upstream's; the fork's seams live in modules it
imports (``scripts/_fork_runner.py``, lane pb-a). A cached green is keyed on
``run_tests_bundled_cache.RUNNER_GLOBS``; a runner input missing from it would let a
change to how every file is spawned replay yesterday's greens.

Read through the AST of the runner, not a list kept beside it: each resolved
``scripts.*`` import must match a glob.
"""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

from scripts import run_tests_bundled_cache as cache

REPO = Path(__file__).resolve().parents[2]


def _runner_script_imports() -> list[str]:
    tree = ast.parse((REPO / "scripts" / "run_tests_parallel.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts."):
            rel = node.module.replace(".", "/") + ".py"
            assert (REPO / rel).is_file(), rel
            found.append(rel)
    return sorted(set(found))


def test_the_runner_imports_its_fork_seam_module():
    assert "scripts/_fork_runner.py" in _runner_script_imports()


def test_every_scripts_module_the_runner_imports_keys_the_cache():
    missing = [
        rel for rel in _runner_script_imports()
        if not any(fnmatch.fnmatchcase(rel, g) for g in cache.RUNNER_GLOBS)
    ]
    assert missing == [], f"runner inputs absent from RUNNER_GLOBS: {missing}"
