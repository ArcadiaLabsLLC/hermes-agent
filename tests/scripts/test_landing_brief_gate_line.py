"""The landing step a hermes landing brief is copied from names the bundled gate.

Row FH-LANDING-BRIEF-WHOLE-TREE-GATE (2026-10-29): the w1029a landing brief named a
pathless ``scripts/run_tests.sh -j 16`` as "the full fork suite" — a whole-tree run
ADR 0016 forbids. ``Harness_Brain/50 — Agent Handoffs/Dispatching a lane.md`` § 5
step 4 is the page a landing brief names, so its gate line is pinned here: the
bundled landing gate is named, and no ``scripts/run_tests.sh`` invocation in the
step runs without a path (a negative source walk, so over-matching is the safe side).

Killing mutation: replace the step's ``scripts/run_tests_bundled.sh tests`` with
``scripts/run_tests.sh -j 16`` -> both tests red.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "Harness_Brain" / "50 — Agent Handoffs" / "Dispatching a lane.md"

#: A backticked runner invocation; group 1 is its argument tail.
_INVOCATION = re.compile(r"`(?:bash )?scripts/run_tests\.sh([^`]*)`")


def _landing_gate_step() -> str:
    text = PAGE.read_text(encoding="utf-8")
    section = text.split("## 5. Landing a batch", 1)[1].split("\n## ", 1)[0]
    match = re.search(r"^4\. .*?(?=^\d+\. )", section, flags=re.DOTALL | re.MULTILINE)
    assert match, "§ 5 has no step 4 — the landing gate step moved; re-point this test"
    return match.group(0)


def _pathless_invocations(step: str) -> list[str]:
    found = []
    for tail in _INVOCATION.findall(step):
        command = re.split(r"[>;|&]", tail, maxsplit=1)[0]  # stop at a redirect or a list operator
        args = [a for a in command.split() if not a.startswith("-") and not a.isdigit()]
        if not args:
            found.append(f"scripts/run_tests.sh{tail}")
    return found


def test_the_landing_step_names_the_bundled_gate():
    assert "`scripts/run_tests_bundled.sh tests" in _landing_gate_step()


def test_the_landing_step_names_no_whole_tree_run():
    assert _pathless_invocations(_landing_gate_step()) == []


def test_the_pathless_detector_has_a_positive_control():
    step = (
        "run `scripts/run_tests.sh -j 16 > .landlog 2>&1` then "
        "`scripts/run_tests.sh -j 4 tests/foo.py > log`"
    )
    assert _pathless_invocations(step) == ["scripts/run_tests.sh -j 16 > .landlog 2>&1"]
