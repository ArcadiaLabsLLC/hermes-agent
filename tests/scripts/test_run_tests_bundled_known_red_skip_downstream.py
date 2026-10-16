"""A known red whose file and recorded dependencies are unchanged since its red is not re-run.

Fork-hygiene row (owner 2026-10-16, "50 min gone is a lot"): the landing gate re-ran
every known red alone; 24 of them cost Σ 2,958 s on the Phase B gate. A red outcome
now writes the key it went red under (``scripts/run_tests_bundled_reds.py``, the
green cache's dependency record and ``Keyer``); the next run skips a known red whose
key is unchanged, reports it ``known-red, skipped`` and still counts it red.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_tests_bundled as bundled

cache = bundled.cache
gate_mod = bundled._gate
reds = bundled._reds
plan = bundled.plan
T = "tests/test_t.py"
IDS = [f"{T}::test_ok"]
_DEPS = dict(paths={T}, dirs=set(), mods={"pkg/__init__.py", "pkg/mod.py"})


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=fg", "-c", "user.email=fg@example.invalid", "commit", "-q", "-m", "c")


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for rel, text in {
        T: "def test_ok():\n    assert False\n", "pkg/__init__.py": "", "pkg/mod.py": "VALUE = 1\n",
        "pkg/other.py": "OTHER = 1\n", "uv.lock": "lock-1\n",
    }.items():
        _write(root, rel, text)
    _commit(root)
    return root


def _args(store_root: Path, **kw) -> SimpleNamespace:
    base = dict(no_cache=False, cache_dir=str(store_root), cache_dry_run=False, cache_reset=False, cache_seed=1,
                cache_max_age=None, file_timeout=None, rerun_known_reds=False)
    return SimpleNamespace(**{**base, **kw})


def _start(repo: Path, store_root: Path, roots=(), **kw) -> "gate_mod.GateRun":
    return gate_mod.GateRun.start(_args(store_root, **kw), repo, [repo / T], list(roots), [], environ={})


def _red_run(repo: Path, store_root: Path, rc: int = 1) -> "gate_mod.GateRun":
    """A run in which ``T`` went red: its outcome writes the red key, its record the red map."""

    gate = _start(repo, store_root)
    gate.collector.files[T] = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=rc, via="bundle", seconds=1.0))
    ledger = plan.RunLedger(failed={T: IDS} if rc == 1 else {})
    timed_out = [T] if rc == 124 else []
    gate.record(SimpleNamespace(outcomes=[bundled.FileOutcome(repo / T, rc, "", {}, 1.0, "bundle")], leaks=[],
                                ledger=ledger), {"elapsed": 1.0}, timed_out=timed_out)
    return gate


def test_an_unchanged_known_red_is_skipped_reported_red_and_stays_a_known_red(repo, tmp_path, capsys):
    store_root = tmp_path / "store"
    _red_run(repo, store_root)

    gate = _start(repo, store_root)
    assert gate.to_run == [] and gate.red_decision.reasons == {T: "unchanged"}
    assert "Known reds: 1 of 1 skipped" in capsys.readouterr().out
    seen = []
    gate.emit_cached(bundled.FileOutcome, seen.append)
    assert [(o.rc, o.via, o.summary) for o in seen] == [(1, "known-red, skipped", {"failed": 1})]
    assert IDS[0] in seen[0].output

    result = SimpleNamespace(outcomes=[], leaks=[], ledger=plan.RunLedger())
    gate.record(result, {"elapsed": 0.0})
    assert [o.via for o in result.outcomes] == ["known-red, skipped"], "the Summary lists it red"
    assert plan.load_known_reds(repo, record_path=gate.store.runs) == {T: frozenset(IDS)}
    assert _start(repo, store_root).to_run == [], "the carried-forward red is skipped again"


@pytest.mark.parametrize("rel", [T, "pkg/mod.py"])
def test_a_known_red_whose_file_or_a_recorded_dependency_changed_runs(repo, tmp_path, rel):
    store_root = tmp_path / "store"
    _red_run(repo, store_root)
    _write(repo, "pkg/other.py", "OTHER = 2\n")  # not a recorded dependency
    _commit(repo)
    assert _start(repo, store_root).to_run == []

    _write(repo, rel, (repo / rel).read_text(encoding="utf-8") + "# edited\n")
    gate = _start(repo, store_root)
    assert gate.to_run == [repo / T] and gate.red_decision.reasons == {T: "changed"}


def test_the_opt_out_a_named_file_and_a_new_generation_run_the_known_red(repo, tmp_path):
    store_root = tmp_path / "store"
    _red_run(repo, store_root)
    assert _start(repo, store_root, rerun_known_reds=True).to_run == [repo / T]
    assert _start(repo, store_root, cache_dry_run=True).to_run == [repo / T]
    named = _start(repo, store_root, roots=[repo / T])
    assert named.to_run == [repo / T] and named.red_decision.reasons == {T: "named"}
    gate = _start(repo, store_root, cache_reset=True)
    assert gate.to_run == [repo / T] and gate.red_decision.reasons == {T: "generation"}


def test_a_timed_out_known_red_is_skipped_on_its_key_too(repo, tmp_path):
    store_root = tmp_path / "store"
    _red_run(repo, store_root, rc=124)
    gate = _start(repo, store_root)
    assert gate.timed_out == {T} and gate.to_run == []


def test_a_red_with_no_dependency_record_or_a_green_drops_the_key(repo, tmp_path):
    store_root = tmp_path / "store"
    _red_run(repo, store_root)
    gate = _start(repo, store_root)
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=1, via="known-red", seconds=1.0))  # no record this time
    assert reds.load(gate.store)[T] == {"f": T, "drop": "no-deps", "run": gate.run_id}
    assert _start(repo, store_root).red_decision.reasons == {T: "no-deps"}

    _red_run(repo, store_root)
    gate = _start(repo, store_root, rerun_known_reds=True)
    gate.collector.files[T] = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=0, via="known-red", seconds=1.0))
    assert reds.load(gate.store)[T]["drop"] == "green"


def test_a_red_key_older_than_the_max_age_runs(repo, tmp_path):
    store_root = tmp_path / "store"
    _red_run(repo, store_root)
    gate = _start(repo, store_root, cache_max_age=1e-9)
    assert gate.to_run == [repo / T] and gate.red_decision.reasons == {T: "max-age"}


def test_the_skip_lists_deselects_are_keyed_and_never_turn_the_cache_off(repo):
    """Every gate passes the skip list's node rows as ``--deselect``: as plain passthrough
    args they turned the cache, and so this skip, off on every run (gate-pb2.log)."""

    snap = cache.TreeSnapshot.take(repo, bundled.scope._scope_git)
    deselect = ["--deselect", "tests/x.py::test_flaky"]

    def collect(args, keyed=()):
        return cache.FixedInputs.collect(snap, args, {}, interp=["interp\tpinned"], keyed_args=keyed)

    assert collect(["-q", *deselect], deselect).disabled == ""
    assert collect(deselect, deselect).digest != collect([]).digest, "the deselects are in the key"
    assert collect(["-k", "x", *deselect], deselect).disabled == "pytest args -k x"
    assert collect(deselect).disabled, "a deselect the runner did not append still turns the cache off"


_KILLED = '''
import os
import helper_mod

def test_killed():
    os._exit(3)  # what pytest-timeout's thread method does: no sessionfinish, no deps line
'''


@pytest.mark.timeout(150)
def test_a_process_killed_mid_file_leaves_a_partial_record_the_red_key_uses(repo, tmp_path):
    """A timeout kills the process before its ``deps`` line: the collection-time
    ``partial`` line is then the record (gate e2e, test_changed_line_mutation_check)."""

    import os
    import sys

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "helper_mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (proj / "test_k.py").write_text(_KILLED, encoding="utf-8")
    plugin = Path(bundled.__file__).resolve().parent / "_bundle_plugin"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(plugin), str(proj)])}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "hermes_dep_record",
         f"--hermes-gate-deps={tmp_path / 'deps'}", "test_k.py"],
        cwd=proj, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    collector = cache.DepsCollector(tmp_path / "deps")
    assert "test_k.py" not in collector.poll()
    assert {"test_k.py", "helper_mod.py"} <= collector.partial["test_k.py"].paths | collector.partial["test_k.py"].mods

    store_root = tmp_path / "store"
    gate = _start(repo, store_root)
    gate.collector.partial[T] = cache.FileDeps(**{k: set(v) for k, v in _DEPS.items()})
    gate.on_outcome(SimpleNamespace(file=repo / T, rc=124, via="known-red", seconds=300.0))
    assert reds.load(gate.store)[T].get("key"), "the killed red is keyed by its partial record"
