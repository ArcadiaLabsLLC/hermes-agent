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

The same shrink-only count holds WALL-TIME ASSERTS (FH-PREPUSH-STEPS-REPORT-WORK-NOT-TIME): an
``assert elapsed < 2`` / ``assert time.monotonic() - t0 <= 1`` in a fork test outside the idle-box set
(``scripts/test_idle_box_files.txt``, owner ruling 2026-10-10: timing files run only on an idle box)
judges a default-tier test by the box's speed. A new one is refused; the existing ones become a
counted-work assert or move to the idle-box set, one by one. Killing mutation: plant
``assert elapsed < 1.0`` in a fork test -> ``test_no_fork_test_adds_a_wall_time_assert`` goes red.
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
IDLE_BOX_LIST = REPO_ROOT / "scripts" / "test_idle_box_files.txt"
#: A name or attribute that holds a measured wall time, when an assert bounds it from above.
_WALL_WORDS = ("elapsed", "duration", "wall", "took")


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
    frozen = _clock_names(tree)
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
        and (_is_clock_call(node.left, frozen) or _is_clock_call(node.right, frozen))
    )


def _clock_names(tree: ast.AST) -> frozenset[str]:
    names = set(CLOCKS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            names.update(alias.asname or alias.name for alias in node.names if alias.name in CLOCKS)
    return frozenset(names)


def _measures_wall(node: ast.AST, names: frozenset[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Sub) and _is_clock_call(child.left, names):
            return True
        word = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else ""
        if any(part in word.lower() for part in _WALL_WORDS):
            return True
    return False


def wall_asserts(tree: ast.AST) -> int:
    """How many ``assert <wall time> < bound`` (``<`` or ``<=``) statements *tree* holds."""
    names = _clock_names(tree)
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)
        and any(isinstance(op, (ast.Lt, ast.LtE)) for op in node.test.ops)
        and _measures_wall(node.test.left, names)
    )


def _idle_box_files() -> frozenset[str]:
    return frozenset(line.strip() for line in IDLE_BOX_LIST.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))


def _fork_test_files() -> list[str]:
    upstream = {line.strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")}
    tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "tests/*.py"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.split("\0")
    return sorted(p for p in tracked if p and p not in upstream and (REPO_ROOT / p).is_file())


def live_counts() -> tuple[dict[str, int], dict[str, int]]:
    """``(bare deadlines, wall-time asserts outside the idle-box set)`` per fork test file."""
    deadlines: Counter[str] = Counter()
    walls: Counter[str] = Counter()
    idle = _idle_box_files()
    for path in _fork_test_files():
        try:
            tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if found := bare_deadlines(tree):
            deadlines[path] = found
        if path not in idle and (found := wall_asserts(tree)):
            walls[path] = found
    return dict(deadlines), dict(walls)


def _baseline(key: str = "files") -> dict[str, int]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))[key]


@pytest.fixture(scope="module")
def counts() -> tuple[dict[str, int], dict[str, int]]:
    return live_counts()


@pytest.fixture(scope="module")
def live(counts) -> dict[str, int]:
    return counts[0]


def test_no_fork_test_adds_a_wall_time_assert(counts):
    baseline = _baseline("wall_asserts")
    grown = {path: (baseline.get(path, 0), n) for path, n in counts[1].items() if n > baseline.get(path, 0)}
    assert not grown, (
        "A default-tier fork test asserts wall time (baseline -> now):\n"
        + "\n".join(f"  {path}: {was} -> {now}" for path, (was, now) in sorted(grown.items()))
        + "\nAssert counted work (calls, frames, rebuilds) or list the file in scripts/test_idle_box_files.txt;"
        " the baseline is shrink-only."
    )


def test_the_wall_assert_baseline_follows_the_count_down(counts):
    baseline = _baseline("wall_asserts")
    fell = {path: (was, counts[1].get(path, 0)) for path, was in baseline.items() if counts[1].get(path, 0) < was}
    assert not fell, ("These fork tests dropped wall-time asserts; lower (or remove) their baseline entries:\n"
                      + "\n".join(f"  {path}: {was} -> {now}" for path, (was, now) in sorted(fell.items())))


@pytest.mark.parametrize("planted, expected", [
    ("assert elapsed < 1.0\n", 1),
    ("import time\nassert time.monotonic() - t0 <= 2\n", 1),
    ("assert result.duration_ms < 50\n", 1),
    ("assert elapsed >= 0.1\n", 0),
    ("assert calls < 3\n", 0),
])
def test_the_lint_counts_a_wall_time_assert(planted, expected):
    assert wall_asserts(ast.parse(planted)) == expected


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
