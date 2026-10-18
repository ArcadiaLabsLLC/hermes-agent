"""``--affected``: run only the test files your uncommitted edits can break. Never a gate.

The change is the working tree against HEAD — tracked edits plus untracked files —
and, with ``--since REF``, ``git diff REF...HEAD`` as well. A test file is selected
when (``select_affected``):

* you edited it (``edited``);
* its LATEST record in the gate store (``deps.jsonl`` / ``modsets.jsonl``) names a
  changed path: a module its process imported that the file's own import chain also
  reaches (``imports <path>`` / ``reaches <path> (import chain)``; a recorded module
  set is the whole process's, see ``ImportGraph``), a non-``.py`` file it opened
  itself (``opened <path>``; the session's opens are the chain's), or a directory it listed that a changed path was added to or removed
  from (``lists <dir>/``; a directory most records list is the session's listing, and
  one the file sits in is its collection's: neither counts; an import-listed one counts when the path's stem is a name the
  process tried to import);
* the session chain changed: the chain's contract (``session-chain contract``);
* NOT a file whose only tie is a changed ``.py`` it opened (``open``/``open_code``) with
  no import reach: that is a whole-tree source walker or a module first loaded deeper
  than two hops — 70 of 180 files for ``agent_runtime/locks.py``, 310 of 370 for
  ``tools/checkpoint_manager.py`` (2026-10-17). Counted in the header, never run;
* a changed path no record names (a new module, a file nothing recorded) reaches it
  by the ``--scope fork`` reach rules, for that path only — its convention source, a
  ``conftest.py`` above it, a direct import (``reach rule: …``); a test file with no
  record is judged by the same rules against every changed path;
* its record says it spawned a program that left no record (the ALL sentinel): the
  sentinel alone never selects it; it is selected only when a changed path lies
  outside ``docs/`` and ``Harness_Brain/`` AND its import chain reaches a changed
  module (``spawned an unrecorded program; …``).

The upstream skip list and the idle-box list win over every rule. Everything
selected runs: no chain sample, no cache audit, no cached-green skip. A module
reached only through the session chain (a conftest, a plugin) or a dynamic import is
NOT selected for: the landing gate (``--scope fork``) is the backstop. The run writes
NOTHING to the gate store (no dependency record, no green, no run line); it keeps a
static-import memo beside it (``MEMO_NAME``). Order: edited files, then direct
importers, then the rest, each fastest-first by ``durations.json``; with
``--fail-fast`` each group runs as its own wave and a red wave stops the run. With
``--cache-dry-run`` it lists the selection and runs nothing.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # imported as ``scripts.run_tests_bundled_affected`` (the tests)
    from scripts import run_tests_bundled_cache as cache
    from scripts import run_tests_bundled_scope as scope
except ImportError:  # loaded by the runner: ``scripts/`` is sys.path[0]
    import run_tests_bundled_cache as cache
    import run_tests_bundled_scope as scope

FLAGS = frozenset({"--affected", "--fail-fast"})
EDITED, DIRECT, REST = 0, 1, 2
GROUP_NAMES = {EDITED: "edited", DIRECT: "direct importers", REST: "the rest"}
#: the static-import memo, beside the gate store and never in it
MEMO_NAME = "hermes_affected_imports.json"
#: import hops a recorded module counts within: the test imports it, or imports a module that
#: does. The graph is one component — a third hop reached 332 files for agent_runtime/locks.py
#: and 1,320 for tools/checkpoint_manager.py, the whole closure 4,400+ (2026-10-17)
REACH_DEPTH = 2
#: a directory more than this share of the records listed is the session's listing, not the file's
SESSION_DIR_SHARE = 0.5


def add_arguments(parser) -> None:
    parser.add_argument(
        "--affected", action="store_true",
        help="run only the test files your uncommitted edits (and --since REF, if given) can break, by the gate "
        "store's per-file dependency records narrowed by static imports; never a gate, writes nothing to the "
        "store — the landing gate is the backstop",
    )
    parser.add_argument("--fail-fast", action="store_true", help="--affected: stop after the first wave with a red")


# ── The change ──────────────────────────────────────────────────────────────


@dataclass
class Change:
    paths: set = field(default_factory=set)
    #: paths added or removed (they change a listed directory's names)
    churned: set = field(default_factory=set)


def _git(repo_root: Path, *args: str) -> List[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args], env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def change_set(repo_root: Path, since: Optional[str] = None) -> Change:
    """Working-tree edits + untracked files vs HEAD, plus ``since...HEAD`` when given."""

    out = Change()
    specs = [["HEAD"]] + ([[f"{since}...HEAD"]] if since else [])
    for spec in specs:
        for line in _git(repo_root, "diff", "--name-status", "--no-renames", *spec):
            status, _, rel = line.partition("\t")
            rel = Path(rel.strip()).as_posix()
            out.paths.add(rel)
            if status[:1] in ("A", "D"):
                out.churned.add(rel)
    for rel in _git(repo_root, "ls-files", "--others", "--exclude-standard"):
        rel = Path(rel.strip()).as_posix()
        out.paths.add(rel)
        out.churned.add(rel)
    return out


# ── The static import graph ─────────────────────────────────────────────────


class ImportGraph:
    """``rel → the module names it imports`` (``scope.imported_modules``), and who reaches whom.

    A recorded module set is the whole PROCESS's — bundle members before the file and
    the session chain included: 4,847 of 6,733 records named ``agent_runtime/locks.py``
    on 2026-10-17. So a ``mods`` hit counts only when the test file also reaches the
    changed module through static imports; a parent package's ``__init__`` counts, as
    importing a submodule runs it."""

    def __init__(self, imports: Mapping[str, Iterable[str]]) -> None:
        self.imports = {rel: set(names) for rel, names in imports.items()}
        self._rev: Optional[Dict[str, set]] = None

    def importers(self, module: str) -> set:
        if self._rev is None:
            self._rev = {}
            for rel, names in self.imports.items():
                for name in names:
                    parts = name.split(".")
                    for i in range(1, len(parts) + 1):
                        self._rev.setdefault(".".join(parts[:i]), set()).add(rel)
        return self._rev.get(module, set())

    def reach(self, modules: Mapping[str, str], depth: int = REACH_DEPTH) -> Dict[str, Tuple[str, bool]]:
        """``rel → (the changed path it reaches, directly?)`` for every file whose import
        chain reaches a changed module (``modules``: name → changed path) in at most
        ``depth`` hops, breadth-first (a file keeps its shortest hop)."""

        out: Dict[str, Tuple[str, bool]] = {}
        seen = set(modules)
        frontier = [(mod, rel) for mod, rel in sorted(modules.items())]
        for hop in range(1, depth + 1):
            following = []
            for mod, origin in frontier:
                for rel in sorted(self.importers(mod)):
                    out.setdefault(rel, (origin, hop == 1))
                    name = scope.module_of(rel)
                    if name and name not in seen:
                        seen.add(name)
                        following.append((name, origin))
            frontier = following
        return out


def load_graph(repo_root: Path, change: Change, memo_path: Path) -> ImportGraph:
    """Every ``.py`` git tracks or the change adds, its imports memoised by blob and path
    in ``memo_path`` (outside the gate store); a changed file is always parsed afresh."""

    keys: Dict[str, Optional[str]] = {}
    for line in _git(repo_root, "ls-files", "-s", "--", "*.py"):
        meta, _, rel = line.partition("\t")
        rel = Path(rel).as_posix()
        keys[rel] = None if rel in change.paths else f"{meta.split()[1]} {rel}"
    keys.update({rel: None for rel in change.paths if rel.endswith(".py") and rel not in keys})
    try:
        memo = json.loads(memo_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        memo = {}
    if not isinstance(memo, dict):
        memo = {}
    found = {rel: memo[key] for rel, key in keys.items() if key and key in memo}
    found.update(_parse_all(repo_root, sorted(rel for rel in keys if rel not in found)))
    kept = {key: found[rel] for rel, key in keys.items() if key}
    if kept.keys() != memo.keys():
        try:
            memo_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = memo_path.with_name(f"{memo_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(kept, sort_keys=True), encoding="utf-8")
            os.replace(tmp, memo_path)
        except OSError:
            pass  # a memo is a speed-up, never a dependency
    return ImportGraph(found)


def _parse_chunk(root: str, rels: List[str]) -> Dict[str, List[str]]:
    return {rel: sorted(scope.imported_modules(Path(root) / rel, rel)) for rel in rels}


def _parse_all(repo_root: Path, rels: List[str]) -> Dict[str, List[str]]:
    """Parse ``rels``: in worker processes when there are many (a cold memo is ~32 s serial)."""

    if len(rels) < 400:
        return _parse_chunk(str(repo_root), rels)
    chunks = [rels[i::8] for i in range(8)]
    try:
        from concurrent.futures import ProcessPoolExecutor

        out: Dict[str, List[str]] = {}
        with ProcessPoolExecutor(max_workers=8) as pool:
            for part in pool.map(_parse_chunk, [str(repo_root)] * len(chunks), chunks):
                out.update(part)
        return out
    except Exception:  # noqa: BLE001 — a pool that cannot start parses serially
        return _parse_chunk(str(repo_root), rels)


# ── Selection ───────────────────────────────────────────────────────────────


@dataclass
class Pick:
    rel: str
    why: str
    group: int = REST


@dataclass
class AffectedSelection:
    picks: Dict[str, Pick] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)  # selected, but on the skip or idle-box list
    uncovered: List[str] = field(default_factory=list)  # changed paths no record names
    #: files whose only tie is a changed .py they opened: source walkers (whole-tree AST gates, 100-240 s
    #: each) and deeper first loads — not run; the landing gate's
    walkers: List[str] = field(default_factory=list)

    def ordered(self, durations: Mapping[str, float]) -> List[Pick]:
        return sorted(
            self.picks.values(), key=lambda p: (p.group, durations.get(p.rel, float("inf")), p.rel),
        )


def _outside_docs(rel: str) -> bool:
    return not rel.startswith(cache.ALL_EXCLUDED_PREFIXES)


def _reach_rule(rel: str, changed: set, reached: Mapping[str, Tuple[str, bool]]) -> Optional[str]:
    """``--scope fork``'s reach rules for one test file against ``changed``."""

    for src in scope.convention_sources(rel):
        if src in changed:
            return f"reach rule: tests {src}"
    for path in sorted(changed):
        if path.endswith("conftest.py") and rel.startswith(path[: -len("conftest.py")]):
            return f"reach rule: conftest {path}"
    hit = reached.get(rel)
    return f"reach rule: imports {hit[0]}" if hit and hit[1] else None


def _reach_why(hit: Tuple[str, bool]) -> str:
    return f"imports {hit[0]}" if hit[1] else f"reaches {hit[0]} (import chain)"


def select_affected(
    tests: Sequence[str],
    change: Change,
    deps: Mapping[str, "cache.StoredDeps"],
    modsets: Mapping[str, List[str]],
    graph: ImportGraph,
    skipped: Iterable[str] = (),
) -> AffectedSelection:
    """Which of ``tests`` (repo-relative test files) the change can break; see the module doc."""

    changed = set(change.paths)
    test_set = set(tests)
    modules = {m: rel for rel in changed for m in [scope.module_of(rel)] if m}
    reached = graph.reach(modules)
    sel = AffectedSelection()
    covered: set = set()
    digest_hits: Dict[str, set] = {}
    for digest, paths in modsets.items():
        found = changed.intersection(paths)
        if found:
            digest_hits[digest] = found
            covered.update(found)
    churn_dirs = {(rel.rsplit("/", 1)[0] if "/" in rel else "."): rel for rel in change.churned}
    listing = _listing_counts(deps.values(), churn_dirs)
    churn_dirs = {d: rel for d, rel in churn_dirs.items() if listing.get(d, 0) <= SESSION_DIR_SHARE * len(deps)}
    churn_names = {rel.rsplit("/", 1)[-1].split(".", 1)[0].casefold(): rel for rel in change.churned}

    for rel in sorted(changed & test_set):
        sel.picks[rel] = Pick(rel, "edited", EDITED)
    sentinel: List[str] = []
    for rel in sorted(test_set & set(deps)):
        record = deps[rel]
        covered.update(changed.intersection(record.paths))
        own = record.keep if record.fx is not None else record.paths  # the session's opens are the chain's
        opened = sorted(changed.intersection(own))
        in_mods = set().union(*(digest_hits.get(d, set()) for d in record.mods))
        why = _reach_why(reached[rel]) if rel in reached and reached[rel][0] in in_mods else None
        if why is None and any(not p.endswith(".py") for p in opened):
            why = f"opened {next(p for p in opened if not p.endswith('.py'))}"
        if why is None:
            why = _listed(record, churn_dirs, churn_names, modsets)
        if why is not None:
            sel.picks.setdefault(rel, Pick(rel, why))
        elif opened:  # a .py opened with no import reach: a source walker (or a deep first load)
            sel.walkers.append(rel)
        elif cache.uncovered_spawn(record.spawn_py, record.spawn_other, record.child_records):
            sentinel.append(rel)

    if any(_outside_docs(p) for p in changed):
        for rel in sentinel:
            if rel in reached and rel not in sel.picks:
                sel.picks[rel] = Pick(rel, f"spawned an unrecorded program; {_reach_why(reached[rel])}")

    if scope.chain.chain_changed(changed):  # the session chain: its contract, as at a landing
        for rel in sorted(test_set):
            if fnmatch.fnmatchcase(rel, scope.CHAIN_CONTRACT_GLOB):
                sel.picks.setdefault(rel, Pick(rel, "session-chain contract"))
    sel.uncovered = sorted(p for p in changed - covered if p not in test_set and not scope.chain.in_chain(p))
    loose = graph.reach({m: r for m, r in modules.items() if r in sel.uncovered})
    for rel in sorted(test_set - set(sel.picks)):
        if rel in deps:
            why = _reach_rule(rel, set(sel.uncovered), loose) if sel.uncovered else None
        else:
            why = _reach_rule(rel, changed, reached)
            why = why and f"{why} (no record)"
        if why:
            sel.picks[rel] = Pick(rel, why)

    for rel in sorted(set(skipped) & set(sel.picks)):
        del sel.picks[rel]
        sel.skipped.append(rel)
    for pick in sel.picks.values():
        if pick.group == REST and rel_direct(reached, pick.rel):
            pick.group = DIRECT
    return sel


def _listing_counts(records: Iterable["cache.StoredDeps"], dirs: Mapping[str, str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        for d in dirs:
            if d in record.dirs and not (d != "." and record.rel.startswith(d + "/")):
                counts[d] = counts.get(d, 0) + 1
    return counts


def _listed(record, churn_dirs: Mapping[str, str], churn_names: Mapping[str, str], modsets) -> Optional[str]:
    """A directory the file listed that a changed path joined or left — not one the file sits
    in, which pytest's collection lists — and an import-listed one only when the path's stem
    is a name the process tried to import (the cache's rule)."""

    for d in sorted(set(record.dirs) & set(churn_dirs)):
        if d != "." and record.rel.startswith(d + "/"):
            continue
        return f"lists {d}/ ({churn_dirs[d]} added or removed)"
    tried = {n.casefold() for digest in record.inames for n in modsets.get(digest, ())}
    for d in sorted(record.idirs):
        for stem, rel in churn_names.items():
            if stem in tried and rel.rsplit("/", 1)[0] == d:
                return f"import-lists {d}/ ({rel} added or removed)"
    return None


def rel_direct(reached: Mapping[str, Tuple[str, bool]], rel: str) -> bool:
    return rel in reached and reached[rel][1]


# ── The run ─────────────────────────────────────────────────────────────────


def main(args, repo_root: Path, runner, pytest_args: List[str]) -> int:
    """Select, print why, run. ``runner`` is ``run_tests_bundled`` (its ``run`` and summary)."""

    started = time.monotonic()
    store = cache.GateStore(cache.gate_store_dir(repo_root, runner.plan.primary_checkout(repo_root), args.cache_dir))
    try:
        change = change_set(repo_root, args.since)
        skip_rows = runner.plan.load_skip_list(args.skip_list or repo_root / runner.plan.SKIP_LIST)
        if not change.paths:
            print(f"Affected: no change against HEAD{' or ' + args.since if args.since else ''} — nothing to run")
            return 0
        graph = load_graph(repo_root, change, store.root.parent / MEMO_NAME)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: --affected cannot read the change: {exc}")
        return 2
    files = runner.rtp._discover_files([repo_root / p for p in (args.paths or runner.rtp._DEFAULT_ROOTS)])
    by_rel = {runner._rel(f, repo_root): f for f in files}
    deps = store.load_deps()
    modsets = store.load_modsets({d for rel, e in deps.items() if rel in by_rel for d in e.digests})
    skipped = set(skip_rows) | scope.load_path_list(repo_root / scope.IDLE_BOX_LIST)
    sel = select_affected(sorted(by_rel), change, deps, modsets, graph, skipped)
    durations = store.load_durations()
    picks = sel.ordered(durations)
    print(
        f"Affected: {len(change.paths)} changed path(s) → {len(picks)} of {len(by_rel)} test file(s) "
        f"({time.monotonic() - started:.1f}s to select; {len(sel.uncovered)} changed path(s) no record names, "
        f"reach rules for those; {len(sel.walkers)} source walker(s) left out); never a gate — the landing "
        "gate is the backstop",
        flush=True,
    )
    for pick in picks:
        print(f"  {pick.rel}  — {pick.why}")
    for rel in sel.skipped:
        print(f"  skipped (skip/idle-box list): {rel}")
    if not picks or args.cache_dry_run:
        return 0
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(runner._PLUGIN_DIR)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    )
    pytest_args = pytest_args + runner.plan.deselect_args(skip_rows, set())
    waves = [[p for p in picks if p.group == g] for g in GROUP_NAMES] if args.fail_fast else [picks]
    rc = 0
    for wave in (w for w in waves if w):
        rc = _run_wave(args, repo_root, runner, pytest_args, [by_rel[p.rel] for p in wave], durations)
        if rc and args.fail_fast:
            print(f"--fail-fast: stopped after the {GROUP_NAMES[wave[0].group]} wave")
            return rc
    return rc


def _run_wave(args, repo_root: Path, runner, pytest_args: List[str], files: List[Path], durations) -> int:
    done = [0]

    def progress(outcome) -> None:
        done[0] += 1
        status = "✓" if outcome.rc == 0 else "✗"
        print(f"[{done[0]:>5}/{len(files)}] {status} {runner._rel(outcome.file, repo_root)} "
              f"({outcome.via}, {outcome.seconds:.1f}s) {outcome.summary}", flush=True)
        if outcome.rc != 0:
            runner.rtp._print_inline_failure(outcome.file, outcome.output, repo_root, pytest_args)

    started = time.monotonic()
    result = runner.run(
        files, pytest_args, repo_root, jobs=args.jobs, bundle_size=args.bundle_size,
        unbundled=runner.load_unbundled(args.unbundled_list), flat_timeout=args.file_timeout,
        retries=args.file_retries, durations=durations, bundle_seconds=args.bundle_seconds,
        solo_seconds=args.solo_seconds, on_outcome=progress,
    )
    elapsed = time.monotonic() - started
    return runner._print_summary(result, files, repo_root, elapsed, args.jobs, result.ledger.summary(args.jobs))
