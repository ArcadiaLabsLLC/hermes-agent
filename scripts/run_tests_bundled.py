#!/usr/bin/env python3
"""Bundled test runner: N test files per pytest process instead of one.

``scripts/run_tests_parallel.py`` runs one ``python -m pytest <file>`` per test
file. Every one of those processes pays interpreter start, plugin load and the
root conftest before its first test; this runner pays it once per BUNDLE of up
to ``--bundle-size`` files (default 20) and otherwise keeps that runner's
contract, by calling its helpers rather than re-spelling them:

* same discovery (``_discover_files``), worker cap, per-attempt temp root,
  process-tree kill, crash and timeout handling (``_run_one_file_once`` runs a
  bundle — its argv is ``pytest <first> <rest…> <args>``);
* same durations file: per-file timings are still recorded, from a small
  plugin (``scripts/_bundle_plugin/hermes_bundle_report.py``) that writes one
  JSON line per collected module and per test report;
* per-bundle timeout scaled from the members' cached durations;
* a bundle whose process DIED before its session ended (pytest-timeout's
  thread method — the only one on Windows, which has no SIGALRM — kills the
  whole process) runs the member it died in alone and sends the members
  that never started back out as ONE new bundle (``Death``);
* retry-on-fail, with isolation added: a bundle that exits non-zero re-runs
  every other member that did not record a clean pass ONE FILE PER PROCESS
  (``_run_one_file``, with the per-file runner's own flake retry). A member
  red in its bundle and green alone is reported as an ISOLATION LEAK, with the
  members that ran before it — that is the observed diff an entry in
  ``scripts/test_bundles_unbundled.txt`` must carry.

Scope (``--scope``) decides which discovered files run at all. ``fork``, the
default and the fork's landing gate, runs every file absent from
``tests/fixtures/upstream_manifest.txt`` plus each inherited file the change
reaches (``select_scope``): the file itself changed, its convention-mapped
source (``tests/<pkg>/test_<mod>.py`` → ``<pkg>/<mod>.py``) changed, it imports
a changed module, or a ``conftest.py`` above it changed. The change is
``git diff --name-only <--since>...HEAD`` (default ``origin/main``) plus
working-tree edits. ``full`` runs everything discovered — the weekly upstream
merge lane, where the inherited set is the thing under test.

Membership is mechanical: files are grouped by their top-level test directory
(``tests/<dir>``), sorted by path, and cut into consecutive chunks. Files named
in the unbundled list run alone. Bundles are submitted longest-first by their
members' cached durations.

The runner's core (``assign_bundles``, ``tally_events``, ``members_to_rerun``,
``bundle_timeout``, ``run``) names no fork path, so it can be lifted into
``run_tests_parallel.py`` as a ``--bundle-size`` flag.

Usage:
    python scripts/run_tests_bundled.py [--scope fork|full] [--since REF] [--bundle-size N] [-j N] [PATH ...] [pytest args]
    scripts/run_tests_bundled.sh tests/agent_runtime tests/hermes_cli tests/hermes_state  # landing gate (fork scope)
    scripts/run_tests_bundled.sh --scope full tests/agent_runtime tests/hermes_cli tests/hermes_state  # weekly merge lane

Exit code: 0 if every file passed (alone or in its bundle); 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PLUGIN_DIR = _SCRIPTS_DIR / "_bundle_plugin"
_PLUGIN_NAME = "hermes_bundle_report"
_DEFAULT_UNBUNDLED = _SCRIPTS_DIR / "test_bundles_unbundled.txt"
DEFAULT_BUNDLE_SIZE = 20
#: Estimated seconds for a member with no cached duration, for the bundle
#: timeout and the submission order only.
_UNCACHED_ESTIMATE_SECONDS = 30.0
_CATEGORIES = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")


def _load_parallel_runner():
    """``run_tests_parallel`` as a module, whether this file runs as a script
    or is imported by a test (``scripts/`` is not a package)."""

    existing = sys.modules.get("run_tests_parallel")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        "run_tests_parallel", _SCRIPTS_DIR / "run_tests_parallel.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_tests_parallel"] = module
    spec.loader.exec_module(module)
    return module


rtp = _load_parallel_runner()


# ── Membership ──────────────────────────────────────────────────────────────


def _rel(path: Path, repo_root: Path) -> str:
    return Path(rtp._format_file(path, repo_root)).as_posix()


def load_unbundled(path: Path) -> set[str]:
    """Repo-relative POSIX paths listed in the unbundled file.

    One path per line; ``#`` starts a comment (the observed diff that put the
    file there belongs on its line); blank lines ignored; a missing file is an
    empty list."""

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    out: set[str] = set()
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            out.add(Path(entry).as_posix())
    return out


def _group_key(rel: str) -> Tuple[str, ...]:
    parts = tuple(rel.split("/"))
    return parts[:2] if len(parts) > 2 else parts[:1]


def assign_bundles(
    files: Sequence[Path],
    repo_root: Path,
    bundle_size: int,
    unbundled: Iterable[str] = (),
) -> Tuple[List[List[Path]], List[Path]]:
    """Split ``files`` into ``(bundles, solos)``.

    Every file lands in exactly one bundle or in ``solos``. Solos are the files
    named in ``unbundled``; with ``bundle_size < 2`` every file is a solo.
    Bundles never cross a top-level test directory and keep path order."""

    skip = set(unbundled)
    by_rel = sorted(((_rel(f, repo_root), f) for f in files), key=lambda item: item[0])
    solos: List[Path] = []
    groups: Dict[Tuple[str, ...], List[Path]] = {}
    for rel, path in by_rel:
        if bundle_size < 2 or rel in skip:
            solos.append(path)
            continue
        groups.setdefault(_group_key(rel), []).append(path)
    bundles: List[List[Path]] = []
    for key in sorted(groups):
        members = groups[key]
        for start in range(0, len(members), bundle_size):
            bundles.append(members[start : start + bundle_size])
    return bundles, solos


def _estimate(path: Path, repo_root: Path, durations: Dict[str, float]) -> float:
    return float(durations.get(rtp._format_file(path, repo_root)) or _UNCACHED_ESTIMATE_SECONDS)


def bundle_timeout(
    bundle: Sequence[Path],
    repo_root: Path,
    flat_timeout: float,
    durations: Dict[str, float],
) -> float:
    """``max(flat, 3 × Σ member estimates)`` — the per-file runner's scaling
    rule (``_effective_file_timeout``) applied to the bundle's total."""

    return max(flat_timeout, 3.0 * sum(_estimate(f, repo_root, durations) for f in bundle))


# ── Scope: which discovered files a run executes ────────────────────────────

SCOPE_FORK = "fork"
SCOPE_FULL = "full"
_DEFAULT_MANIFEST = Path("tests") / "fixtures" / "upstream_manifest.txt"
_DEFAULT_SINCE = "origin/main"


def load_manifest(path: Path) -> set[str]:
    """Repo-relative POSIX paths the inherited-files manifest lists (``#``
    lines are comments). A missing manifest raises: without it every file
    would read as fork-only and the scope would silently be the full set."""

    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            out.add(Path(entry).as_posix())
    return out


def changed_paths(repo_root: Path, since: str) -> set[str]:
    """Paths the work under test changed: ``git diff --name-only <since>...HEAD``
    plus the tracked working-tree edits (``git diff --name-only HEAD``). Raises
    ``RuntimeError`` when git cannot answer, so an unknown diff is never read
    as an empty one."""

    import subprocess

    out: set[str] = set()
    for spec in ([f"{since}...HEAD"], ["HEAD"]):
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", *spec],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git diff --name-only {' '.join(spec)} failed: {proc.stderr.strip()}")
        out.update(Path(line.strip()).as_posix() for line in proc.stdout.splitlines() if line.strip())
    return out


def module_of(rel: str) -> Optional[str]:
    """``a/b/c.py`` → ``a.b.c``; ``a/b/__init__.py`` → ``a.b``; else None."""

    if not rel.endswith(".py"):
        return None
    parts = rel[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts and all(p.isidentifier() for p in parts) else None


def convention_sources(test_rel: str) -> List[str]:
    """Upstream's layout: ``tests/<pkg…>/test_<mod>.py`` tests ``<pkg…>/<mod>.py``
    (or the package ``<pkg…>/<mod>/__init__.py``)."""

    parts = test_rel.split("/")
    if len(parts) < 2 or parts[0] != "tests" or not parts[-1].startswith("test_"):
        return []
    stem = parts[-1][len("test_") :]
    base = "/".join(parts[1:-1] + [stem[: -len(".py")]]) if stem.endswith(".py") else ""
    return [f"{base}.py", f"{base}/__init__.py"] if base else []


def imported_modules(path: Path, rel: str) -> set[str]:
    """Every module name ``path`` imports, relative imports resolved against
    its package. ``from a import b`` yields both ``a`` and ``a.b``. A file that
    does not parse yields nothing (its own run will say why)."""

    import ast
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # a test's own SyntaxWarning is its run's to report
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return set()
    package = rel.split("/")[:-1]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else list(package)
                head = ".".join(base + ([node.module] if node.module else []))
            else:
                head = node.module or ""
            if head:
                out.add(head)
            out.update(f"{head}.{alias.name}" if head else alias.name for alias in node.names)
    return out


@dataclass
class ScopeSelection:
    """Why each selected file is in scope, and what was left out."""

    fork_only: List[Path] = field(default_factory=list)
    #: inherited files, by the reason that selected them
    touched: List[Path] = field(default_factory=list)  # the test file itself changed
    source: List[Path] = field(default_factory=list)  # its convention-mapped source changed
    importer: List[Path] = field(default_factory=list)  # it imports a changed module
    conftest: List[Path] = field(default_factory=list)  # a conftest.py above it changed
    named: List[Path] = field(default_factory=list)  # named explicitly on the command line
    excluded: List[Path] = field(default_factory=list)

    @property
    def selected(self) -> List[Path]:
        return sorted(
            self.fork_only + self.touched + self.source + self.importer + self.conftest + self.named,
            key=lambda p: str(p),
        )


def select_scope(
    files: Sequence[Path],
    repo_root: Path,
    inherited: set[str],
    changed: set[str],
    named: Iterable[Path] = (),
) -> ScopeSelection:
    """The ``fork`` scope: every file NOT in ``inherited`` (the upstream
    manifest), plus each inherited file the change could reach — the file
    itself changed, the source its name maps to changed, it imports a changed
    module, or a ``conftest.py`` in one of its directories changed. Files named
    explicitly (not found by walking a directory) always run."""

    named_real = {Path(p).resolve() for p in named}
    changed_modules = {m for m in (module_of(rel) for rel in changed) if m}
    changed_conftest_dirs = {rel.rsplit("/", 1)[0] for rel in changed if rel.endswith("/conftest.py")}
    sel = ScopeSelection()
    for path in files:
        rel = _rel(path, repo_root)
        if rel not in inherited:
            sel.fork_only.append(path)
        elif path.resolve() in named_real:
            sel.named.append(path)
        elif rel in changed:
            sel.touched.append(path)
        elif any(src in changed for src in convention_sources(rel)):
            sel.source.append(path)
        elif any(rel.startswith(d + "/") for d in changed_conftest_dirs):
            sel.conftest.append(path)
        elif changed_modules and any(
            imp == mod or imp.startswith(mod + ".")
            for imp in imported_modules(path, rel)
            for mod in changed_modules
        ):
            sel.importer.append(path)
        else:
            sel.excluded.append(path)
    return sel


# ── Per-file results out of one bundle process ──────────────────────────────


@dataclass
class FileTally:
    counts: Dict[str, int] = field(default_factory=dict)
    collect_seconds: float = 0.0
    test_seconds: float = 0.0
    collect_error: bool = False
    failed_nodeids: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        out = {k: v for k, v in self.counts.items() if v}
        if self.collect_error:
            out["errors"] = out.get("errors", 0) + 1
        return out

    @property
    def clean(self) -> bool:
        return not self.collect_error and not self.counts.get("failed") and not self.counts.get("errors")


@dataclass
class BundleEvents:
    files: Dict[str, FileTally] = field(default_factory=dict)
    session_start: Optional[float] = None
    session_end: Optional[float] = None
    exit_status: Optional[int] = None


def tally_events(lines: Iterable[str]) -> BundleEvents:
    """Fold the plugin's JSON lines into per-file tallies. A torn last line
    (process killed mid-write) is ignored."""

    events = BundleEvents()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = record.get("k")
        if kind == "start":
            events.session_start = record.get("t")
        elif kind == "end":
            events.session_end = record.get("t")
            events.exit_status = record.get("rc")
        elif kind == "collect":
            tally = events.files.setdefault(record["f"], FileTally())
            tally.collect_seconds += float(record.get("d") or 0.0)
            tally.collect_error = tally.collect_error or bool(record.get("err"))
        elif kind == "test":
            tally = events.files.setdefault(record["f"], FileTally())
            tally.test_seconds += float(record.get("d") or 0.0)
            category = record.get("c") or ""
            if category == "error":
                category = "errors"
            if category in _CATEGORIES:
                tally.counts[category] = tally.counts.get(category, 0) + 1
            if record.get("n"):
                tally.failed_nodeids.append(record["n"])
    return events


def members_to_rerun(member_rels: Sequence[str], events: BundleEvents, bundle_rc: int) -> List[str]:
    """The members of a non-zero bundle that must be re-run alone.

    A member is re-run when it recorded a failure or error, or recorded
    nothing at all. When the session never reached its end (killed by the
    timeout, crashed), a clean tally proves nothing for the member that was
    running and the ones queued behind it, so every member from the last one
    that recorded a test onward is re-run too. If the bundle failed but no
    member carries the failure (a session-level error), every member is
    re-run. A zero-exit bundle re-runs nothing."""

    if bundle_rc == 0:
        return []
    complete = set(member_rels)
    if events.session_end is None:
        ran = [i for i, rel in enumerate(member_rels) if rel in events.files and events.files[rel].counts]
        complete = set(member_rels[: ran[-1]]) if ran else set()
    rerun = [
        rel
        for rel in member_rels
        if rel not in complete or rel not in events.files or not events.files[rel].clean
    ]
    return rerun or list(member_rels)


# ── Execution ───────────────────────────────────────────────────────────────


@dataclass
class FileOutcome:
    file: Path
    rc: int
    output: str
    summary: Dict[str, int]
    seconds: float
    via: str  # "bundle" | "solo" | "rerun"
    bundle_index: Optional[int] = None


@dataclass
class Leak:
    """A member re-run alone that passed there.

    ``kind`` is ``"leak"`` when its bundle reached the end of its session and
    the member recorded a failure in it — red with other files in the process,
    green alone: module state leaked into it. It is ``"unreached"`` when the
    bundle process died first (pytest-timeout's thread method, a crash, the
    bundle timeout): nothing is known about the member except that it never
    finished, and ``stopped_in`` names the member the process died in — the
    file that belongs in the unbundled list, not this one."""

    file: Path
    bundle_index: int
    earlier: List[str]
    in_bundle: Dict[str, int]
    failed_nodeids: List[str]
    kind: str = "leak"
    stopped_in: Optional[str] = None


@dataclass
class RunResult:
    outcomes: List[FileOutcome]
    leaks: List[Leak]
    bundle_walls: List[Tuple[int, float, int]]  # (index, wall, rc)
    bundles: List[List[Path]]
    solos: List[Path]
    reruns: int
    deaths: List["Death"] = field(default_factory=list)
    rebundles: int = 0


@dataclass
class Death:
    """A bundle process that died before its session ended: the member it
    died in (run alone next) and the members behind it that never started
    (re-bundled together)."""

    bundle_index: int
    stopped_in: str
    unreached: List[str]


BundleRunner = Callable[[Path, List[str], Path, float], Tuple[Path, int, str, Dict[str, int], float]]
SoloRunner = Callable[[Path, List[str], Path, float, int], Tuple[Path, int, str, Dict[str, int], float]]


def run(
    files: Sequence[Path],
    pytest_args: List[str],
    repo_root: Path,
    *,
    jobs: int,
    bundle_size: int = DEFAULT_BUNDLE_SIZE,
    unbundled: Iterable[str] = (),
    flat_timeout: float,
    retries: int,
    durations: Dict[str, float],
    bundle_runner: Optional[BundleRunner] = None,
    solo_runner: Optional[SoloRunner] = None,
    on_outcome: Optional[Callable[[FileOutcome], None]] = None,
) -> RunResult:
    """Run ``files`` as bundles plus solos; return one outcome per file.

    ``bundle_runner`` / ``solo_runner`` default to the per-file runner's
    ``_run_one_file_once`` / ``_run_one_file``; tests inject fakes."""

    bundle_runner = bundle_runner or rtp._run_one_file_once
    solo_runner = solo_runner or rtp._run_one_file
    bundles, solos = assign_bundles(files, repo_root, bundle_size, unbundled)

    lock = threading.Lock()
    outcomes: List[FileOutcome] = []
    leaks: List[Leak] = []
    bundle_walls: List[Tuple[int, float, int]] = []
    deaths: List[Death] = []
    first_pass_bundles = len(bundles)
    futures: List[Future] = []
    reruns = 0
    scratch = Path(tempfile.mkdtemp(prefix="bundles-", dir=rtp._runner_scratch_root()))

    def _record(outcome: FileOutcome) -> None:
        with lock:
            outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    def _solo(path: Path, via: str, bundle_index: Optional[int], leak_info=None) -> None:
        timeout = rtp._effective_file_timeout(path, repo_root, flat_timeout, durations)
        fpath, rc, output, summary, wall = solo_runner(path, pytest_args, repo_root, timeout, retries)
        if via == "rerun" and rc == 0 and leak_info is not None:
            with lock:
                leaks.append(leak_info)
        _record(FileOutcome(fpath, rc, output, summary, wall, via, bundle_index))

    def _bundle(index: int, members: List[Path], executor: ThreadPoolExecutor) -> None:
        nonlocal reruns
        events_path = scratch / f"bundle-{index:04d}.jsonl"
        args = [str(m) for m in members[1:]] + list(pytest_args) + [
            "-p",
            _PLUGIN_NAME,
            f"--hermes-bundle-events={events_path}",
        ]
        timeout = bundle_timeout(members, repo_root, flat_timeout, durations)
        started = time.time()
        _first, rc, output, _summary, wall = bundle_runner(members[0], args, repo_root, timeout)
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        events = tally_events(lines)
        with lock:
            bundle_walls.append((index, wall, rc))
        rels = [_rel(m, repo_root) for m in members]
        startup_share = 0.0
        if events.session_start is not None:
            startup_share = max(0.0, events.session_start - started) / len(members)
        rerun = set(members_to_rerun(rels, events, rc))
        stopped_in = None
        unreached: List[Path] = []
        if rc != 0 and events.session_end is None:
            ran = [rel for rel in rels if rel in events.files and events.files[rel].counts]
            stopped_in = ran[-1] if ran else rels[0]
            unreached = [m for m, rel in zip(members, rels) if rels.index(rel) > rels.index(stopped_in)]
            with lock:
                deaths.append(Death(index, stopped_in, [_rel(m, repo_root) for m in unreached]))
        for position, (member, rel) in enumerate(zip(members, rels)):
            tally = events.files.get(rel, FileTally())
            if rel not in rerun:
                seconds = startup_share + tally.collect_seconds + tally.test_seconds
                _record(FileOutcome(member, 0, "", tally.summary(), seconds, "bundle", index))
                continue
            if member in unreached:
                continue  # never started: re-bundled below, not run alone
            leak = Leak(
                member,
                index,
                rels[:position],
                tally.summary(),
                list(tally.failed_nodeids),
                "unreached" if stopped_in is not None else "leak",
                stopped_in,
            )
            with lock:
                reruns += 1
                futures.append(executor.submit(_solo, member, "rerun", index, leak))
        # The process died in ``stopped_in`` (which goes solo above); the members
        # queued behind it never started, so nothing about them needs a process
        # of its own — they go back out as one bundle. Each re-bundle is shorter
        # by at least the file it died in, so this terminates.
        if len(unreached) >= 2:
            with lock:
                new_index = len(bundles)
                bundles.append(unreached)
                futures.append(executor.submit(_bundle, new_index, unreached, executor))
        elif unreached:
            with lock:
                reruns += 1
                futures.append(executor.submit(_solo, unreached[0], "rerun", index, None))

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        order = sorted(
            range(len(bundles)),
            key=lambda i: sum(_estimate(f, repo_root, durations) for f in bundles[i]),
            reverse=True,
        )
        with lock:
            for i in order:
                futures.append(executor.submit(_bundle, i, bundles[i], executor))
            for path in sorted(solos, key=lambda p: _estimate(p, repo_root, durations), reverse=True):
                futures.append(executor.submit(_solo, path, "solo", None))
        # Re-runs are submitted from inside bundle jobs, so drain until the
        # list stops growing.
        seen = 0
        while True:
            with lock:
                pending = futures[seen:]
                seen = len(futures)
            if not pending:
                break
            for fut in pending:
                fut.result()

    shutil.rmtree(scratch, ignore_errors=True)

    # The per-file runner's straggler rule, unchanged: a file whose failure is
    # timeout-shaped (contention, not an assertion) gets one serial retry at
    # 1-worker isolation after the pool drains.
    for position, outcome in enumerate(list(outcomes)):
        if outcome.rc == 0 or not rtp._is_retryable_timeout_result(1, outcome.output, outcome.summary):
            continue
        fpath, rc, output, summary, wall = solo_runner(outcome.file, pytest_args, repo_root, flat_timeout, 0)
        outcomes[position] = FileOutcome(fpath, rc, output, summary, wall, "retry", outcome.bundle_index)
        if on_outcome is not None:
            on_outcome(outcomes[position])

    return RunResult(
        outcomes, leaks, bundle_walls, bundles, solos, reruns, deaths, len(bundles) - first_pass_bundles
    )


# ── CLI ─────────────────────────────────────────────────────────────────────

_OUR_FLAGS = {
    "-h", "--help", "-j", "--jobs", "--bundle-size", "--file-timeout",
    "--file-retries", "--unbundled-list", "--scope", "--since", "--manifest",
}
_PYTEST_VALUE_FLAGS = {"-k", "-m", "-p", "-o", "-c", "-r", "-W"}


def _split_argv(argv: List[str]) -> Tuple[List[str], List[str]]:
    if "--" in argv:
        sep = argv.index("--")
        before, explicit = argv[:sep], argv[sep + 1 :]
    else:
        before, explicit = argv, []
    ours: List[str] = []
    passthrough: List[str] = []
    i = 0
    while i < len(before):
        tok = before[i]
        head = tok.split("=", 1)[0]
        if tok.startswith("-") and head not in _OUR_FLAGS and tok[:2] not in {"-j"}:
            passthrough.append(tok)
            if tok in _PYTEST_VALUE_FLAGS and i + 1 < len(before):
                passthrough.append(before[i + 1])
                i += 2
                continue
        else:
            ours.append(tok)
        i += 1
    return ours, passthrough + explicit


def _print_summary(result: RunResult, files: Sequence[Path], repo_root: Path, elapsed: float, jobs: int) -> int:
    totals = {k: 0 for k in _CATEGORIES}
    failures = [o for o in result.outcomes if o.rc != 0]
    for outcome in result.outcomes:
        for key in _CATEGORIES:
            totals[key] += outcome.summary.get(key, 0)
    collected = sum(totals.values())
    crashed = sum(1 for o in result.outcomes if o.summary.get("crashed"))
    print()
    print(
        f"=== Summary: {len(files)} files ({len(result.bundles) - result.rebundles} bundles + "
        f"{result.rebundles} re-bundled, {len(result.solos)} solo, "
        f"{result.reruns} re-run alone), {totals['passed']} tests passed, {totals['failed']} failed, "
        f"{totals['errors']} errors, {totals['skipped']} skipped in {elapsed:.1f}s ({jobs} workers) ==="
    )
    if result.bundle_walls:
        walls = sorted(result.bundle_walls, key=lambda item: item[1], reverse=True)
        print("  Slowest bundles:")
        for index, wall, rc in walls[:10]:
            first = _rel(result.bundles[index][0], repo_root)
            print(f"    {wall:>7.1f}s  rc={rc}  #{index} ({len(result.bundles[index])} files from {first})")
    leaks = [leak for leak in result.leaks if leak.kind == "leak"]
    unreached = [leak for leak in result.leaks if leak.kind == "unreached"]
    if leaks:
        print()
        print(
            f"=== ⚠ {len(leaks)} ISOLATION LEAK{'S' if len(leaks) != 1 else ''} "
            "(red in a bundle that finished, green alone — candidates for scripts/test_bundles_unbundled.txt) ==="
        )
        for leak in leaks:
            print(
                f"  {_rel(leak.file, repo_root)}  # observed: bundle #{leak.bundle_index} {leak.in_bundle} "
                f"after {len(leak.earlier)} earlier member(s); passed alone"
            )
            for nodeid in leak.failed_nodeids[:5]:
                print(f"      red in bundle: {nodeid}")
            if leak.earlier:
                print(f"      earlier members: {', '.join(leak.earlier)}")
    if result.deaths:
        passed_alone = {_rel(leak.file, repo_root) for leak in unreached}
        print()
        print(
            f"=== {len(result.deaths)} bundle process(es) died before their session ended. The file each died in "
            "ran alone; the members behind it were re-bundled. The file is the unbundled-list candidate ==="
        )
        for death in sorted(result.deaths, key=lambda d: d.bundle_index):
            alone = "passed alone" if death.stopped_in in passed_alone else "red alone too"
            print(
                f"  {death.stopped_in}  # observed: bundle #{death.bundle_index} died in this file ({alone}); "
                f"{len(death.unreached)} later member(s) re-bundled"
            )
    if rtp._FLAKY_RESULTS:
        print()
        print(f"=== ⚠ {len(rtp._FLAKY_RESULTS)} FLAKY file(s) (failed once alone, passed on retry) ===")
        for path, _output in rtp._FLAKY_RESULTS:
            print(f"  {_rel(path, repo_root)}")
    if failures:
        print()
        print("=== Failure output ===")
        for outcome in sorted(failures, key=lambda o: _rel(o.file, repo_root)):
            print()
            print(f"--- {_rel(outcome.file, repo_root)} ---")
            print(outcome.output.rstrip())
        print()
        print(f"=== {len(failures)} file{'s' if len(failures) != 1 else ''} failed ===")
        for outcome in sorted(failures, key=lambda o: _rel(o.file, repo_root)):
            print(f"  {_rel(outcome.file, repo_root)}  {outcome.summary}")
    if collected == 0 and not crashed:
        print()
        print(f"=== ✗ NO TESTS RAN — 0 collected across {len(files)} files. This is NOT a pass. ===")
        return 1
    return 1 if failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    rtp._make_stdio_glyph_safe()
    ours, pytest_args = _split_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "-j", "--jobs", type=int,
        default=int(os.environ.get("HERMES_TEST_WORKERS") or rtp._adaptive_default_jobs(os.cpu_count())),
    )
    parser.add_argument("--bundle-size", type=int, default=DEFAULT_BUNDLE_SIZE)
    parser.add_argument(
        "--file-timeout", type=float,
        default=float(os.environ.get("HERMES_TEST_FILE_TIMEOUT", rtp._DEFAULT_FILE_TIMEOUT_SECONDS)),
    )
    parser.add_argument(
        "--file-retries", type=int,
        default=int(os.environ.get("HERMES_TEST_FILE_RETRIES", rtp._DEFAULT_FILE_RETRIES)),
    )
    parser.add_argument("--unbundled-list", type=Path, default=_DEFAULT_UNBUNDLED)
    parser.add_argument(
        "--scope", choices=(SCOPE_FORK, SCOPE_FULL), default=SCOPE_FORK,
        help="fork (default, the landing gate): files absent from the upstream manifest plus the "
        "inherited files the change reaches; full: every discovered file (the weekly merge lane)",
    )
    parser.add_argument(
        "--since", default=_DEFAULT_SINCE, metavar="REF",
        help=f"--scope fork: the change is `git diff <REF>...HEAD` plus working-tree edits (default {_DEFAULT_SINCE})",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="upstream manifest (default tests/fixtures/upstream_manifest.txt)")
    parser.add_argument("paths", nargs="*", metavar="PATH")
    args = parser.parse_args(ours)

    if any("::" in p for p in args.paths):
        parser.error("node ids are not supported here; run the file with scripts/run_tests.sh")

    repo_root = _SCRIPTS_DIR.parent
    roots = [repo_root / p for p in (args.paths or rtp._DEFAULT_ROOTS)]
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        parser.error(f"path(s) do not exist: {', '.join(missing)}")
    files = rtp._discover_files(roots)
    if not files:
        print("No test files to run", file=sys.stderr)
        return 1
    if args.scope == SCOPE_FORK:
        manifest = args.manifest or repo_root / _DEFAULT_MANIFEST
        try:
            inherited = load_manifest(manifest)
            changed = changed_paths(repo_root, args.since)
        except (OSError, RuntimeError) as exc:
            print(
                f"error: --scope fork cannot tell fork from inherited files: {exc}\n"
                "       fix the cause, or run --scope full",
                file=sys.stderr,
            )
            return 2
        sel = select_scope(files, repo_root, inherited, changed, named=[r for r in roots if r.is_file()])
        print(
            f"Scope fork (since {args.since}, {len(changed)} changed path(s)): {len(sel.fork_only)} fork-only + "
            f"{len(sel.selected) - len(sel.fork_only)} inherited reached by the change "
            f"(touched {len(sel.touched)}, source {len(sel.source)}, importer {len(sel.importer)}, "
            f"conftest {len(sel.conftest)}, named {len(sel.named)}); "
            f"{len(sel.excluded)} inherited left to --scope full",
            flush=True,
        )
        files = sel.selected
        if not files:
            print("No test files in scope", file=sys.stderr)
            return 1

    # Constant for the whole run, so setting it before any worker starts is
    # race-free: every bundle child can then load the plugin by name.
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(_PLUGIN_DIR)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    )
    durations = rtp._load_durations(repo_root)
    unbundled = load_unbundled(args.unbundled_list)
    print(
        f"Bundled runner: {len(files)} test files, bundle size {args.bundle_size}, "
        f"{len(unbundled)} listed unbundled, -j {args.jobs}",
        flush=True,
    )

    done = 0
    counter_lock = threading.Lock()

    def _progress(outcome: FileOutcome) -> None:
        nonlocal done
        with counter_lock:
            done += 1
            status = "✓" if outcome.rc == 0 else "✗"
            print(
                f"[{done:>5}/{len(files)}] {status} {_rel(outcome.file, repo_root)} "
                f"({outcome.via}, {outcome.seconds:.1f}s) {outcome.summary}",
                flush=True,
            )
            if outcome.rc != 0:
                rtp._print_inline_failure(outcome.file, outcome.output, repo_root, pytest_args)

    started = time.monotonic()
    result = run(
        files,
        pytest_args,
        repo_root,
        jobs=args.jobs,
        bundle_size=args.bundle_size,
        unbundled=unbundled,
        flat_timeout=args.file_timeout,
        retries=args.file_retries,
        durations=durations,
        on_outcome=_progress,
    )
    elapsed = time.monotonic() - started

    failures = [(o.file, o.output, o.summary) for o in result.outcomes if o.rc != 0]
    leaked = {leak.file for leak in result.leaks}
    times = [(o.file, o.seconds) for o in result.outcomes if o.file not in leaked]
    clean = rtp._clean_pass_durations(times, failures, rtp._FLAKY_RESULTS)
    if clean:
        rtp._save_durations(clean, repo_root)
        print(f"  Durations cached to {rtp._DURATIONS_FILE} ({len(clean)} files)")
    return _print_summary(result, files, repo_root, elapsed, args.jobs)


if __name__ == "__main__":
    sys.exit(main())
