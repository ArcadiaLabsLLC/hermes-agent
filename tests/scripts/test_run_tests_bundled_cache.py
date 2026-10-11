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
    assert store.load_green() == {}, "only a first-attempt whole-file green is cached"
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
    ledger = SimpleNamespace(failed={T: [f"{T}::test_ok"]}, file_seconds={T: 2.0, "tests/test_u.py": 3.0})
    green = SimpleNamespace(file=worktree / "tests/test_u.py", rc=0)
    from_worktree.record(SimpleNamespace(outcomes=[outcome, green], ledger=ledger, leaks=[]), {"elapsed": 1.0})
    again = gate_mod.GateRun.start(args, worktree, [], [], [], environ={})
    assert again.known_reds == {T: frozenset({f"{T}::test_ok"})}
    assert from_primary.store.load_durations() == {"tests/test_u.py": 3.0}


def test_the_store_durations_never_take_an_absolute_or_backslash_key(tmp_path):
    store = cache.GateStore(tmp_path / "s")
    store.save_durations({"tests/a.py": 1.0, "/tmp/pytest-of-x/probe.py": 2.0, "X:\\tmp\\p.py": 3.0, "tests\\b.py": 4.0})
    assert store.load_durations() == {"tests/a.py": 1.0}
