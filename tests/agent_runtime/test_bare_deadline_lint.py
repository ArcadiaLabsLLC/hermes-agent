"""FH-BARE-DEADLINE-LINT: a new bare clock deadline in hermes' OWN tests is refused when it is written.

A ``deadline = time.monotonic() + 5`` in a test is a budget measured on one box, and the fork's
timing flakes were exactly that, red under load (the RT-FLAKE-*-UNDER-LOAD rows). Waiting tests use
``tests._downstream.load_wait.wait_for`` instead, whose budget follows the box's load.

The lint counts every ``<clock>() + <anything>`` — ``time.monotonic``, ``time.time``,
``time.perf_counter`` and their ``*_ns`` forms, however imported — in each FORK-owned test file
(tracked under ``tests/``, not in the upstream manifest ``tests/fixtures/upstream_manifest.txt``).
Inherited (upstream) test files are out of scope: they are never edited without the owner's words.
``tests/fixtures/bare_deadline_baseline.json`` holds each file's count on 2026-11-15; a count may only
fall, and the baseline must follow it down (shrink-only; never raised, owner 2026-11-13).
Killing mutation (recorded in the commit): plant ``deadline = time.monotonic() + 5`` in a fork test
-> ``test_no_fork_test_adds_a_bare_deadline`` goes red naming the file.
"""

from __future__ import annotations

import ast
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "tests" / "fixtures" / "bare_deadline_baseline.json"
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "upstream_manifest.txt"
CLOCKS = frozenset({"monotonic", "time", "perf_counter", "monotonic_ns", "time_ns", "perf_counter_ns"})


def _is_clock_call(node: ast.AST, names: frozenset[str]) -> bool:
    if not isinstance(node, ast.Call) or node.args or node.keywords:
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in CLOCKS
    return isinstance(func, ast.Name) and func.id in names


def bare_deadlines(tree: ast.AST) -> int:
    """How many ``<clock>() + x`` / ``x + <clock>()`` sums *tree* holds (``from time import monotonic as
    clock`` included)."""
    names = set(CLOCKS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            names.update(alias.asname or alias.name for alias in node.names if alias.name in CLOCKS)
    frozen = frozenset(names)
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
        and (_is_clock_call(node.left, frozen) or _is_clock_call(node.right, frozen))
    )


def _fork_test_files() -> list[str]:
    upstream = {line.strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")}
    tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "tests/*.py"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.split("\0")
    return sorted(p for p in tracked if p and p not in upstream and (REPO_ROOT / p).is_file())


def live_counts() -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in _fork_test_files():
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        if "(" not in source or "+" not in source:
            continue
        try:
            found = bare_deadlines(ast.parse(source))
        except SyntaxError:
            continue
        if found:
            counts[path] = found
    return dict(counts)


def _baseline() -> dict[str, int]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["files"]


@pytest.fixture(scope="module")
def live() -> dict[str, int]:
    return live_counts()


def test_no_fork_test_adds_a_bare_deadline(live):
    baseline = _baseline()
    grown = {path: (baseline.get(path, 0), count) for path, count in live.items() if count > baseline.get(path, 0)}
    assert not grown, (
        "A fork test adds a bare clock deadline (baseline -> now):\n"
        + "\n".join(f"  {path}: {was} -> {now}" for path, (was, now) in sorted(grown.items()))
        + "\nWait with tests._downstream.load_wait.wait_for(predicate_or_event, budget) instead; the baseline"
        " is shrink-only and is never raised."
    )


def test_the_baseline_follows_the_count_down(live):
    baseline = _baseline()
    fell = {path: (was, live.get(path, 0)) for path, was in baseline.items() if live.get(path, 0) < was}
    assert not fell, (
        "These fork tests dropped bare deadlines; lower (or remove) their baseline entries:\n"
        + "\n".join(f"  {path}: {was} -> {now}" for path, (was, now) in sorted(fell.items()))
    )


@pytest.mark.parametrize("planted, expected", [
    ("import time\ndeadline = time.monotonic() + 5\n", 1),
    ("from time import monotonic as clock\nend = clock() + budget\n", 1),
    ("import time\nstop = 2.0 + time.time()\n", 1),
    ("import time\nelapsed = time.monotonic() - start\n", 0),
    ("from tests._downstream.load_wait import wait_for\nwait_for(lambda: done, 5)\n", 0),
])
def test_the_lint_counts_every_spelling_of_a_bare_deadline(planted, expected):
    assert bare_deadlines(ast.parse(planted)) == expected
