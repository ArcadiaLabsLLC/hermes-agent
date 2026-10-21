"""``scripts/source_cache.py``: one read and one parse per file version per process.

Killing mutations (2026-10-18): drop the ``key in _TREES`` hit branch in ``tree`` ->
``test_a_second_walker_reads_the_first_walkers_parse`` red; key ``_key`` on the path
alone -> ``test_a_rewritten_file_is_read_again`` red.
"""

from __future__ import annotations

import pytest

from scripts import god_file_scope, source_cache


@pytest.fixture(autouse=True)
def _empty_cache():
    source_cache.clear()
    yield
    source_cache.clear()


def test_a_second_walker_reads_the_first_walkers_parse(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("X = 1\n", encoding="utf-8")
    first = god_file_scope.tree(tmp_path, "mod.py")  # the god-file gates' door
    second = source_cache.tree(path)  # every other walker's door
    assert first is second
    assert source_cache.stats() == {"reads": 1, "read_hits": 0, "parses": 1, "parse_hits": 1}


def test_a_rewritten_file_is_read_again(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("X = 1\n", encoding="utf-8")
    assert source_cache.source(path) == "X = 1\n"
    path.write_text("LONGER = 22\n", encoding="utf-8")
    assert source_cache.source(path) == "LONGER = 22\n"
    assert [n.targets[0].id for n in source_cache.tree(path).body] == ["LONGER"]


def test_a_file_that_does_not_parse_is_none_and_undecodable_bytes_are_replaced(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")
    assert source_cache.tree(bad) is None
    odd = tmp_path / "odd.py"
    odd.write_bytes(b"S = '\xff'\n")
    assert source_cache.tree(odd) is not None


def test_trees_past_the_budget_are_evicted_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(source_cache, "TREE_BUDGET_BYTES", 20)
    paths = []
    for index in range(3):
        path = tmp_path / f"m{index}.py"
        path.write_text(f"VALUE_{index} = 1\n", encoding="utf-8")  # 12 bytes each
        paths.append(path)
        source_cache.tree(path)
    source_cache.tree(paths[2])
    assert source_cache.stats()["parse_hits"] == 1
    source_cache.tree(paths[0])  # evicted: parsed again
    assert source_cache.stats()["parses"] == 4


def test_a_single_pass_walker_reads_a_kept_tree_and_keeps_none_of_its_own(tmp_path):
    kept, passing = tmp_path / "kept.py", tmp_path / "passing.py"
    kept.write_text("K = 1\n", encoding="utf-8")
    passing.write_text("P = 1\n", encoding="utf-8")
    first = source_cache.tree(kept)
    assert source_cache.tree(kept, keep=False) is first
    assert source_cache.tree(passing, keep=False) is not source_cache.tree(passing, keep=False)
    assert source_cache.stats()["parses"] == 3
