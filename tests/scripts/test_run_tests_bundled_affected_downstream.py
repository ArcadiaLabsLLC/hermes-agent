"""``--affected``: the test files an uncommitted edit can break, from the gate store's records.

``scripts/run_tests_bundled_affected.py`` selects on a store's per-file dependency
records narrowed by static imports, falls back to the ``--scope fork`` reach rules
for a path no record names, lets the skip list win, and writes nothing to the store.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import run_tests_bundled_affected as affected
from scripts import run_tests_bundled_cache as cache

MOD = "agent_runtime/widget.py"
T_DIRECT = "tests/agent_runtime/test_widget_user.py"
T_CHAIN = "tests/agent_runtime/test_via_helper.py"
T_FAR = "tests/agent_runtime/test_far.py"
T_OTHER = "tests/hermes_cli/test_unrelated.py"
T_SPAWN = "tests/tools/test_spawns.py"
TESTS = [T_DIRECT, T_CHAIN, T_FAR, T_OTHER, T_SPAWN]

#: rel → static imports: T_CHAIN reaches MOD in two hops, T_FAR in three
IMPORTS = {
    T_DIRECT: {"agent_runtime.widget"},
    "agent_runtime/helper.py": {"agent_runtime.widget"},
    T_CHAIN: {"agent_runtime.helper"},
    "agent_runtime/outer.py": {"agent_runtime.helper"},
    T_FAR: {"agent_runtime.outer"},
    T_OTHER: {"hermes_cli.config"},
    T_SPAWN: {"agent_runtime.widget"},
}


def _store(tmp_path: Path, spawn: bool = False) -> cache.GateStore:
    """Every recorded process imported MOD (a process-wide module set, as the recorder writes)."""

    store = cache.GateStore(tmp_path / "gate")
    session = {MOD, "agent_runtime/helper.py", "agent_runtime/outer.py", "hermes_cli/config.py"}
    entries = {rel: cache.FileDeps(paths={rel}, mods=set(session)) for rel in TESTS}
    entries[T_SPAWN] = cache.FileDeps(paths={T_SPAWN}, mods={"tools/other.py"}, spawn_other=int(spawn))
    store.write_deps(entries, "run-1")
    return store


def _select(tmp_path, changed, churned=(), skipped=(), spawn=False, imports=IMPORTS, tests=TESTS):
    store = _store(tmp_path, spawn)
    deps = store.load_deps()
    change = affected.Change(set(changed), set(churned))
    return affected.select_affected(
        tests, change, deps, store.load_modsets(), affected.ImportGraph(imports), skipped,
    )


def test_an_edited_module_selects_its_recorded_importers_and_not_an_unrelated_file(tmp_path):
    sel = _select(tmp_path, {MOD})

    assert sel.picks[T_DIRECT].why == f"imports {MOD}"
    assert sel.picks[T_CHAIN].why == f"reaches {MOD} (import chain)"
    assert T_OTHER not in sel.picks  # its process imported MOD; its own imports never reach it
    assert T_FAR not in sel.picks  # three hops: the landing gate's
    assert sel.uncovered == []


def test_an_edited_test_file_is_selected_first(tmp_path):
    sel = _select(tmp_path, {MOD, T_OTHER})
    order = [p.rel for p in sel.ordered({T_DIRECT: 9.0, T_CHAIN: 1.0, T_OTHER: 50.0})]

    assert sel.picks[T_OTHER].why == "edited"
    assert order[:3] == [T_OTHER, T_DIRECT, T_CHAIN]  # edited, direct importers, the rest


def test_the_skip_list_wins_over_every_rule(tmp_path):
    sel = _select(tmp_path, {MOD, T_OTHER}, skipped={T_DIRECT, T_OTHER})

    assert T_DIRECT not in sel.picks and T_OTHER not in sel.picks
    assert sel.skipped == [T_DIRECT, T_OTHER]
    assert T_CHAIN in sel.picks


def test_a_path_no_record_names_falls_back_to_the_reach_rules(tmp_path):
    new = "agent_runtime/brand_new.py"
    imports = {**IMPORTS, T_OTHER: {"agent_runtime.brand_new"}, "tests/agent_runtime/test_brand_new.py": set()}
    tests = TESTS + ["tests/agent_runtime/test_brand_new.py"]
    sel = _select(tmp_path, {new}, churned={new}, imports=imports, tests=tests)

    assert sel.uncovered == [new]
    assert sel.picks[T_OTHER].why == f"reach rule: imports {new}"
    assert sel.picks["tests/agent_runtime/test_brand_new.py"].why == f"reach rule: tests {new} (no record)"
    assert T_DIRECT not in sel.picks


def test_the_all_sentinel_selects_only_a_code_change_its_imports_reach(tmp_path):
    assert T_SPAWN not in _select(tmp_path / "a", {"docs/x.md"}, spawn=True).picks
    assert T_SPAWN not in _select(tmp_path / "b", {"agent_runtime/elsewhere.py"}, spawn=True).picks
    sel = _select(tmp_path / "c", {MOD}, spawn=True)
    assert sel.picks[T_SPAWN].why == f"spawned an unrecorded program; imports {MOD}"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_main_lists_the_selection_and_writes_nothing_to_the_gate_store(tmp_path, capsys):
    repo = tmp_path / "repo"
    for rel, body in {MOD: "X = 1\n", T_DIRECT: "import agent_runtime.widget\n", T_OTHER: "import os\n"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    (repo / MOD).write_text("X = 2\n", encoding="utf-8")
    store = cache.GateStore(repo / ".pytest_cache" / "hermes_gate")
    store.write_deps({rel: cache.FileDeps(paths={rel}, mods={MOD}) for rel in (T_DIRECT, T_OTHER)}, "run-1")
    before = {p.name: p.read_bytes() for p in store.root.iterdir()}
    runner = SimpleNamespace(
        plan=SimpleNamespace(primary_checkout=lambda r: r, load_skip_list=lambda p: {}, SKIP_LIST=Path("none.txt")),
        rtp=SimpleNamespace(_discover_files=lambda roots: sorted(repo.glob("tests/**/test_*.py")), _DEFAULT_ROOTS=["tests"]),
        _rel=lambda f, r: f.relative_to(r).as_posix(),
    )
    args = SimpleNamespace(since=None, skip_list=None, cache_dir=None, paths=[], cache_dry_run=True, fail_fast=False)

    assert affected.main(args, repo, runner, []) == 0

    out = capsys.readouterr().out
    assert f"{T_DIRECT}  — imports {MOD}" in out and T_OTHER not in out
    assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before


def test_a_new_file_selects_a_walker_of_its_directory_but_not_its_siblings(tmp_path):
    store = cache.GateStore(tmp_path / "gate")
    new = "tests/agent_runtime/test_new.py"
    store.write_deps({
        T_DIRECT: cache.FileDeps(paths={T_DIRECT}, dirs={"tests/agent_runtime"}),  # its collection listed it
        T_OTHER: cache.FileDeps(paths={T_OTHER}, dirs={"tests/agent_runtime"}),  # a walker
    }, "run-1")
    sel = affected.select_affected(
        [T_DIRECT, T_OTHER, new], affected.Change({new}, {new}), store.load_deps(), store.load_modsets(),
        affected.ImportGraph({}),
    )

    assert sel.picks[T_OTHER].why == f"lists tests/agent_runtime/ ({new} added or removed)"
    assert T_DIRECT not in sel.picks and sel.picks[new].why == "edited"
