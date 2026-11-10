"""`scripts/census_pool.py` and the order-independent binding walk it relies on (FH-PREPUSH-CAP-TIGHT).

The name census gates map their whole-tree walk over worker processes in chunks. That is
only sound if (1) the chunks cover the population once, in order, and come back in order,
and (2) a file's census row does not depend on which file a process happened to read
first — ``god_file_scope.module_bindings`` used to cache an import cycle's CUT answer and
serve it to every later caller, so a chunk that entered the cycle elsewhere read a
different binding than the serial walk.
"""

from __future__ import annotations

import subprocess

import pytest

from scripts import census_pool as pool
from scripts import god_file_probe as probe
from scripts import god_file_scope as scope
from scripts import source_cache


def test_chunks_cover_every_item_once_contiguous_and_in_order():
    items = list(range(23))
    for parts in (1, 2, 5, 23, 40):
        cut = pool.chunks(items, parts)
        assert [x for chunk in cut for x in chunk] == items
        assert len(cut) == min(parts, len(items))
        assert max(map(len, cut)) - min(map(len, cut)) <= 1
    assert pool.chunks([], 4) == []


def test_census_jobs_reads_the_env_and_stays_serial_for_a_small_census(monkeypatch):
    monkeypatch.setenv("HERMES_CENSUS_JOBS", "5")
    assert pool.census_jobs(pool.MIN_PARALLEL) == 5
    assert pool.census_jobs(pool.MIN_PARALLEL - 1) == 1
    monkeypatch.setenv("HERMES_CENSUS_JOBS", "1")
    assert pool.census_jobs(10_000) == 1
    for bad in ("0", "two", "-3"):
        monkeypatch.setenv("HERMES_CENSUS_JOBS", bad)
        with pytest.raises(ValueError):
            pool.census_jobs(10_000)


# KILLING MUTATION: return the futures' results in completion order (``as_completed``) or drop the
# last chunk in ``map_chunks`` -> the pooled answer is not the serial one.
@pytest.mark.timeout(120)
def test_a_pooled_map_answers_what_the_serial_map_answers_in_order(monkeypatch):
    items = [f"item-{i:03d}" for i in range(57)]
    monkeypatch.setattr(pool, "MIN_PARALLEL", 1)
    monkeypatch.setenv("HERMES_CENSUS_JOBS", "3")
    pooled = pool.map_chunks(list, items)
    assert len(pooled) == 3 * pool.CHUNKS_PER_JOB
    assert [x for chunk in pooled for x in chunk] == items
    monkeypatch.setenv("HERMES_CENSUS_JOBS", "1")
    assert pool.map_chunks(list, items) == [items]


def _repo(root, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _forget() -> None:
    scope._CLEAN.clear()
    scope._TOP.clear()
    scope.module_path.cache_clear()
    scope.file_scope.cache_clear()
    source_cache.clear()


# KILLING MUTATION: cache every ``module_bindings`` answer in ``_CLEAN`` (drop the cut check) -> the
# cycle's cut answer for ``cyc.b`` (read from inside ``cyc.a``) is served to the top-level ask.
def test_a_modules_bindings_do_not_depend_on_which_module_was_read_first(tmp_path):
    _repo(tmp_path, {
        "cyc/__init__.py": "",
        "cyc/a.py": "from cyc.b import LATE\nEARLY = 'early'\n",
        "cyc/b.py": "from cyc.a import EARLY\nLATE = 'late'\n",
    })
    try:
        _forget()
        b_first = dict(scope.module_bindings(tmp_path, "cyc/b.py"))
        _forget()
        scope.module_bindings(tmp_path, "cyc/a.py")  # reads b from inside the a->b->a cycle
        a_first = dict(scope.module_bindings(tmp_path, "cyc/b.py"))
    finally:
        _forget()
    assert b_first["EARLY"] == ("str", "early", "cyc.a"), b_first
    assert a_first == b_first


@pytest.mark.timeout(120)
def test_the_chunked_ladder_census_is_the_serial_one(tmp_path, monkeypatch):
    """Positive control on a real walk: the same tree, serial and over three workers."""
    files = {"lpkg/__init__.py": "", "lpkg/kinds.py": (
        "from enum import Enum\nclass Kind(str, Enum):\n    A = 'a'\n    B = 'b'\n    C = 'c'\n")}
    for i in range(12):
        files[f"lpkg/m{i:02d}.py"] = (
            "from lpkg.kinds import Kind\n"
            f"def route{i}(k, op):\n"
            "    if k == 'a':\n        return 1\n    if k == 'b':\n        return 2\n"
            "    if k == 'c':\n        return 3\n"
            "    if isinstance(op, int):\n        return 4\n    elif isinstance(op, str):\n        return 5\n"
            "    elif isinstance(op, bytes):\n        return 6\n"
        )
    _repo(tmp_path, files)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("# base x\n", encoding="utf-8")
    monkeypatch.setattr(probe, "MANIFEST", manifest)
    population = probe.fork_production_files.__wrapped__(tmp_path, manifest)
    monkeypatch.setattr(probe, "fork_production_files", lambda root=None, manifest=None: population)
    try:
        monkeypatch.setenv("HERMES_CENSUS_JOBS", "1")
        _forget()
        serial = probe.ladder_census(tmp_path)
        monkeypatch.setattr(pool, "MIN_PARALLEL", 1)
        monkeypatch.setenv("HERMES_CENSUS_JOBS", "3")
        _forget()
        pooled = probe.ladder_census(tmp_path)
    finally:
        _forget()
    assert len(population) == 14
    assert ("lpkg/m00.py", "route0", "ladder", "k") in serial
    assert ("lpkg/m11.py", "route11", "isinstance", "op") in serial
    assert pooled == serial
