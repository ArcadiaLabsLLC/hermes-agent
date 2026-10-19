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
        _rel=lambda f, r: f.relative_to(r).as_posix(), _UNCACHED_ESTIMATE_SECONDS=30.0,
    )
    args = SimpleNamespace(since=None, skip_list=None, cache_dir=None, paths=[], cache_dry_run=True, fail_fast=False,
                           jobs=8)

    assert affected.main(args, repo, runner, []) == 0

    out = capsys.readouterr().out
    assert f"{T_DIRECT}  — imports {MOD}" in out and T_OTHER not in out
    assert "Σ 30 s, floor 3.8 s at -j 8 — under-a-minute edit" in out, "the bar is on the Affected line"
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


def test_a_source_walker_is_counted_not_run_and_a_data_file_it_opened_selects_it(tmp_path):
    store = cache.GateStore(tmp_path / "gate")
    store.write_deps({
        T_OTHER: cache.FileDeps(paths={T_OTHER, MOD}),  # read MOD's text, imports none of it
        T_FAR: cache.FileDeps(paths={T_FAR, "docs/table.md"}),
    }, "run-1")
    sel = affected.select_affected(
        [T_OTHER, T_FAR], affected.Change({MOD, "docs/table.md"}), store.load_deps(), store.load_modsets(),
        affected.ImportGraph(IMPORTS),
    )

    assert sel.walkers == [T_OTHER] and T_OTHER not in sel.picks
    assert sel.picks[T_FAR].why == "opened docs/table.md"


def _own_store(tmp_path: Path) -> cache.GateStore:
    """Every process imported MOD; T_CHAIN loaded it itself, T_DIRECT named it, the rest neither."""

    store = cache.GateStore(tmp_path / "gate")
    session = {MOD, "agent_runtime/helper.py", "agent_runtime/outer.py", "hermes_cli/config.py"}
    own = {T_CHAIN: ({MOD}, set()), T_DIRECT: (set(), {MOD}), T_FAR: (set(), set()), T_OTHER: (set(), set())}
    store.write_deps({
        rel: cache.FileDeps(paths={rel}, mods=set(session), mods_own=loaded, mods_ref=named,
                            own_records=1, deps_records=1)
        for rel, (loaded, named) in own.items()
    }, "run-1")
    return store


def test_a_record_with_its_own_modules_selects_exactly_the_files_that_loaded_or_named_the_module(tmp_path):
    store = _own_store(tmp_path)
    imports = {**IMPORTS, T_OTHER: {"agent_runtime.helper"}}  # two static hops: the old reach picked it
    sel = affected.select_affected(
        [T_DIRECT, T_CHAIN, T_FAR, T_OTHER], affected.Change({MOD}), store.load_deps(), store.load_modsets(),
        affected.ImportGraph(imports),
    )

    assert sel.picks[T_CHAIN].why == f"loaded {MOD} (recorded)"
    assert sel.picks[T_DIRECT].why == f"imports {MOD} (recorded)"
    assert sel.picks[T_DIRECT].group == affected.DIRECT
    assert T_OTHER not in sel.picks and T_FAR not in sel.picks
    assert sel.uncovered == []


def test_a_module_only_the_session_loaded_falls_back_to_the_reach_rules(tmp_path):
    store = _own_store(tmp_path)
    helper = "agent_runtime/helper.py"  # in every process's set, in no file's own
    sel = affected.select_affected(
        [T_DIRECT, T_CHAIN, T_FAR, T_OTHER], affected.Change({helper}), store.load_deps(), store.load_modsets(),
        affected.ImportGraph(IMPORTS),
    )

    assert sel.uncovered == [helper]
    assert sel.picks[T_CHAIN].why == f"reach rule: imports {helper}"
    assert set(sel.picks) == {T_CHAIN}


def test_a_module_the_file_loaded_that_imports_the_change_selects_it_when_an_earlier_member_loaded_the_change(tmp_path):
    """q-runner 2026-10-18 (r-recorder ``1bf2272916`` row): T_CHAIN loaded MOD first, so T_VIA's own
    set names only the intermediate it loaded (helper imports MOD); T_FAR loaded outer, two hops out."""

    store = cache.GateStore(tmp_path / "gate")
    session = {MOD, "agent_runtime/helper.py", "agent_runtime/outer.py"}
    own = {T_CHAIN: {MOD}, T_DIRECT: {"agent_runtime/helper.py"}, T_FAR: {"agent_runtime/outer.py"}}
    store.write_deps({
        rel: cache.FileDeps(paths={rel}, mods=set(session), mods_own=loaded | {rel}, mods_ref=set(),
                            own_records=1, deps_records=1)
        for rel, loaded in own.items()
    }, "run-1")
    imports = {**IMPORTS, T_DIRECT: {"agent_runtime.helper"}}
    sel = affected.select_affected(
        [T_DIRECT, T_CHAIN, T_FAR], affected.Change({MOD}), store.load_deps(), store.load_modsets(),
        affected.ImportGraph(imports),
    )

    assert sel.picks[T_DIRECT].why == f"loaded agent_runtime/helper.py (recorded), which reaches {MOD}"
    assert T_FAR not in sel.picks, "an intermediate counts one hop out, never two"
    assert set(sel.picks) == {T_CHAIN, T_DIRECT}


def test_fail_fast_runs_edited_and_direct_importers_first_and_the_slowest_last():
    picks = [affected.Pick("e", "edited", affected.EDITED), affected.Pick("d", "x", affected.DIRECT),
             affected.Pick("r", "y", affected.REST)]
    waves = affected.fail_fast_waves(picks)

    assert [[p.rel for p in w] for w in waves] == [["e", "d"], ["r"]]
    assert affected.wave_name(waves[0]) == "edited + direct importers"
    assert affected.fail_fast_waves(picks[2:]) == [[picks[2]]]


def test_the_runner_reads_the_affected_durations_in_its_own_spelling(tmp_path):
    """q-runner 2026-10-18: the store keys durations POSIX, the runner's estimate reads the OS
    spelling; --affected passed them raw, so on Windows every file estimated 30 s."""
    from scripts import run_tests_bundled as bundled

    rel = "tests/agent_runtime/test_operator_redo.py"
    keyed = affected.os_keyed({rel: 190.0})
    assert bundled._estimate(tmp_path / rel, tmp_path, keyed) == 190.0
    assert affected.Pick(rel, "x").rel in keyed, "the selection's POSIX order keys stay"


def test_a_selection_over_sixty_seconds_a_job_is_a_hub_edit():
    """p10-suite B.1: the locks.py selection's recorded Σ 1,027 s at -j 8 is a hub edit; its bar is
    1.25 × floor + 20 s, and a wall over it prints the banner (a verdict, never an exit code)."""

    durations = {"tests/a.py": 1000.0, "tests/b.py": 27.0}
    bar = affected.bar_for(["tests/a.py", "tests/b.py"], durations, 8, 30.0)

    assert (bar.sigma, round(bar.floor, 1), bar.hub) == (1027.0, 128.4, True)
    assert bar.line() == "Σ 1027 s, floor 128.4 s at -j 8 — hub edit"
    assert bar.seconds == 1.25 * bar.floor + 20.0
    assert affected.bar_verdict(bar.seconds + 1, bar)[-1] == "=== affected wall over its bar ==="
    assert len(affected.bar_verdict(bar.seconds, bar)) == 1


def test_a_small_selection_is_an_under_a_minute_edit():
    durations = {"tests/a.py": 100.0}
    bar = affected.bar_for(["tests/a.py", "tests/untimed.py"], durations, 8, 30.0)

    assert (bar.sigma, bar.hub, bar.verdict, bar.seconds) == (130.0, False, "under-a-minute edit", 60.0)
    assert affected.bar_verdict(61.0, bar) == ["affected: wall 61.0 s vs bar 60.0 s (under-a-minute edit)",
                                               "=== affected wall over its bar ==="]
