"""A second copy of a list of ids or names in hermes' own code is refused when it is written.

Row ``FH-DUPLICATE-LITERAL-TABLES-REFUSED`` (task ``TASK-ONE-FACT-ONE-PLACE``, whose
Eternia half is ``EterniaLauncher/test/architecture/duplicate_literal_tables_test.dart``).
A fact lives in one module; every other reader imports it.

NEGATIVE gate, so a source walk is the right shape: the same set of four or more
distinct ``str`` or ``int`` constants, written as a list, tuple or set literal in two
fork production files, reds -- unless the baseline ``duplicate_literal_tables_baseline.txt``
holds that table with exactly those files. Population: ``god_file_probe.fork_production_files``
-- tracked ``.py`` minus the upstream manifest (``tests/fixtures/upstream_manifest.txt``),
tests outside ``tests/_downstream/`` excluded. Upstream files are exempt by that manifest
and never edited; a fork hunk inside one is not read.

A table is keyed by its sorted distinct values, so order and quoting do not matter; an
element that is not a plain constant (a name, an f-string, a ``bool``) keeps the literal
out of the walk -- the safe direction for a gate that only refuses NEW copies. The id is
the Eternia gate's FNV-1a of ``s:<text>`` / ``i:<int>`` values, so a table both repos
write has one id in both baselines.

The baseline is today's duplicates and is SHRINK-ONLY: a line whose copies went away reds
until it is cut, and the line count may never pass ``_SEEDED``. Never add a line to make
a new copy pass -- import the owner instead. A reviewed exemption (two tables that only
happen to match) carries ``exempt:`` and its reason, and is shrink-only too.

Killing mutation (recorded on the row): append
``_MUTATION = ("p0", "p1", "p2", "p3")`` -- ``board_models.CARD_PRIORITIES``, already
copied in two other files -- to ``agent_runtime/serde.py`` and
``test_no_list_of_ids_is_written_in_a_second_file`` reds: ``f20c475a gained a copy in
agent_runtime/serde.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import god_file_probe as probe
from scripts import source_cache

pytestmark = pytest.mark.gate

_BASELINE = Path(__file__).with_name("duplicate_literal_tables_baseline.txt")

# The baseline's line count when it was seeded (2026-11-16, lane w1115e-fh5). Never raise it.
_SEEDED = 21

MIN_TABLE_VALUES = 4


def _value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        if isinstance(node.value, str):
            return f"s:{node.value}"
        if isinstance(node.value, int):
            return f"i:{node.value}"
    return None


def literal_tables(tree: ast.AST) -> list[list[str]]:
    """The sorted distinct values of every list/tuple/set literal of 4+ plain constants."""
    tables: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        values = [_value(elt) for elt in node.elts]
        if any(v is None for v in values):
            continue
        distinct = sorted(set(values))  # type: ignore[arg-type]
        if len(distinct) >= MIN_TABLE_VALUES:
            tables.append(distinct)
    return tables


def table_id(values: list[str]) -> str:
    """FNV-1a, 32 bits, over the values joined by U+0001 (UTF-16 units, as Dart's codeUnits)."""
    digest = 0x811C9DC5
    joined = "\u0001".join(values).encode("utf-16-le")
    for i in range(0, len(joined), 2):
        digest ^= joined[i] | (joined[i + 1] << 8)
        digest = (digest * 0x01000193) & 0xFFFFFFFF
    return f"{digest:08x}"


def duplicate_tables(trees: dict[str, ast.AST]) -> list[tuple[str, list[str], set[str]]]:
    """``(id, values, files)`` for every table written in two or more files."""
    by_id: dict[str, tuple[list[str], set[str]]] = {}
    for path, tree in trees.items():
        for values in literal_tables(tree):
            by_id.setdefault(table_id(values), (values, set()))[1].add(path)
    return sorted(
        (tid, values, files) for tid, (values, files) in by_id.items() if len(files) > 1
    )


def parse_baseline(text: str) -> dict[str, set[str]]:
    """``<id>  <file>, <file>…  # <preview> — <reason>`` lines; ``#`` and blank lines are comments."""
    held: dict[str, set[str]] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        tid, rest = line.split("  ", 1)
        held[tid] = set(rest.split("  #", 1)[0].split(", "))
    return held


def baseline_line(tid: str, values: list[str], files: set[str], reason: str) -> str:
    preview = " | ".join(v[2:] for v in values[:3])
    return f"{tid}  {', '.join(sorted(files))}  # {len(values)} values ({preview} …) — {reason}"


def judge(
    current: list[tuple[str, list[str], set[str]]], held: dict[str, set[str]]
) -> tuple[list[str], list[str]]:
    """(added, stale): a new table or a file a held one gained; a held line no longer true."""
    seen = {tid: files for tid, _, files in current}
    added = [
        f"{tid} gained a copy in {path} ({', '.join(values[:4])})"
        if tid in held
        else f"{tid} is new: {', '.join(sorted(files))} ({', '.join(values[:4])})"
        for tid, values, files in current
        for path in (sorted(files - held[tid]) if tid in held else [None])
    ]
    stale = [
        f"{tid} no longer copied in {path} -- cut it from the line"
        if tid in seen
        else f"{tid} is no longer duplicated -- delete its line"
        for tid, files in held.items()
        for path in (sorted(files - seen[tid]) if tid in seen else [None])
    ]
    return added, stale


def _fork_trees() -> dict[str, ast.AST]:
    trees: dict[str, ast.AST] = {}
    for path in probe.fork_production_files():
        tree = source_cache.tree(probe.ROOT / path)
        if tree is not None:
            trees[path] = tree
    return trees


def test_no_list_of_ids_is_written_in_a_second_file():
    trees = _fork_trees()
    assert len(trees) > 1000, f"the walk read little: {len(trees)} fork files"
    held = parse_baseline(_BASELINE.read_text(encoding="utf-8"))
    added, stale = judge(duplicate_tables(trees), held)
    assert added == [], (
        "a list of ids or names was written a second time; import the one owner "
        "instead of copying it (never add a baseline line):\n" + "\n".join(added)
    )
    assert stale == [], (
        f"the baseline only shrinks -- cut these from {_BASELINE.name}:\n" + "\n".join(stale)
    )
    assert len(held) <= _SEEDED, f"the baseline grew past its seeded {_SEEDED} lines"


def _trees(**sources: str) -> dict[str, ast.AST]:
    return {f"{name}.py": ast.parse(text) for name, text in sources.items()}


def test_the_scanner_finds_a_four_value_table_in_two_files_whatever_the_order():
    found = duplicate_tables(
        _trees(a="IDS = ['a', 'b', 'c', 'd']", b='X = {"d", "c", "b", "a"}', c="FEW = ('a', 'b', 'c')")
    )
    assert [files for _, _, files in found] == [{"a.py", "b.py"}]


def test_the_scanner_ignores_short_mixed_and_interpolated_lists():
    found = duplicate_tables(
        _trees(
            a="X = ['a', 'b', 'c', 'd']",
            b="Y = ['a', 'b', 'c', name]",
            c="Z = ['a', 'b', 'c', f'{d}']",
            d="W = [True, False, 0, 1]\nV = [True, False, 0, 1]",
        )
    )
    assert found == []


def test_a_new_copy_a_gained_file_and_a_stale_line_are_each_named():
    current = duplicate_tables(_trees(a="['a','b','c','d']", b="['a','b','c','d']", c="['a','b','c','d']"))
    tid = current[0][0]
    added, stale = judge(current, {tid: {"a.py", "b.py"}, "deadbeef": {"x.py", "y.py"}})
    assert len(added) == 1 and "c.py" in added[0]
    assert len(stale) == 1 and "deadbeef" in stale[0]


def test_the_id_matches_the_eternia_gate():
    # Dart: tableId(['s:jpeg', 's:jpg', 's:png', 's:webp']) == '0b9a879a' (its baseline, 9d1d09cbaa).
    assert table_id(["s:jpeg", "s:jpg", "s:png", "s:webp"]) == "0b9a879a"
