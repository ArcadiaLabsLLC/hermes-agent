"""W0-G5 — routing is data: no new ladder on a string, a kind or an ``isinstance``.

Plan: ``docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`` rule
12 and §2.4. Three arms, all a NEGATIVE guarantee over the AST (a source walk is
the right instrument for "this is never written"):

* ``ladder`` — >= 3 arms in one body comparing the SAME subject against string
  constants, counted across sibling guard ``if``s AND down ``elif`` chains;
* ``isinstance`` — >= 3 ``isinstance`` arms on one subject;
* ``vocab`` — a compare against a member of a vocabulary the fork declares as a
  ``Final`` string collection or a string ``Enum``. The vocabulary is
  ENUMERATED from those declarations by the same walk, never typed here.

Baseline: ``tests/fixtures/ladder_routing_grandfathered.json`` (one row per
``path|function|kind|subject``; arms only shrink).
"""

from __future__ import annotations

import ast

from scripts import god_file_probe as probe


def _drift() -> probe.Drift:
    return probe.compare_numbers("W0-G5 ladder routing", probe.ladder_live(), probe.ladder_fixture())


def _ladders(source: str) -> set[tuple[str, str, int]]:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return set(probe._ladders_in(node.body))


def test_the_detector_sees_both_spellings_of_a_ladder():
    """Positive control: guard siblings and an elif chain are the same ladder; two arms are not."""
    guards = (
        "def h(op):\n"
        " if op == 'ping':\n  return 1\n"
        " if op == 'hello':\n  return 2\n"
        " if op == 'version':\n  return 3\n"
    )
    assert _ladders(guards) == {("ladder", "op", 3)}
    chained = (
        "def h(m):\n if m.kind in ('a', 'b'):\n  pass\n"
        " elif m.kind == 'c':\n  pass\n elif 'd' == m.kind:\n  pass\n"
    )
    assert _ladders(chained) == {("ladder", "m.kind", 3)}
    isinst = (
        "def h(v):\n if isinstance(v, bool):\n  pass\n"
        " elif isinstance(v, int):\n  pass\n if isinstance(v, str):\n  pass\n"
    )
    assert _ladders(isinst) == {("isinstance", "v", 3)}
    assert _ladders("def h(op):\n if op == 'a':\n  pass\n elif op == 'b':\n  pass\n") == set()


def test_the_vocabulary_is_enumerated_from_declarations():
    tree = ast.parse(
        "from enum import Enum\nfrom typing import Final\n"
        "KINDS: Final = ('alpha', 'beta')\n"
        "WORDS: Final[frozenset[str]] = frozenset({'gamma'})\n"
        "class Mode(str, Enum):\n    ON = 'delta'\n"
        "PLAIN = ('not-a-vocabulary',)\n"
    )
    assert probe._vocabulary_strings(tree) == {"alpha", "beta", "gamma", "delta"}
    assert len(probe.vocabulary()) > 50, "the fork's declared vocabularies went missing from the walk"


def test_no_new_ladder():
    drift = _drift()
    assert not drift.new, (
        "new routing ladders — make the vocabulary a dispatch table / registry / strategy "
        "(rule 12), do not add a row:\n" + drift.render()
    )


def test_no_grandfathered_ladder_grew():
    drift = _drift()
    assert not drift.grew, "a grandfathered ladder gained arms:\n" + drift.render()


def test_a_converted_ladder_loses_its_row():
    drift = _drift()
    assert not drift.stale, "delete these rows — the ladder is gone:\n" + drift.render()
