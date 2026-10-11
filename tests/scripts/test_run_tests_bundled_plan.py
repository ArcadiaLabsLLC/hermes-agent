"""Suite-speed Stages 0-3 in the bundled runner, pinned without spawning pytest.

Plan: ``docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md`` §3.

* Stage 0 — the run ledger records every process and prints what the run cost;
* Stage 1 — a file on the upstream skip list runs only when named, in both scopes;
* Stage 2 — a red member whose failing set is unchanged since the last
  recorded run is reported from its bundle, never re-run alone (O5);
* Stage 3 — bundles are cut by a duration budget, slow files run alone, and
  solos are submitted before bundles.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

plan = bundled.plan


def _tree(root: Path, rels: list[str]) -> list[Path]:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return [root / rel for rel in rels]


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _bundle_runner(root: Path, red: dict[str, list[str]], calls: list):
    """Writes the plugin's events: members in ``red`` fail the given node ids."""

    def _run(first, args, repo_root, timeout):
        calls.append(("bundle", _rel(root, first)))
        events = Path(next(a for a in args if a.startswith("--hermes-bundle-events=")).split("=", 1)[1])
        members = [first] + [Path(a) for a in args if a.endswith(".py")]
        records, rc = [{"k": "start", "t": 0.0}], 0
        for member in members:
            rel = _rel(root, member)
            records.append({"k": "collect", "f": rel, "d": 0.25, "err": False})
            for nodeid in red.get(rel, []):
                rc = 1
                records.append({"k": "test", "f": rel, "c": "failed", "d": 1.0, "n": nodeid})
            if rel not in red:
                records.append({"k": "test", "f": rel, "c": "passed", "d": 0.5})
        records.append({"k": "end", "t": 1.0, "rc": rc})
        events.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return first, rc, "FAILED tests/alpha/test_1.py::test_ok - assert 1 == 2", {}, 2.0

    return _run


def _solo_runner(root: Path, calls: list, rc: int = 1):
    def _run(path, args, repo_root, timeout, retries):
        calls.append(("solo", _rel(root, path)))
        return path, rc, "red alone" if rc else "ok", {"failed": 1} if rc else {"passed": 1}, 0.5

    return _run


def _run(root, files, red, known, calls, **kw):
    return bundled.run(
        files, [], root, jobs=kw.pop("jobs", 2), bundle_size=20, flat_timeout=300.0, retries=0,
        durations=kw.pop("durations", {}), known_reds=known,
        bundle_runner=_bundle_runner(root, red, calls), solo_runner=_solo_runner(root, calls), **kw,
    )


# ── Stage 3: duration-budget bundles, slow files alone and first ────────────


def test_a_budget_closes_a_bundle_before_it_overflows_and_a_heavy_member_stands_alone():
    members = [(Path(n), s) for n, s in [("a", 50), ("b", 50), ("c", 30), ("d", 200), ("e", 10)]]

    assert plan.cut_by_budget(members, 120, 20) == [[Path("a"), Path("b")], [Path("c")], [Path("d")], [Path("e")]]
    assert plan.cut_by_budget(members, 0, 2) == [[Path("a"), Path("b")], [Path("c"), Path("d")], [Path("e")]]


def test_no_bundle_passes_the_budget_by_more_than_its_largest_member(tmp_path):
    """The plan's positive control for Stage 3, on synthetic gate-shaped durations."""
    rels = [f"tests/alpha/test_{i:02d}.py" for i in range(40)]
    files = _tree(tmp_path, rels)
    durations = {str(Path(r)): float((i * 7) % 45 + 1) for i, r in enumerate(rels)}

    bundles, solos = bundled.assign_bundles(
        files, tmp_path, 20, durations=durations, bundle_seconds=120.0, solo_seconds=60.0
    )

    sums = [sum(durations[str(Path(_rel(tmp_path, m)))] for m in b) for b in bundles]
    assert solos == [] and max(sums) <= 120.0 + max(durations.values())
    assert sorted(_rel(tmp_path, m) for b in bundles for m in b) == rels


def test_a_file_cached_over_the_solo_budget_runs_alone_and_before_every_bundle(tmp_path):
    rels = ["tests/alpha/test_0.py", "tests/alpha/test_1.py", "tests/alpha/test_slow.py"]
    files = _tree(tmp_path, rels)
    calls: list = []

    result = _run(
        tmp_path, files, {}, {}, calls, jobs=1,
        durations={str(Path("tests/alpha/test_slow.py")): 90.0}, bundle_seconds=120.0, solo_seconds=60.0,
    )

    assert [_rel(tmp_path, s) for s in result.solos] == ["tests/alpha/test_slow.py"]
    assert calls[0] == ("solo", "tests/alpha/test_slow.py") and calls[1][0] == "bundle"


# ── Stage 2: a red is not paid for twice ────────────────────────────────────


def test_a_red_member_unchanged_since_the_last_run_is_reported_from_its_bundle(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    red = {"tests/alpha/test_1.py": ["tests/alpha/test_1.py::test_ok"]}
    calls: list = []

    result = _run(tmp_path, files, red, {k: frozenset(v) for k, v in red.items()}, calls)

    assert [c for c in calls if c[0] == "solo"] == []
    outcome = next(o for o in result.outcomes if o.file.name == "test_1.py")
    assert (outcome.via, outcome.rc, result.reruns) == ("known-red", 1, 0)
    assert "O5" in outcome.output and "tests/alpha/test_1.py::test_ok" in outcome.output
    assert "FAILED tests/alpha/test_1.py::test_ok" in outcome.output
    assert result.ledger.known_red == ["tests/alpha/test_1.py"]


def test_a_red_member_whose_failing_set_changed_is_re_run_alone(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    red = {"tests/alpha/test_1.py": ["tests/alpha/test_1.py::test_ok", "tests/alpha/test_1.py::test_new"]}
    calls: list = []

    result = _run(tmp_path, files, red, {"tests/alpha/test_1.py": frozenset({"tests/alpha/test_1.py::test_ok"})}, calls)

    assert ("solo", "tests/alpha/test_1.py") in calls
    assert next(o for o in result.outcomes if o.file.name == "test_1.py").via == "rerun"


def test_the_record_keeps_reds_drops_greens_and_carries_unrun_files_forward(tmp_path):
    previous = {"tests/a.py": frozenset({"tests/a.py::t"}), "tests/unrun.py": frozenset({"tests/unrun.py::t"})}
    plan.record_run(
        tmp_path, {"elapsed": 1.0},
        final_rc={"tests/a.py": 0, "tests/b.py": 1},
        failed={"tests/b.py": ["tests/b.py::t2", "tests/b.py::t1"]},
        previous=previous,
    )

    assert plan.load_known_reds(tmp_path) == {
        "tests/b.py": frozenset({"tests/b.py::t1", "tests/b.py::t2"}),
        "tests/unrun.py": frozenset({"tests/unrun.py::t"}),
    }
    assert plan.load_known_reds(tmp_path / "nowhere") == {}


def test_an_idle_box_line_after_a_gate_line_does_not_erase_the_known_reds(tmp_path):
    """scripts/run_tests_idle.sh appends a ``"kind": "idle"`` line with no red map;
    the next gate still reads the last GATE line's reds (design sweep D3.01)."""
    plan.record_run(tmp_path, {"elapsed": 1.0}, final_rc={"tests/b.py": 1}, failed={"tests/b.py": ["tests/b.py::t"]}, previous={})
    with (tmp_path / plan.RUNS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": plan.IDLE_RUN_KIND, "rc": 0, "files": ["tests/agent_runtime/x.py"]}) + "\n")

    assert plan.load_known_reds(tmp_path) == {"tests/b.py": frozenset({"tests/b.py::t"})}


def test_an_empty_failing_set_is_never_known_red():
    assert not plan.is_known_red("a.py", [], {"a.py": frozenset()})
    assert not plan.is_known_red("a.py", ["a.py::t"], {})


# ── Stage 0: the run measures itself ────────────────────────────────────────


def test_the_ledger_counts_processes_work_and_the_double_run_of_a_red(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    calls: list = []

    result = _run(tmp_path, files, {"tests/alpha/test_1.py": ["tests/alpha/test_1.py::test_ok"]}, {}, calls)
    cost = result.ledger.summary(2)

    assert cost["processes"] == {"bundle": 1, "solo": 0, "rerun": 1, "retry": 0}
    # test_0's 0.25 s collect + 0.5 s test; the fake rerun wrote no events
    assert result.ledger.file_seconds == {"tests/alpha/test_0.py": pytest.approx(0.75)}
    assert cost["rerun_seconds"] >= 1.25  # the red's bundle attempt (0.25 + 1.0) plus its run alone
    assert cost["critical"]["kind"] in {"bundle", "rerun"}
    text = "\n".join(plan.render(cost))
    assert "utilization" in text and "idle tail" in text and "critical path" in text


def test_the_idle_tail_starts_when_the_pool_last_stopped_being_full():
    procs = [plan.Process("bundle", ["a"], 0, 10), plan.Process("bundle", ["b"], 0, 4), plan.Process("solo", ["c"], 4, 6)]

    assert plan.idle_tail(procs, 2, 0, 10) == pytest.approx(4.0)  # full until 6, then one worker to 10
    assert plan.idle_tail(procs, 3, 0, 10) == pytest.approx(10.0)  # never full


# ── Stage 1: the skip list ──────────────────────────────────────────────────


def test_a_listed_file_is_skipped_in_both_scopes_even_when_reached_but_runs_when_named(tmp_path):
    files = _tree(tmp_path, ["tests/pkg/test_fork.py", "tests/pkg/test_up.py", "tests/pkg/test_listed.py"])
    inherited = {"tests/pkg/test_up.py", "tests/pkg/test_listed.py"}
    listed = {"tests/pkg/test_listed.py"}

    fork = bundled.select_scope(files, tmp_path, inherited, {"tests/pkg/test_listed.py"}, skipped=listed)
    full = bundled.select_scope(files, tmp_path, set(), set(), skipped=listed, full=True)
    named = bundled.select_scope(files, tmp_path, inherited, set(), named=[files[2]], skipped=listed)

    assert [_rel(tmp_path, p) for p in fork.skipped_red] == ["tests/pkg/test_listed.py"]
    assert [_rel(tmp_path, p) for p in fork.selected] == ["tests/pkg/test_fork.py"]
    assert [_rel(tmp_path, p) for p in full.selected] == ["tests/pkg/test_fork.py", "tests/pkg/test_up.py"]
    assert [_rel(tmp_path, p) for p in named.named] == ["tests/pkg/test_listed.py"] and not named.skipped_red


def test_a_skip_row_has_three_fields_and_a_class_word(tmp_path):
    row = plan.parse_skip_line("tests/x/test_a.py · env: hangs on the provider network · abcdef0123")
    assert (row.path, row.klass, row.sha) == ("tests/x/test_a.py", "env", "abcdef0123")
    assert plan.parse_skip_line("# comment") is None and plan.parse_skip_line("  ") is None
    with pytest.raises(ValueError, match="path · why · upstream SHA"):
        plan.parse_skip_line("tests/x/test_a.py · env: no sha")
    with pytest.raises(FileNotFoundError):
        plan.load_skip_list(tmp_path / "missing.txt")


# ── O4: a fresh landing worktree plans from the primary checkout's record ────

def _clone_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    import subprocess

    def git(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    primary = tmp_path / "primary"
    primary.mkdir()
    git(primary, "init", "-q")
    (primary / "README").write_text("x", encoding="utf-8")
    git(primary, "add", "README")
    git(primary, "-c", "user.name=o4", "-c", "user.email=o4@example.invalid", "commit", "-q", "-m", "seed")
    worktree = tmp_path / "landing"
    git(primary, "worktree", "add", "-q", "--detach", str(worktree))
    return primary, worktree


def test_a_fresh_worktree_reads_the_primarys_durations_and_run_record(tmp_path):
    primary, worktree = _clone_with_worktree(tmp_path)
    assert plan.primary_checkout(worktree).resolve() == primary.resolve()
    assert plan.primary_checkout(primary) is None

    (primary / "test_durations.json").write_text(json.dumps({"tests/a.py": 90.0, "tests/b.py": 3.0}), encoding="utf-8")
    (worktree / "test_durations.json").write_text(json.dumps({"tests/b.py": 4.0}), encoding="utf-8")
    durations = plan.load_durations_with_primary(worktree, bundled.rtp._load_durations)
    assert durations == {"tests/a.py": 90.0, "tests/b.py": 4.0}

    record = primary / plan.RUNS_FILE
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"red": {"tests/a.py": ["tests/a.py::t"]}}) + "\n", encoding="utf-8")
    assert plan.load_known_reds(worktree) == {"tests/a.py": frozenset({"tests/a.py::t"})}
    own = worktree / plan.RUNS_FILE
    own.parent.mkdir(parents=True)
    own.write_text(json.dumps({"red": {}}) + "\n", encoding="utf-8")
    assert plan.load_known_reds(worktree) == {}
