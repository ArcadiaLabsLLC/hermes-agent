"""The green-result cache wired into the bundled runner (fast-gate §1).

``scripts/run_tests_bundled.py::main`` makes one :class:`GateRun` per run. It

* reads the gate store (``scripts/run_tests_bundled_cache.py``), keys every
  selected file against the tree the run starts from and decides, per file,
  whether it is a cached green or a miss and why;
* adds the dependency recorder to every pytest process the run spawns, and as
  each file comes back green writes its record and its key to the store;
* writes the run record and the clean-pass durations to the STORE (the primary
  checkout's, owner ruling Q6), so they outlive a landing worktree.

Loaded by the runner's ``_load_sibling`` after its siblings, so the plain
imports below resolve to the modules it already loaded (``scripts/`` is not a
package; run as a script, it is ``sys.path[0]``).

Opt-out: ``--no-cache`` or ``HERMES_GATE_CACHE=0`` — no recorder, no green
reads or writes (the run record and durations still go to the store).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence

import run_tests_bundled_cache as cache  # noqa: E402 — registered by run_tests_bundled._load_sibling
import run_tests_bundled_plan as plan  # noqa: E402
import run_tests_bundled_scope as scope  # noqa: E402
import run_tests_parallel as rtp  # noqa: E402

FLAGS = frozenset({"--no-cache", "--cache-dir", "--cache-dry-run"})
CACHE_ENV = "HERMES_GATE_CACHE"
PLUGIN_NAME = "hermes_dep_record"
_PLUGIN_DIR = Path(__file__).resolve().parent / "_bundle_plugin"
#: a via whose green is a first-attempt whole-file pass (not a re-run, a retry or a known red)
GREEN_VIAS = frozenset({"bundle", "solo"})
_LISTED_HITS = 50


def add_arguments(parser) -> None:
    parser.add_argument(
        "--no-cache", action="store_true",
        help="green-result cache off for this run: no dependency recording, no cached skips (or HERMES_GATE_CACHE=0)",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help=f"the gate store (default <primary checkout>/{cache.STORE_SUBDIR.as_posix()}, or ${cache.STORE_ENV})",
    )
    parser.add_argument(
        "--cache-dry-run", action="store_true",
        help="list every file the cache would skip and why the rest would run; run everything",
    )


class GateRun:
    """One run's side of the cache."""

    def __init__(self, repo_root: Path, store: "cache.GateStore", deps_dir: Optional[Path]) -> None:
        self.repo_root = Path(repo_root)
        self.store = store
        self.enabled = deps_dir is not None
        self.deps_dir = deps_dir
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self.collector = cache.DepsCollector(deps_dir) if deps_dir is not None else None
        self.keyer: Optional["cache.Keyer"] = None
        self.disabled = "" if self.enabled else "--no-cache"
        self.decision: Optional["cache.CacheDecision"] = None
        self.known_reds: Dict[str, frozenset] = {}
        self.to_run: list = []
        self.generation = 0
        self.greens_written = 0
        self._deps_written: set = set()
        self._lock = threading.Lock()

    @classmethod
    def start(
        cls, args, repo_root: Path, files: Sequence[Path], roots: Sequence[Path], pytest_args: Sequence[str],
        environ: Mapping[str, str] = os.environ,
    ) -> "GateRun":
        enabled = not getattr(args, "no_cache", False) and environ.get(CACHE_ENV, "1") != "0"
        override = getattr(args, "cache_dir", None) or environ.get(cache.STORE_ENV)
        store = cache.GateStore(cache.gate_store_dir(repo_root, plan.primary_checkout(repo_root), override))
        gate = cls(repo_root, store, Path(tempfile.mkdtemp(prefix="gate-deps-")) if enabled else None)
        runs = store.runs if store.runs.is_file() else None
        gate.known_reds = plan.load_known_reds(repo_root, record_path=runs) if runs else plan.load_known_reds(repo_root)
        gate.to_run = list(files)
        if enabled:
            gate._decide(files, [r for r in roots if Path(r).is_file()], pytest_args, environ)
            gate._print_decision(getattr(args, "cache_dry_run", False))
        return gate

    def _decide(self, files, named, pytest_args, environ) -> None:
        try:
            snapshot = cache.TreeSnapshot.take(self.repo_root, scope._scope_git)
        except (OSError, RuntimeError) as exc:
            self.disabled = f"git: {exc}"
            snapshot = None
        if snapshot is not None:
            fixed = cache.FixedInputs.collect(snapshot, pytest_args, environ, strip_paths=[_PLUGIN_DIR])
            self.disabled = fixed.disabled
            deps = self.store.load_deps()
            modsets = self.store.load_modsets({d for entry in deps.values() for d in entry.mods})
            self.keyer = cache.Keyer(snapshot, fixed, modsets)
            self.generation = self.store.generation()
        else:
            deps = {}
        self.decision = cache.decide(
            files, self.repo_root, keyer=self.keyer, disabled=self.disabled, deps=deps,
            greens=self.store.load_green() if self.keyer is not None else {}, generation=self.generation,
            named=named, known_reds=self.known_reds,
        )

    def _print_decision(self, listing: bool) -> None:
        d = self.decision
        misses = ", ".join(f"{reason} {n}" for reason, n in d.misses_by_reason().most_common()) or "none"
        print(
            f"Green-result cache (dry run, nothing skipped): {len(d.cached)} of {len(d.reasons)} file(s) "
            f"would be skipped; misses: {misses}; keys in {d.seconds:.1f}s; store {self.store.root}",
            flush=True,
        )
        if listing:
            for path, entry in d.cached[:_LISTED_HITS]:
                print(f"  would skip: {cache.rel_of(path, self.repo_root)}  (green {entry.t}, {entry.seconds:.1f}s)")
            if len(d.cached) > _LISTED_HITS:
                print(f"  … and {len(d.cached) - _LISTED_HITS} more")

    @property
    def plugin_args(self) -> list:
        if not self.enabled:
            return []
        return ["-p", PLUGIN_NAME, f"--hermes-gate-deps={self.deps_dir}"]

    @property
    def writes(self) -> bool:
        return self.enabled and self.keyer is not None and not self.disabled

    def durations(self, legacy_load) -> Dict[str, float]:
        """The planner's durations: the store's, over the legacy per-checkout files."""

        legacy = plan.load_durations_with_primary(self.repo_root, legacy_load)
        return {**legacy, **{str(Path(rel)): s for rel, s in self.store.load_durations().items()}}

    # ── as the run goes ──

    def chain(self, on_outcome: Callable) -> Callable:
        def _both(outcome) -> None:
            on_outcome(outcome)
            self.on_outcome(outcome)

        return _both

    def on_outcome(self, outcome) -> None:
        """A first-attempt whole-file green writes the file's record and key now,
        so a killed run keeps the greens it reached."""

        if not self.writes or outcome.rc != 0 or outcome.via not in GREEN_VIAS:
            return
        if any(Path(p) == Path(outcome.file) for p, _out in rtp._FLAKY_RESULTS):
            return
        rel = cache.rel_of(outcome.file, self.repo_root)
        with self._lock:
            deps = self.collector.poll().get(rel)
            if deps is None:
                return  # no record, no key: the file is a miss next time
            key = self.keyer.key_fresh(rel, deps)
            self.store.write_deps({rel: deps}, self.run_id)
            self._deps_written.add(rel)
            now = time.time()
            entry = cache.GreenEntry(rel, key, self.run_id, time.strftime("%Y-%m-%d", time.localtime(now)), now,
                                     float(outcome.seconds), self.generation)
            self.store.append_green([entry.line()])
            self.greens_written += 1

    # ── after the run ──

    def record(self, result, cost: Mapping[str, object]) -> None:
        """The run record and the clean-pass durations, into the store."""

        final_rc = {cache.rel_of(o.file, self.repo_root): o.rc for o in result.outcomes}
        failed = result.ledger.failed if result.ledger is not None else {}
        plan.record_run(self.repo_root, cost, final_rc, failed, self.known_reds, record_path=self.store.runs)
        skip = {cache.rel_of(p, self.repo_root) for p, _out in rtp._FLAKY_RESULTS}
        skip |= {cache.rel_of(leak.file, self.repo_root) for leak in result.leaks}
        seconds = result.ledger.file_seconds if result.ledger is not None else {}
        clean = {rel: s for rel, s in seconds.items() if final_rc.get(rel) == 0 and rel not in skip}
        if clean:
            self.store.save_durations(clean)
            print(f"  Durations cached to {self.store.durations} ({len(clean)} files)")

    def report(self, result, rc: int) -> int:
        """After the Summary: the remaining dependency records, the census and
        the cache line. Returns the run's exit code."""

        if not self.enabled or self.collector is None:
            print("  green-result cache: off (--no-cache / HERMES_GATE_CACHE=0)")
            return rc
        entries = self.collector.poll()
        rest = {rel: deps for rel, deps in entries.items() if rel not in self._deps_written}
        self.store.write_deps(rest, self.run_id)
        seconds = result.ledger.file_seconds if result.ledger is not None else {}
        print(cache.census(entries, seconds))
        state = f"off ({self.disabled})" if self.disabled else f"{self.greens_written} green(s) written"
        print(f"  green-result cache: {state}; store {self.store.root}")
        shutil.rmtree(self.deps_dir, ignore_errors=True)
        return rc
