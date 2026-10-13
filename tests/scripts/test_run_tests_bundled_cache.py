"""Fast-gate §1 stages 2-4: the green-result cache's key, decision, skip and audit.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §1. A cache
that hides a real red is the failure this design exists to prevent, so every key
input is proven to invalidate here, in a scratch git repository: the test file,
a recorded module, a recorded data file and listed directory, the conftest
chain, the ALL sentinel of a file that spawned a process, the interpreter lock,
the runner's own files and the runner environment.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_tests_bundled as bundled

cache = bundled.cache
gate_mod = bundled._gate
T = "tests/test_t.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _commit(root: Path, message: str = "c") -> None:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=fg", "-c", "user.email=fg@example.invalid", "commit", "-q", "-m", message)


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for rel, text in {
        T: "def test_ok():\n    pass\n",
        "conftest.py": "# root conftest\n",
        "pkg/__init__.py": "",
        "pkg/mod.py": "VALUE = 1\n",
        "pkg/other.py": "OTHER = 1\n",
        "data/fix.txt": "x\n",
        "listed/a.txt": "a\n",
        "uv.lock": "lock-1\n",
        "scripts/run_tests_bundled.py": "# runner\n",
        "docs/note.md": "doc\n",
        "Harness_Brain/n.md": "brain\n",
    }.items():
        _write(root, rel, text)
    _commit(root, "seed")
    return root


_DEPS = dict(paths={T, "data/fix.txt"}, dirs={"listed"}, mods={"conftest.py", "pkg/__init__.py", "pkg/mod.py"})


def _keyer(root: Path, store: "cache.GateStore", env=None, args=()) -> "cache.Keyer":
    snap = cache.TreeSnapshot.take(root, bundled.scope._scope_git)
    fixed = cache.FixedInputs.collect(snap, list(args), env or {}, interp=["interp\tpinned"])
    deps = store.load_deps()
    return cache.Keyer(snap, fixed, store.load_modsets({d for e in deps.values() for d in e.mods}))


def _green(root: Path, store, deps=None, env=None, *, gen=0) -> None:
    """What a green outcome writes: the file's record and its key under this tree."""

    deps = deps or cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    key = _keyer(root, store, env).key_fresh(T, deps)
    store.write_deps({T: deps}, "r1")
    store.append_green([cache.GreenEntry(T, key, "r1", "2026-10-10", time.time(), 1.5, gen).line()])


def _reason(root: Path, store, env=None, args=(), **kw) -> str:
    keyer = _keyer(root, store, env, args)
    decision = cache.decide(
        [root / T], root, keyer=keyer, disabled=keyer.fixed.disabled, deps=store.load_deps(),
        greens=store.load_green(), generation=store.generation(), **kw,
    )
    return decision.reasons[T]


@pytest.fixture
def store(tmp_path):
    return cache.GateStore(tmp_path / "store")


# ── stage 2: every key input invalidates ────────────────────────────────────


def test_an_unchanged_tree_is_a_hit(repo, store):
    _green(repo, store)
    assert _reason(repo, store) == "hit"


@pytest.mark.parametrize("rel", [T, "pkg/mod.py", "conftest.py", "data/fix.txt"])
def test_editing_the_test_file_a_recorded_module_the_conftest_or_a_data_file_misses(repo, store, rel):
    _green(repo, store)
    _write(repo, rel, (repo / rel).read_text(encoding="utf-8") + "# edited\n")
    _commit(repo)
    assert _reason(repo, store) == "changed"


def test_a_file_added_to_a_listed_directory_misses_and_an_unrelated_edit_does_not(repo, store):
    _green(repo, store)
    _write(repo, "pkg/other.py", "OTHER = 2\n")  # not recorded by this file
    _commit(repo)
    assert _reason(repo, store) == "hit"
    _write(repo, "listed/b.txt", "b\n")
    assert _reason(repo, store) == "changed"


def test_a_file_that_spawned_a_process_depends_on_every_tracked_file_but_docs_and_the_brain(repo, store):
    deps = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()}, spawn_other=1)
    _green(repo, store, deps)
    _write(repo, "docs/note.md", "doc 2\n")
    _write(repo, "Harness_Brain/n.md", "brain 2\n")
    _commit(repo)
    assert _reason(repo, store) == "hit", "owner ruling Q1: docs/ and Harness_Brain/ are outside the ALL sentinel"
    _write(repo, "pkg/other.py", "OTHER = 2\n")
    _commit(repo)
    assert _reason(repo, store) == "changed"


def test_a_dirty_edit_misses_and_committing_it_unchanged_keeps_the_key(repo, store):
    _write(repo, "pkg/mod.py", "VALUE = 2\n")  # uncommitted
    _green(repo, store)  # green under the dirty tree
    assert _reason(repo, store) == "hit"
    _commit(repo)  # the same bytes, now a blob: git-blob hashing keeps the key
    assert _reason(repo, store) == "hit"
    _write(repo, "pkg/mod.py", "VALUE = 3\n")
    assert _reason(repo, store) == "changed"


@pytest.mark.parametrize("rel", ["uv.lock", "scripts/run_tests_bundled.py"])
def test_the_interpreter_lock_and_the_runners_own_files_change_every_key(repo, store, rel):
    _green(repo, store)
    _write(repo, rel, "changed\n")
    _commit(repo)
    assert _reason(repo, store) == "changed"


def test_the_runner_environment_is_in_the_key_but_the_worker_count_and_plugin_dir_are_not(repo, store, tmp_path):
    plugin = str(tmp_path / "plugin")
    env = {"HERMES_TEST_FLAG": "1", "HERMES_TEST_WORKERS": "8", "PYTHONPATH": plugin, "TZ": "UTC"}
    _green(repo, store, env=env)
    assert _reason(repo, store, env={**env, "HERMES_TEST_WORKERS": "2"}) == "hit"
    assert _reason(repo, store, env={**env, "HERMES_TEST_FLAG": "2"}) == "changed"
    assert _reason(repo, store, env={**env, "TZ": "Europe/Paris"}) == "changed"
    snap = cache.TreeSnapshot.take(repo, bundled.scope._scope_git)
    lines = cache.FixedInputs.collect(snap, [], {"PYTHONPATH": plugin}, strip_paths=[plugin], interp=[]).lines
    assert "env\tPYTHONPATH=" in lines


def test_a_passthrough_pytest_arg_disables_reading_and_writing(repo, store, tmp_path):
    _green(repo, store)
    assert _reason(repo, store, args=["-q"]) == "hit"
    assert _reason(repo, store, args=["-k", "ok"]).startswith("off (pytest args -k ok")

    gate = gate_mod.GateRun(repo, cache.GateStore(tmp_path / "s2"), tmp_path / "deps")
    gate.keyer = _keyer(repo, gate.store, args=["-k", "ok"])
    gate.disabled = gate.keyer.fixed.disabled
    gate.collector.files[T] = cache.FileDeps(paths={T})
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=0, via="bundle", seconds=1.0))
    assert gate.store.load_green() == {}, "a -k run is not a whole-file green"


def test_a_named_file_a_known_red_and_an_old_generation_always_run(repo, store):
    _green(repo, store)
    assert _reason(repo, store, named=[repo / T]) == "named"
    assert _reason(repo, store, known_reds=[T]) == "known-red"
    store.bump_generation()
    assert _reason(repo, store) == "generation"


def test_a_green_outcome_writes_a_key_the_next_run_reads_back_as_a_hit(repo, store, tmp_path):
    gate = gate_mod.GateRun(repo, store, tmp_path / "deps")
    gate.keyer = _keyer(repo, store)
    gate.collector.files[T] = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    for via in ("rerun", "retry", "known-red"):
        gate.on_outcome(SimpleNamespace(file=repo / T, rc=0, via=via, seconds=1.0))
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=1, via="bundle", seconds=1.0))
    assert "key" not in store.load_green()[T] and _reason(repo, store) == "red", "only a first-attempt whole-file green is cached"
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=0, via="bundle", seconds=1.0))
    assert _reason(repo, store) == "hit"


# ── the store outlives the worktree (owner ruling Q6) ───────────────────────


def test_a_worktree_and_its_primary_share_one_store_and_the_run_record_lives_there(repo, tmp_path):
    worktree = tmp_path / "landing"
    _git(repo, "worktree", "add", "-q", "--detach", str(worktree))
    args = SimpleNamespace(no_cache=True, cache_dir=None, cache_dry_run=False)
    from_worktree = gate_mod.GateRun.start(args, worktree, [], [], [], environ={})
    from_primary = gate_mod.GateRun.start(args, repo, [], [], [], environ={})
    assert from_worktree.store.root.resolve() == from_primary.store.root.resolve()
    assert from_primary.store.root.resolve() == (repo / ".pytest_cache" / "hermes_gate").resolve()

    outcome = SimpleNamespace(file=worktree / T, rc=1)
    ledger = bundled.plan.RunLedger(failed={T: [f"{T}::test_ok"]}, file_seconds={T: 2.0, "tests/test_u.py": 3.0})
    green = SimpleNamespace(file=worktree / "tests/test_u.py", rc=0)
    from_worktree.record(SimpleNamespace(outcomes=[outcome, green], ledger=ledger, leaks=[]), {"elapsed": 1.0})
    again = gate_mod.GateRun.start(args, worktree, [], [], [], environ={})
    assert again.known_reds == {T: frozenset({f"{T}::test_ok"})}
    assert from_primary.store.load_durations() == {"tests/test_u.py": 3.0}


def test_the_store_durations_never_take_an_absolute_or_backslash_key(tmp_path):
    store = cache.GateStore(tmp_path / "s")
    store.save_durations({"tests/a.py": 1.0, "/tmp/pytest-of-x/probe.py": 2.0, "X:\\tmp\\p.py": 3.0, "tests\\b.py": 4.0})
    assert store.load_durations() == {"tests/a.py": 1.0}


# ── stage 3: skipping and the audit ─────────────────────────────────────────


def test_the_audit_samples_at_least_25_hits_and_its_seed_reproduces_the_sample():
    hits = [f"tests/test_{i:03d}.py" for i in range(100)]
    first = cache.audit_sample(hits, seed=7)
    assert len(first) >= 25 and set(first) <= set(hits)
    assert cache.audit_sample(list(reversed(hits)), seed=7) == first, "the printed seed must reproduce the sample"
    assert cache.audit_sample(hits, seed=8) != first
    many = [f"tests/test_{i:04d}.py" for i in range(2000)]
    assert len(cache.audit_sample(many, 1)) == 40  # 2 %
    assert len(cache.audit_sample(many, 1, cache.sample_fraction(0))) == 100  # 5 % for the first three runs
    assert cache.sample_fraction(3) == cache.SAMPLE_FRACTION
    assert cache.audit_sample(hits[:10], 1) == hits[:10], "fewer hits than the minimum: every hit runs"


def _gate_with_hits(repo: Path, store, tmp_path: Path, n: int) -> "gate_mod.GateRun":
    gate = gate_mod.GateRun(repo, store, tmp_path / "deps")
    gate.keyer = _keyer(repo, store)
    paths = [repo / f"tests/test_{i:03d}.py" for i in range(n)]
    entries = [cache.GreenEntry(cache.rel_of(p, repo), "k", "r0", "2026-10-09", 0.0, 2.0, 0) for p in paths]
    gate.decision = cache.CacheDecision(cached=list(zip(paths, entries)), reasons={cache.rel_of(p, repo): "hit" for p in paths})
    return gate


def test_a_run_skips_its_hits_but_the_sample_and_reports_the_skipped_as_cached(repo, store, tmp_path, capsys):
    gate = _gate_with_hits(repo, store, tmp_path, 100)
    files = [p for p, _e in gate.decision.cached] + [repo / T]
    gate._skip(files, seed=11)
    gate._print_decision(dry=False)
    assert len(gate.sampled) == 25 and len(gate.cached) == 75
    assert set(gate.to_run) == {repo / T} | {repo / rel for rel in gate.sampled}
    assert "seed 11" in capsys.readouterr().out

    seen = []
    gate.emit_cached(bundled.FileOutcome, seen.append)
    assert len(seen) == 75 and all(o.rc == 0 and o.via.startswith("cached") for o in seen)


def _audited(repo, store, tmp_path, monkeypatch, rc_alone: int):
    monkeypatch.setattr(gate_mod.rtp, "_FLAKY_RESULTS", [])
    gate = _gate_with_hits(repo, store, tmp_path, 1)
    _green(repo, store)
    gate.decision.cached = [(repo / T, cache.GreenEntry(T, "k", "r0", "2026-10-09", 0.0, 1.0, 0))]
    gate.sampled = [T]
    gate.rerun_alone = lambda rel: rc_alone
    red = bundled.FileOutcome(repo / T, 1, "FAILED tests/test_t.py::test_ok", {"failed": 1}, 1.0, "bundle", 0)
    result = SimpleNamespace(outcomes=[red], leaks=[], ledger=None)
    gate.audit(result)
    return gate, result


def test_a_sampled_hit_red_twice_is_a_cache_defect_that_fails_the_run_and_bumps_the_generation(
    repo, store, tmp_path, monkeypatch, capsys
):
    gate, result = _audited(repo, store, tmp_path, monkeypatch, rc_alone=1)
    assert gate.verdict.defects == [T] and not gate.verdict.flakes
    assert store.generation() == 1, "the next run must be cold"
    assert gate.report(result, 0) == 1
    out = capsys.readouterr().out
    assert "CACHE AUDIT: 1 cached-green file(s) red on re-execution" in out and T in out


def test_a_sampled_hit_red_then_green_alone_is_flaky_not_a_defect_and_loses_its_green(
    repo, store, tmp_path, monkeypatch, capsys
):
    gate, result = _audited(repo, store, tmp_path, monkeypatch, rc_alone=0)
    assert gate.verdict.flakes == [T] and not gate.verdict.defects
    assert result.outcomes[0].rc == 0 and result.outcomes[0].via == "audit-flaky"
    assert store.generation() == 0
    assert gate.report(result, 0) == 0
    assert "CACHE AUDIT" not in capsys.readouterr().out
    assert _reason(repo, store) == "flaky", "a flaky file is never cached on that green"


# ── stage 4: the never-cache classes and the max age ────────────────────────


def _writing_gate(repo: Path, store, tmp_path: Path) -> "gate_mod.GateRun":
    gate = gate_mod.GateRun(repo, store, tmp_path / "deps")
    gate.keyer = _keyer(repo, store)
    gate.collector.files[T] = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    return gate


def _green_outcome(repo: Path, via: str = "bundle", rc: int = 0):
    return SimpleNamespace(file=repo / T, rc=rc, via=via, seconds=1.0)


@pytest.mark.parametrize(
    "outcome_via, rc, reason",
    [("bundle", 1, "red"), ("retry", 0, "straggler"), ("rerun", 0, "rerun"), ("known-red", 1, "red")],
)
def test_a_red_a_straggler_retry_and_a_rerun_supersede_the_green_with_their_reason(
    repo, store, tmp_path, outcome_via, rc, reason
):
    gate = _writing_gate(repo, store, tmp_path)
    gate.on_outcome(_green_outcome(repo))
    assert _reason(repo, store) == "hit"
    gate.on_outcome(_green_outcome(repo, outcome_via, rc))
    assert _reason(repo, store) == reason


def test_a_flaky_green_is_never_cached_and_needs_two_greens_in_a_row_after(repo, store, tmp_path, monkeypatch):
    gate = _writing_gate(repo, store, tmp_path)
    monkeypatch.setattr(gate_mod.rtp, "_FLAKY_RESULTS", [(repo / T, "FLAKY")])
    gate.on_outcome(_green_outcome(repo, "solo"))
    assert _reason(repo, store) == "flaky"
    monkeypatch.setattr(gate_mod.rtp, "_FLAKY_RESULTS", [])
    gate.on_outcome(_green_outcome(repo))
    assert _reason(repo, store) == "probation", "one green after a flake is not enough"
    gate.on_outcome(_green_outcome(repo))
    assert _reason(repo, store) == "hit"


@pytest.mark.parametrize("kind", ["leak", "unreached"])
def test_an_isolation_leak_or_an_unreached_member_is_never_cached_on_this_runs_green(repo, store, tmp_path, kind):
    gate = _writing_gate(repo, store, tmp_path)
    gate.on_outcome(_green_outcome(repo))
    leak = bundled.Leak(repo / T, 0, [], {"failed": 1}, [f"{T}::test_ok"], kind)
    result = SimpleNamespace(outcomes=[bundled.FileOutcome(repo / T, 0, "", {}, 1.0, "bundle", 0)], leaks=[leak],
                             deaths=[], ledger=None)
    gate.record(result, {"elapsed": 1.0})
    assert _reason(repo, store) == kind


def test_a_member_behind_a_dead_bundle_is_unreached_and_misses(repo, store, tmp_path):
    gate = _writing_gate(repo, store, tmp_path)
    gate.on_outcome(_green_outcome(repo))
    death = bundled.Death(0, "tests/test_other.py", [T])
    gate.record(SimpleNamespace(outcomes=[], leaks=[], deaths=[death], ledger=None), {"elapsed": 1.0})
    assert _reason(repo, store) == "unreached"


def test_a_named_file_always_runs_with_its_reason_printed(repo, store, capsys):
    _green(repo, store)
    keyer = _keyer(repo, store)
    gate = gate_mod.GateRun(repo, store, None)
    gate.decision = cache.decide(
        [repo / T], repo, keyer=keyer, disabled="", deps=store.load_deps(), greens=store.load_green(),
        generation=0, named=[repo / T],
    )
    gate._print_decision(dry=True)
    assert gate.decision.run == [repo / T] and not gate.decision.cached
    assert f"would run: {T}  (named)" in capsys.readouterr().out


def test_a_green_older_than_the_max_age_misses(repo, store):
    _green(repo, store)
    keyer = _keyer(repo, store)

    def reason(days: float) -> str:
        return cache.decide(
            [repo / T], repo, keyer=keyer, disabled="", deps=store.load_deps(), greens=store.load_green(),
            generation=0, now=time.time() + days * 86400,
        ).reasons[T]

    assert reason(13) == "hit"
    assert reason(15) == "max-age", "owner ruling Q2: a 15-day-old green runs"


# ── stage 5 (1b): a recorded Python child retires the ALL sentinel ──────────


def test_a_spawner_whose_python_children_all_recorded_depends_only_on_its_records(repo, store):
    deps = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()}, spawn_py=2, child_records=2)
    _green(repo, store, deps)
    _write(repo, "pkg/other.py", "OTHER = 2\n")
    _commit(repo)
    assert _reason(repo, store) == "hit", "every child left a record: no whole-tree dependency"
    assert cache.uncovered_spawn(2, 0, 1) and cache.uncovered_spawn(1, 1, 5) and not cache.uncovered_spawn(0, 0, 0)


# ── the store stays bounded ─────────────────────────────────────────────────


def test_compaction_keeps_the_newest_line_per_file_and_only_the_module_sets_still_named(repo, store):
    _green(repo, store)
    old = cache.FileDeps(paths={T}, mods={"pkg/other.py"})
    store.write_deps({"tests/test_u.py": old}, "r0")
    _green(repo, store)  # a second line for T, same key
    store.write_deps({"tests/test_u.py": cache.FileDeps(paths={"tests/test_u.py"}, mods={"pkg/mod.py"})}, "r2")
    before_green, before_deps = store.load_green(), store.load_deps()
    assert len(store.load_modsets()) == 3

    assert store.compact(limit=1, modsets_limit=1) == ["green.jsonl", "deps.jsonl", "modsets.jsonl"]
    assert store.load_green() == before_green and store.load_deps() == before_deps
    assert len(store.green.read_text(encoding="utf-8").splitlines()) == 1
    assert len(store.deps.read_text(encoding="utf-8").splitlines()) == 2
    assert len(store.load_modsets()) == 2, "the set only the superseded line named is gone"
    assert _reason(repo, store) == "hit"
    assert store.compact() == [], "under the limits nothing is rewritten"
