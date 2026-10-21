"""The green-result cache wired into the bundled runner (fast-gate §1).

``scripts/run_tests_bundled.py::main`` makes one :class:`GateRun` per run. It

* reads the gate store (``scripts/run_tests_bundled_cache.py``), keys every
  selected file against the tree the run starts from and decides, per file,
  whether it is a cached green (skipped) or a miss, and why;
* re-executes an audit sample of the hits as ordinary members; a sampled hit
  red in the run AND red again alone is a CACHE DEFECT: the run exits 1 and the
  store's generation is bumped, so the next run is cold;
* adds the dependency recorder to every pytest process the run spawns, and as
  each file comes back green writes its record and its key to the store;
* writes the run record and the clean-pass durations to the STORE (the primary
  checkout's, owner ruling Q6), so they outlive a landing worktree.

Loaded by the runner's ``_load_sibling`` after its siblings, so the plain
imports below resolve to the modules it already loaded (``scripts/`` is not a
package; run as a script, it is ``sys.path[0]``).

Opt-out: ``--no-cache`` or ``HERMES_GATE_CACHE=0`` — no recorder, no skips, no
green reads or writes (the run record and durations still go to the store).
``--cache-dry-run`` keys and reports but skips nothing.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

import run_tests_bundled_cache as cache  # registered by run_tests_bundled._load_sibling
import run_tests_bundled_fixtures as fixtures
import run_tests_bundled_plan as plan
import run_tests_bundled_reds as reds
import run_tests_bundled_scope as scope
import run_tests_bundled_via as vias
import run_tests_parallel as rtp

FLAGS = frozenset({
    "--no-cache", "--cache-dir", "--cache-dry-run", "--cache-reset", "--cache-seed", "--cache-max-age", "--rerun-known-reds",
})
CACHE_ENV = "HERMES_GATE_CACHE"
PLUGIN_NAME = "hermes_dep_record"
_PLUGIN_DIR = Path(__file__).resolve().parent / "_bundle_plugin"
#: a via whose green is a first-attempt whole-file pass (not a re-run, a retry or a known red)
GREEN_VIAS = frozenset({vias.ViaKind.BUNDLE, vias.ViaKind.SOLO})
#: a via whose outcome is never cached, and the reason its next run prints
NEVER_CACHED_VIAS = {vias.ViaKind.RETRY: "straggler", vias.ViaKind.RERUN: "rerun"}
_LISTED = 50


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
    parser.add_argument("--cache-reset", action="store_true", help="bump the store's generation: every green misses")
    parser.add_argument("--cache-seed", type=int, default=None, help="the audit sample's seed (default: from the clock)")
    parser.add_argument(
        "--cache-max-age", type=float, default=cache.DEFAULT_MAX_AGE_DAYS, metavar="DAYS",
        help=f"a green older than this misses (default {cache.DEFAULT_MAX_AGE_DAYS:g}, owner ruling Q2)",
    )
    parser.add_argument(
        "--rerun-known-reds", action="store_true",
        help="run every known red, even one whose file and recorded dependencies are unchanged since its red",
    )


class GateRun:
    """One run's side of the cache."""

    def __init__(self, repo_root: Path, store: cache.GateStore, deps_dir: Optional[Path]) -> None:
        self.repo_root = Path(repo_root)
        self.store = store
        self.enabled = deps_dir is not None
        self.deps_dir = deps_dir
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self.collector = cache.DepsCollector(deps_dir) if deps_dir is not None else None
        self.keyer: Optional[cache.Keyer] = None
        self.disabled = "" if self.enabled else "--no-cache"
        self.decision: Optional[cache.CacheDecision] = None
        self.known_reds: dict[str, frozenset] = {}
        self.timed_out: frozenset = frozenset()
        self.to_run: list = []
        self.cached: list = []  # (path, GreenEntry) skipped this run
        self.sampled: list[str] = []
        self.seed: Optional[int] = None
        self.fraction = cache.SAMPLE_FRACTION
        self.verdict = cache.AuditVerdict()
        self.generation = 0
        self.greens_written = 0
        self.pytest_args: list[str] = []
        self.file_timeout = float(rtp._DEFAULT_FILE_TIMEOUT_SECONDS)
        #: rel → rc of one more run alone (the audit's second run); tests inject a fake
        self.rerun_alone: Optional[Callable[[str], int]] = None
        self.max_age_days = cache.DEFAULT_MAX_AGE_DAYS
        self.greens: dict[str, dict] = {}  # each file's newest green.jsonl line, as the run read it
        self.deps: dict[str, cache.StoredDeps] = {}
        self.reds: dict[str, dict] = {}  # each file's newest red.jsonl line, as the run read it
        self.red_decision: Optional[reds.RedDecision] = None
        self.red_outcomes: list = []  # known reds skipped this run, reported red without a process
        self._deps_written: set = set()
        self._lock = threading.Lock()

    @classmethod
    def start(
        cls, args, repo_root: Path, files: Sequence[Path], roots: Sequence[Path], pytest_args: Sequence[str],
        environ: Mapping[str, str] = os.environ, keyed_args: Sequence[str] = (),
    ) -> GateRun:
        enabled = not getattr(args, "no_cache", False) and environ.get(CACHE_ENV, "1") != "0"
        override = getattr(args, "cache_dir", None) or environ.get(cache.STORE_ENV)
        store = cache.GateStore(cache.gate_store_dir(repo_root, plan.primary_checkout(repo_root), override))
        gate = cls(repo_root, store, Path(tempfile.mkdtemp(prefix="gate-deps-")) if enabled else None)
        gate.pytest_args = list(pytest_args)
        gate.file_timeout = float(getattr(args, "file_timeout", None) or gate.file_timeout)
        gate.max_age_days = float(getattr(args, "cache_max_age", None) or cache.DEFAULT_MAX_AGE_DAYS)
        runs = store.runs if store.runs.is_file() else None  # else the legacy per-checkout record
        gate.known_reds = plan.load_known_reds(repo_root, record_path=runs)
        gate.timed_out = plan.load_timed_out(repo_root, record_path=runs)
        gate.to_run = list(files)
        if getattr(args, "cache_reset", False):
            print(f"Green-result cache: --cache-reset, generation now {store.bump_generation()}", flush=True)
        if enabled:
            gate._decide(files, [r for r in roots if Path(r).is_file()], pytest_args, environ, keyed_args)
            dry = getattr(args, "cache_dry_run", False)
            if not dry and gate.writes:
                gate._skip(files, getattr(args, "cache_seed", None))
                if not getattr(args, "rerun_known_reds", False):
                    gate._skip_reds([r for r in roots if Path(r).is_file()])
            gate._print_decision(dry)
        return gate

    def _decide(self, files, named, pytest_args, environ, keyed_args=()) -> None:
        try:
            snapshot = cache.TreeSnapshot.take(self.repo_root, scope._scope_git)
        except (OSError, RuntimeError) as exc:
            self.disabled = f"git: {exc}"
            snapshot = None
        if snapshot is not None:
            fixed = cache.FixedInputs.collect(
                snapshot, pytest_args, environ, strip_paths=[_PLUGIN_DIR], keyed_args=keyed_args,
            )
            self.disabled = fixed.disabled
            deps = self.store.load_deps()
            modsets = self.store.load_modsets({d for entry in deps.values() for d in entry.digests})
            shapes = fixtures.Fingerprints(self.repo_root, snapshot.blob, cache.git_blob_id)
            self.keyer = cache.Keyer(snapshot, fixed, modsets, shapes)
            self.generation = self.store.generation()
            self.greens = self.store.load_green()
            self.deps, self.reds = deps, reds.load(self.store)
        else:
            deps = {}
        self.decision = cache.decide(
            files, self.repo_root, keyer=self.keyer, disabled=self.disabled, deps=deps,
            greens=self.greens, generation=self.generation, named=named,
            known_reds=set(self.known_reds) | set(self.timed_out), max_age_days=self.max_age_days,
        )

    def _skip(self, files: Sequence[Path], seed: Optional[int]) -> None:
        """Skip the hits but an audit sample, which runs as ordinary members."""

        hits = {cache.rel_of(path, self.repo_root): (path, entry) for path, entry in self.decision.cached}
        self.seed = seed if seed is not None else int(time.time() * 1000) % (1 << 31)
        self.fraction = cache.sample_fraction(self.store.skip_runs())
        self.sampled = cache.audit_sample(list(hits), self.seed, self.fraction)
        sampled = set(self.sampled)
        self.decision.sampled = [hits[rel][0] for rel in self.sampled]
        self.cached = [hit for rel, hit in sorted(hits.items()) if rel not in sampled]
        skipped = {cache.rel_of(path, self.repo_root) for path, _entry in self.cached}
        self.to_run = [path for path in files if cache.rel_of(path, self.repo_root) not in skipped]

    def _skip_reds(self, named) -> None:
        """Take the known reds whose key is unchanged since their red out of the run."""

        self.red_decision = reds.decide(
            self.to_run, self.repo_root, keyer=self.keyer, known=set(self.known_reds) | set(self.timed_out),
            deps=self.deps, reds=self.reds, generation=self.generation, named=named, max_age_days=self.max_age_days,
        )
        skipped = {cache.rel_of(path, self.repo_root) for path, _line in self.red_decision.skipped}
        self.to_run = [path for path in self.to_run if cache.rel_of(path, self.repo_root) not in skipped]

    def _print_decision(self, dry: bool) -> None:
        if self.red_decision is not None and self.red_decision.reasons:
            print(self.red_decision.line(), flush=True)
        d = self.decision
        misses = ", ".join(f"{reason} {n}" for reason, n in d.misses_by_reason().most_common()) or "none"
        tail = f"misses: {misses}; keys in {d.seconds:.1f}s; store {self.store.root}"
        if self.seed is not None:
            print(
                f"Green-result cache: {len(self.cached)} of {len(d.reasons)} file(s) skipped as cached green; "
                f"audit re-runs {len(self.sampled)} hit(s) (seed {self.seed}, {self.fraction:.0%}, "
                f"min {cache.SAMPLE_MINIMUM}); {tail}",
                flush=True,
            )
            return
        state = f"off: {self.disabled}" if self.disabled else "dry run, nothing skipped"
        print(f"Green-result cache ({state}): {len(d.cached)} of {len(d.reasons)} file(s) would be skipped; {tail}",
              flush=True)
        if dry:
            for path, entry in d.cached[:_LISTED]:
                print(f"  would skip: {cache.rel_of(path, self.repo_root)}  (green {entry.t}, {entry.seconds:.1f}s)")
            if len(d.cached) > _LISTED:
                print(f"  … and {len(d.cached) - _LISTED} more")
            runs = [(rel, why) for rel, why in sorted(d.reasons.items()) if why not in ("hit", "no-green")]
            for rel, why in runs[:_LISTED]:
                print(f"  would run: {rel}  ({why})")

    @property
    def plugin_args(self) -> list:
        if not self.enabled:
            return []
        return ["-p", PLUGIN_NAME, f"--hermes-gate-deps={self.deps_dir}"]

    @property
    def writes(self) -> bool:
        return self.enabled and self.keyer is not None and not self.disabled

    def durations(self, legacy_load) -> dict[str, float]:
        """The planner's durations: the store's, over the legacy per-checkout files."""

        legacy = plan.load_durations_with_primary(self.repo_root, legacy_load)
        return {**legacy, **{str(Path(rel)): s for rel, s in self.store.load_durations().items()}}

    # ── as the run goes ──

    def emit_cached(self, outcome_type, on_outcome: Callable) -> None:
        """Report every skipped file without a process: a cached green as passed, a
        known red whose key is unchanged as red (``record`` adds those to the result)."""

        for path, entry in self.cached:
            note = f"cached green {entry.t} ({entry.seconds:.1f}s, run {entry.run}); key unchanged, not run"
            on_outcome(outcome_type(path, 0, note, {}, 0.0, vias.Via.cached(f"green {entry.t} {entry.seconds:.1f}s"), None))
        for path, line in self.red_decision.skipped if self.red_decision is not None else ():
            ids = sorted(self.known_reds.get(cache.rel_of(path, self.repo_root), ()))
            outcome = outcome_type(path, 1, reds.note(line, ids), {"failed": len(ids)} if ids else {},
                                   0.0, reds.SKIPPED_VIA, None)
            self.red_outcomes.append(outcome)
            on_outcome(outcome)

    def chain(self, on_outcome: Callable) -> Callable:
        def _both(outcome) -> None:
            on_outcome(outcome)
            self.on_outcome(outcome)

        return _both

    def _never_cached(self, outcome) -> str:
        """Why this outcome may not be cached ("" when it may)."""

        if outcome.rc != 0:
            return "red"
        if any(Path(p) == Path(outcome.file) for p, _out in rtp._FLAKY_RESULTS):
            return "flaky"
        kind = vias.kind_of(outcome.via)
        if kind in GREEN_VIAS:
            return ""
        return NEVER_CACHED_VIAS.get(kind, f"via {outcome.via}")

    def on_outcome(self, outcome) -> None:
        """A first-attempt whole-file green writes the file's record and key now,
        so a killed run keeps the greens it reached; any other outcome supersedes
        the file's green with the reason it may not be cached."""

        if not self.writes:
            return
        rel = cache.rel_of(outcome.file, self.repo_root)
        why = self._never_cached(outcome)
        if why:
            with self._lock:
                self.store.drop_green([rel], why, self.run_id)
                self.greens[rel] = {"f": rel, "drop": why}
                self._red_key(rel, outcome.rc)
            return
        with self._lock:
            deps = self.collector.poll().get(rel)
            if deps is None:
                return  # no record, no key: the file is a miss next time
            key = self.keyer.key_fresh(rel, deps)
            self.store.write_deps({rel: deps}, self.run_id)
            self._deps_written.add(rel)
            now = time.time()
            streak, needs = cache.streak_after(self.greens.get(rel))
            entry = cache.GreenEntry(rel, key, self.run_id, time.strftime("%Y-%m-%d", time.localtime(now)), now,
                                     float(outcome.seconds), self.generation, self.keyer.snapshot.head, streak, needs)
            self.store.append_green([entry.line()])
            self.greens[rel] = entry.line()
            self.greens_written += 1
            self._red_key(rel, 0)

    def _red_key(self, rel: str, rc: int) -> None:
        """A red writes the key it went red under (its dependency record now, or the
        collection-time ``partial`` record of a process killed mid-file); a red with
        no record, or a green after a keyed red, drops the file's red key."""

        deps = (self.collector.poll().get(rel) or self.collector.partial.get(rel)) if rc != 0 else None
        if deps is None:
            if (self.reds.get(rel) or {}).get("key"):
                why = "green" if rc == 0 else "no-deps"
                reds.drop(self.store, rel, why, self.run_id)
                self.reds[rel] = {"f": rel, "drop": why}
            return
        self.store.write_deps({rel: deps}, self.run_id)
        self._deps_written.add(rel)
        reds.write_key(self.store, rel, self.keyer.key_fresh(rel, deps), self.run_id, self.generation)

    # ── after the run ──

    def _rerun(self, rel: str) -> int:
        if self.rerun_alone is not None:
            return self.rerun_alone(rel)
        _f, rc, _out, _summary, _wall = rtp._run_one_file_once(
            self.repo_root / rel, list(self.pytest_args), self.repo_root, self.file_timeout
        )
        return rc

    def audit(self, result) -> None:
        """The sampled hits' verdict: red twice is a cache defect (generation
        bumped, the run exits 1); red then green alone is a flake (its outcome
        turns FLAKY-green and its green entry is dropped)."""

        if not self.sampled:
            return
        last = {cache.rel_of(o.file, self.repo_root): (i, o) for i, o in enumerate(result.outcomes)}
        final_rc = {rel: o.rc for rel, (_i, o) in last.items()}
        self.verdict = cache.audit_verdict(self.sampled, final_rc, self._rerun)
        for rel in self.verdict.flakes:
            index, outcome = last[rel]
            banner = "⚠ FLAKY (cache audit): red in the run, green alone. Fix the flake — do not ignore this.\n"
            result.outcomes[index] = type(outcome)(
                outcome.file, 0, banner + outcome.output, outcome.summary, outcome.seconds, vias.AUDIT_FLAKY,
                outcome.bundle_index,
            )
            rtp._FLAKY_RESULTS.append((outcome.file, banner + outcome.output))
        self.store.drop_green(self.verdict.flakes, "flaky", self.run_id)
        if self.verdict.defects:
            self.store.drop_green(self.verdict.defects, "audit-defect", self.run_id)
            self.generation = self.store.bump_generation()

    def record(
        self, result, cost: dict[str, object], *, timed_out=(), extra: Optional[Mapping[str, object]] = None
    ) -> None:
        """The audit, then the run record and the clean-pass durations, into the store."""

        self.audit(result)
        if self.writes:  # a leak or an unreached member is never cached on this run's green
            dead = [(self.repo_root / rel, "unreached") for death in getattr(result, "deaths", []) for rel in death.unreached]
            for path, kind in [(leak.file, leak.kind) for leak in result.leaks] + dead:
                self.store.drop_green([cache.rel_of(path, self.repo_root)], kind, self.run_id)
        if self.decision is not None:
            cost["cache"] = {
                "skipped": len(self.cached), "sampled": len(self.sampled), "seed": self.seed,
                "fraction": self.fraction, "misses": dict(self.decision.misses_by_reason()),
                "keys_seconds": round(self.decision.seconds, 2),
                "defects": self.verdict.defects, "flakes": self.verdict.flakes,
                "known_red_skipped": len(self.red_outcomes),
            }
        final_rc = {cache.rel_of(o.file, self.repo_root): o.rc for o in result.outcomes}
        failed = result.ledger.failed if result.ledger is not None else {}
        diagnostics = result.ledger.diagnostic_record() if result.ledger is not None else {}
        plan.record_run(
            self.repo_root, cost, final_rc, failed, self.known_reds, timed_out=timed_out,
            previous_timed_out=self.timed_out, extra={**(extra or {}), **diagnostics}, record_path=self.store.runs,
        )  # a skipped known red is absent from final_rc, so its red and timed-out entries carry forward
        result.outcomes.extend(self.red_outcomes)  # ... and the Summary still lists it red
        skip = {cache.rel_of(p, self.repo_root) for p, _out in rtp._FLAKY_RESULTS}
        skip |= {cache.rel_of(leak.file, self.repo_root) for leak in result.leaks}
        seconds = result.ledger.file_seconds if result.ledger is not None else {}
        clean = {rel: s for rel, s in seconds.items() if final_rc.get(rel) == 0 and rel not in skip}
        if clean:
            self.store.save_durations(clean)
            print(f"  Durations cached to {self.store.durations} ({len(clean)} files)")

    def report(self, result, rc: int) -> int:
        """After the Summary: the remaining dependency records, the census, the
        cache line and the audit. Returns the run's exit code (1 on a defect)."""

        if not self.enabled or self.collector is None:
            print("  green-result cache: off (--no-cache / HERMES_GATE_CACHE=0)")
            return rc
        entries = self.collector.poll()
        rest = {rel: deps for rel, deps in entries.items() if rel not in self._deps_written}
        self.store.write_deps(rest, self.run_id)
        seconds = result.ledger.file_seconds if result.ledger is not None else {}
        print(cache.census(entries, seconds))
        state = f"off ({self.disabled})" if self.disabled else (
            f"{len(self.cached)} skipped as cached green, {len(self.sampled)} audited (seed {self.seed}); "
            f"{self.greens_written} green(s) written"
        )
        compacted = self.store.compact() + ([reds.RED_FILE] if reds.compact(self.store) else [])
        print(f"  green-result cache: {state}; store {self.store.root}"
              + (f"; compacted {', '.join(compacted)}" if compacted else ""))
        shutil.rmtree(self.deps_dir, ignore_errors=True)
        if self.verdict.flakes:
            print(f"  cache audit: {len(self.verdict.flakes)} sampled hit(s) red in the run, green alone — FLAKY, "
                  f"not a cache defect: {', '.join(self.verdict.flakes)}")
        if not self.verdict.defects:
            if self.sampled:
                print(f"  cache audit: clean ({len(self.sampled)} sampled hit(s) re-run)")
            return rc
        self._print_defects()
        return 1

    def _print_defects(self) -> None:
        defects = self.verdict.defects
        print()
        print(f"=== ✗ CACHE AUDIT: {len(defects)} cached-green file(s) red on re-execution ===")
        stored = self.store.load_deps()
        greens = {path_rel: entry for path_rel, entry in
                  ((cache.rel_of(p, self.repo_root), e) for p, e in (self.decision.cached if self.decision else []))}
        for rel in defects:
            entry, deps = greens.get(rel), stored.get(rel)
            print(f"  {rel}  green {entry.t if entry else '?'} (run {entry.run if entry else '?'}); "
                  f"red in this run and red again alone")
            if deps is not None:
                print(f"      recorded: {len(deps.paths)} path(s), {len(deps.dirs)} dir(s), "
                      f"{len(deps.mods)} module set(s), spawn_py {deps.spawn_py}, spawn_other {deps.spawn_other}")
                for path in deps.paths[:_LISTED]:
                    print(f"        {path}")
            if entry is not None and entry.head:
                try:
                    stat = scope._scope_git(self.repo_root, "diff", "--stat", entry.head).strip().splitlines()
                except RuntimeError as exc:
                    stat = [f"(git diff unavailable: {exc})"]
                print(f"      tree since its green ({entry.head[:10]}): {stat[-1] if stat else 'no change'}")
        print(
            f"  generation bumped to {self.generation}: the next run is cold. A key missed a dependency — file a "
            "fork-hygiene row with this block; never clear the store and move on."
        )
