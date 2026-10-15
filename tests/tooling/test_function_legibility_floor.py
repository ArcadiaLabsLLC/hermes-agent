"""W0-G7 — no fork function over 150 lines or nested deeper than 4, beyond a shrinking list.

Plan: ``docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`` rule
17 and §2.4 (ruling Q4: a gate). Lines are ``end_lineno - lineno + 1`` of the
def (nested defs included, as the §0.2 table measures them); depth is control-
block nesting inside the function, ``elif`` not counted, nested defs their own
unit. Baseline: ``tests/fixtures/legibility_grandfathered.json``.
"""

from __future__ import annotations

import ast

from scripts import god_file_probe as probe


def _drift() -> probe.Drift:
    return probe.compare_numbers("W0-G7 legibility floor", probe.floor_live(), probe.floor_fixture())


def _depth(source: str) -> int:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return probe.nesting_depth(node)


def test_depth_counts_blocks_and_not_elif():
    """Positive control: five nested blocks read 5; an elif ladder reads 1; a nested def is its own unit."""
    five = (
        "def f(x):\n if x:\n  for y in x:\n   while y:\n    with y:\n"
        "     try:\n      pass\n     except E:\n      pass\n"
    )
    assert _depth(five) == 5
    ladder = "def f(x):\n if x == 1:\n  pass\n elif x == 2:\n  pass\n elif x == 3:\n  pass\n else:\n  pass\n"
    assert _depth(ladder) == 1
    nested_def = "def f(x):\n if x:\n  def g():\n   if x:\n    if x:\n     if x:\n      if x:\n       pass\n"
    assert _depth(nested_def) == 1


def test_no_new_function_breaks_the_floor():
    drift = _drift()
    assert not drift.new, (
        "these functions are over 150 lines or nested deeper than 4 and are not grandfathered — "
        "lift them into an object or helpers (rule 17):\n" + drift.render()
    )


def test_no_grandfathered_function_grew():
    drift = _drift()
    assert not drift.grew, "a grandfathered function GREW (lines or depth):\n" + drift.render()


def test_a_function_back_under_the_floor_loses_its_row():
    drift = _drift()
    assert not drift.stale, "delete these rows — the functions are within the floor now:\n" + drift.render()
