"""``--affected <base>``: the default landing gate's file selection.

Owner ruling 2026-10-16: the whole tree runs only at an upstream release merge;
every other landing runs the files its change can reach. The change is
``git diff --name-only <base>...HEAD`` plus the working-tree edits
(``scope.changed_paths``). A discovered test file is selected for the FIRST of
these reasons that holds (:class:`Reason`):

* ``touched`` — the diff touches the test file itself;
* ``importer`` — it reaches a changed path through the import graph: an AST
  walk of its static imports, transitively, plus the ``conftest.py`` files above
  it, and, where the gate store holds the dependency recorder's record of it
  (``scripts/_bundle_plugin/hermes_dep_record.py``), every path it opened — data
  files and dynamic imports the AST cannot see (``records_from_store`` says why
  the record's module sets are not used);
* ``gate`` — a changed path falls under a glob the gate declares in
  ``scripts/affected_gate_paths.txt`` (the tooling gates walk the tree, so a file
  they would walk can be new to every record);
* ``sample`` — the change touches the SESSION CHAIN (``scripts/run_tests_bundled_chain.py``'s
  paths, sitecustomize among them, and the runner itself): every process loads
  it, so it reaches every file, and the selection takes the smallest file of
  every test folder, ties by path, as the chain's smoke run — drawn from the
  fork-owned files only (what ``--scope fork`` runs with no change; never
  ``tests/e2e`` or ``tests/docker``, which discovery leaves out, nor an upstream
  file), the skip list applied. A session-chain path selects an importer only
  through what the file opened ITSELF (the record's ``keep``) or imports
  statically, never through the session's own loads;
* ``named`` — named on the command line.

The upstream skip list and the idle-box list apply as in every scope: a listed
file runs only when named. Pure selection: no test runs here.
"""

from __future__ import annotations

import fnmatch
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

try:  # imported as ``scripts.run_tests_bundled_affected`` (the tests)
    from scripts import run_tests_bundled_cache as cache
    from scripts import run_tests_bundled_chain as chain
    from scripts import run_tests_bundled_scope as scope
except ImportError:  # loaded by the runner: ``scripts/`` is sys.path[0]
    import run_tests_bundled_cache as cache
    import run_tests_bundled_chain as chain
    import run_tests_bundled_scope as scope

#: gate test file → the globs of the paths it walks (``fnmatch``: ``*`` crosses ``/``)
GATE_PATHS_LIST = Path("scripts") / "affected_gate_paths.txt"
#: the runner's own files: a change to them changes how every file is run
RUNNER_GLOBS = (
    "scripts/run_tests_bundled*.py", "scripts/run_tests_bundled.sh", "scripts/run_tests.sh",
    "scripts/run_tests_parallel.py", "scripts/_fork_runner.py",
)


class Reason(str, Enum):
    """Why a file is in the affected selection, in priority order."""

    NAMED = "named"
    TOUCHED = "touched"
    IMPORTER = "importer"
    GATE = "gate"
    SAMPLE = "sample"


@dataclass(frozen=True)
class Pick:
    reason: Reason
    via: str  # the changed path (or the folder a sample stands for)
    source: str = ""  # importer: "record" or "ast"

    def line(self, rel: str) -> str:
        how = f" ({self.source})" if self.source else ""
        return f"  {self.reason.value}{how}: {rel}  <- {self.via}"


@dataclass(frozen=True)
class Record:
    """One file's recorded dependencies, as the selection reads them."""

    paths: frozenset  # every path its process opened while the file (or the session) was current
    own: frozenset  # what the file opened itself (its collection, its tests, its children)


@dataclass
class Affected:
    """The selection: one :class:`Pick` per selected file, and what it was taken from."""

    base: str
    changed: list[str]
    chain_paths: list[str]
    picks: dict[str, Pick] = field(default_factory=dict)
    by_rel: dict[str, Path] = field(default_factory=dict)
    candidates: int = 0
    records: int = 0
    seconds: float = 0.0
    skipped_red: list[Path] = field(default_factory=list)
    idle_box: list[Path] = field(default_factory=list)

    @property
    def selected(self) -> list[Path]:
        return sorted((self.by_rel[rel] for rel in self.picks), key=str)

    @property
    def chain(self) -> list[Path]:  # ``_print_expected_wall``'s chain test
        return [self.by_rel[rel] for rel, pick in self.picks.items() if pick.reason is Reason.SAMPLE]

    def counts(self) -> dict[str, int]:
        out = {reason.value: 0 for reason in Reason}
        for pick in self.picks.values():
            out[pick.reason.value] += 1
        return out

    def lines(self) -> list[str]:
        counts = ", ".join(f"{name} {n}" for name, n in self.counts().items())
        head = (
            f"Affected since {self.base} ({len(self.changed)} changed path(s)): {len(self.picks)} of "
            f"{self.candidates} file(s) selected ({counts}); {self.records} with a record, "
            f"{self.candidates - self.records} AST only; selected in {self.seconds:.1f}s"
        )
        out = [head]
        if self.chain_paths:
            out.append(f"  session chain: {', '.join(self.chain_paths)} — one sample per test folder")
        out += [self.picks[rel].line(rel) for rel in sorted(self.picks)]
        return out


def in_session_chain(rel: str) -> bool:
    """Loaded by, or deciding how, every test process: the chain or the runner."""

    return chain.in_chain(rel) or any(fnmatch.fnmatchcase(rel, g) for g in RUNNER_GLOBS)


def load_gate_paths(path: Path) -> dict[str, tuple[str, ...]]:
    """``<gate test file> <glob> [<glob> …]  # why`` per line; a missing list declares nothing."""

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2:
            out[fields[0]] = tuple(fields[1:])
    return out



# ── The import graph ────────────────────────────────────────────────────────


def records_from_store(store, rels: Iterable[str]) -> dict[str, Record]:
    """Each wanted file's newest record in the gate store.

    Its module sets are NOT read: a set is the union of every module the PROCESS had
    loaded by the file's end, its bundle-mates' included, so it over-reaches by the
    bundle (land/q2, 2026-10-16: 3,566 of 6,727 records name ``agent/provider_failure.py``
    in a module set, 49 opened it). The static import closure stands in for it."""

    wanted = set(rels)
    return {rel: Record(frozenset(d.paths), frozenset(d.keep)) for rel, d in store.load_deps().items() if rel in wanted}


class ImportGraph:
    """Static imports resolved to repo files. A file's direct imports are memoised by its
    blob and directory (``blob_of``; ``memo`` is the gate store's ``imports.jsonl``), so a
    run parses only the files that changed since the last one."""

    MEMO = "imports.jsonl"

    def __init__(self, repo_root: Path, blob_of: Optional[Callable[[str], str]] = None,
                 memo: Optional[dict[str, list[str]]] = None) -> None:
        self.root = Path(repo_root)
        self._blob_of = blob_of
        self.memo: dict[str, list[str]] = memo if memo is not None else {}
        self.fresh: dict[str, list[str]] = {}  # parsed this run: appended to the memo
        self._direct: dict[str, tuple[str, ...]] = {}
        self._exists: dict[str, bool] = {}

    def _is_file(self, rel: str) -> bool:
        found = self._exists.get(rel)
        if found is None:
            found = self._exists[rel] = (self.root / rel).is_file()
        return found

    def _resolve(self, module: str) -> list[str]:
        """``a.b.c`` → the repo files importing it loads: each package ``__init__`` and the module."""

        parts = module.split(".")
        out = []
        for depth in range(1, len(parts) + 1):
            base = "/".join(parts[:depth])
            for rel in (f"{base}/__init__.py", f"{base}.py"):
                if self._is_file(rel):
                    out.append(rel)
        return out

    def _modules(self, rel: str) -> list[str]:
        blob = self._blob_of(rel) if self._blob_of is not None else ""
        key = f"{blob}\t{rel.rsplit('/', 1)[0] if '/' in rel else ''}" if blob else ""
        if key in self.memo:
            return self.memo[key]
        mods = sorted(scope.imported_modules(self.root / rel, rel))
        if key:
            self.memo[key] = self.fresh[key] = mods
        return mods

    def direct(self, rel: str) -> tuple[str, ...]:
        found = self._direct.get(rel)
        if found is None:
            resolved = {r for m in self._modules(rel) for r in self._resolve(m)} - {rel}
            found = self._direct[rel] = tuple(sorted(resolved))
        return found

    def reaching(self, starts: Iterable[str], targets: Iterable[str]) -> dict[str, str]:
        """Every file reachable from ``starts`` that reaches a ``targets`` path, mapped to the
        target a breadth-first walk back from the sorted targets reached it from."""

        nodes: set[str] = set()
        stack = list(starts)
        while stack:
            node = stack.pop()
            if node not in nodes:
                nodes.add(node)
                stack.extend(self.direct(node))
        back: dict[str, list[str]] = {}
        for node in nodes:
            for dep in self.direct(node):
                back.setdefault(dep, []).append(node)
        via = {target: target for target in sorted(targets) if target in nodes}
        queue = list(via)
        for node in queue:
            for parent in back.get(node, ()):
                if parent not in via:
                    via[parent] = via[node]
                    queue.append(parent)
        return via


def load_import_memo(store_root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        lines = (Path(store_root) / ImportGraph.MEMO).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            record = json.loads(line)
            out[record["k"]] = list(record["m"])
        except (ValueError, KeyError, TypeError):
            continue  # a torn line from a killed run: that file is parsed again
    return out


def save_import_memo(store_root: Path, fresh: Mapping[str, list[str]]) -> None:
    if not fresh:
        return
    Path(store_root).mkdir(parents=True, exist_ok=True)
    with open(Path(store_root) / ImportGraph.MEMO, "a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps({"k": k, "m": m}) + "\n" for k, m in sorted(fresh.items())))


def conftests_above(rel: str) -> list[str]:
    parts = rel.split("/")[:-1]
    return [f"{'/'.join(parts[:i])}/conftest.py" if i else "conftest.py" for i in range(len(parts) + 1)]


def add_arguments(parser, change_group) -> None:
    change_group.add_argument(
        "--affected", metavar="BASE", default=None,
        help="the landing gate (owner ruling 2026-10-16): only the files `git diff BASE...HEAD` and the "
        "working tree can reach — touched, importers, declared gates, one sample per folder on a chain change",
    )
    parser.add_argument("--select-only", action="store_true", help="print the selection and exit; run nothing")


FLAGS = frozenset({"--affected", "--select-only"})


# ── The selection ───────────────────────────────────────────────────────────


def _hit(rel: str, record: Optional[Record], static: Optional[str], plain: set[str], chained: set[str]) -> Optional[str]:
    """The first changed path ``rel`` reaches: ``static`` (what its static import closure
    reaches — a session-chain path only when the file imports it itself), a ``conftest.py``
    above it, and, with a record, any path it opened (a chain path only when it opened it ITSELF)."""

    hits = {static} if static else set()
    hits |= {c for c in conftests_above(rel) if c in plain}
    if record is not None:
        hits |= (plain & record.paths) | (chained & record.own)
    return min(hits) if hits else None


def samples(rels: Iterable[str], size_of: Callable[[str], int]) -> dict[str, str]:
    """The smallest file of every test folder (ties by path): folder → rel."""

    best: dict[str, tuple[int, str]] = {}
    for rel in rels:
        folder = rel.rsplit("/", 1)[0] if "/" in rel else "."
        candidate = (size_of(rel), rel)
        if folder not in best or candidate < best[folder]:
            best[folder] = candidate
    return {folder: rel for folder, (_size, rel) in best.items()}


def select_affected(
    files: Sequence[Path], repo_root: Path, changed: Iterable[str], *, base: str,
    records: Mapping[str, Record], gates: Mapping[str, Sequence[str]],
    named: Iterable[Path] = (), skipped: Iterable[str] = (), idle_box: Iterable[str] = (),
    sample_pool: Optional[set[str]] = None, size_of: Optional[Callable[[str], int]] = None,
    graph: Optional[ImportGraph] = None,
) -> Affected:
    """``sample_pool``: the files the chain's samples are drawn from — ``select_for_run``
    passes the fork-owned files (``--scope fork`` with no change: the upstream manifest's
    files are left out), so a sample never runs an upstream file the normal gate would
    not; None draws from every candidate."""

    started = time.monotonic()
    root = Path(repo_root)
    changed = sorted(set(changed))
    chained = {rel for rel in changed if in_session_chain(rel)}
    plain = set(changed) - chained
    out = Affected(base, changed, sorted(chained))
    named_real = {Path(p).resolve() for p in named}
    skipped, idle = set(skipped), set(idle_box)
    graph = graph or ImportGraph(root)
    size_of = size_of or (lambda rel: (root / rel).stat().st_size)
    candidates: list[str] = []
    for path in files:
        rel = scope._rel_posix(path, root)
        out.by_rel[rel] = path
        is_named = path.resolve() in named_real
        if (rel in skipped or rel in idle) and not is_named:
            (out.skipped_red if rel in skipped else out.idle_box).append(path)
            continue
        candidates.append(rel)
        if is_named:
            out.picks[rel] = Pick(Reason.NAMED, "command line")
    out.candidates = len(candidates)
    out.records = sum(1 for rel in candidates if rel in records)
    gate_hits = {
        gate: min(hits) for gate, globs in gates.items()
        if (hits := [rel for rel in changed if any(fnmatch.fnmatchcase(rel, g) for g in globs)])
    }
    rest = [rel for rel in candidates if rel not in out.picks and rel not in plain and rel not in chained]
    statics = graph.reaching(rest, changed)
    for rel in candidates:
        if rel in out.picks:
            continue
        if rel in plain or rel in chained:
            out.picks[rel] = Pick(Reason.TOUCHED, rel)
            continue
        record = records.get(rel)
        hit = _hit(rel, record, statics.get(rel), plain, chained)
        if hit is not None:
            out.picks[rel] = Pick(Reason.IMPORTER, hit, "record+ast" if record is not None else "ast")
        elif rel in gate_hits:
            out.picks[rel] = Pick(Reason.GATE, gate_hits[rel])
    if chained:
        pool = [rel for rel in candidates if sample_pool is None or rel in sample_pool]
        for folder, rel in sorted(samples(pool, size_of).items()):
            out.picks.setdefault(rel, Pick(Reason.SAMPLE, folder + "/"))
    out.seconds = time.monotonic() - started
    return out


def select_for_run(args, files: list[Path], repo_root: Path, roots: list[Path], skip_rows, store) -> Optional[Affected]:
    """``main``'s ``--affected`` step: the selection, every line of it printed.
    ``None`` when git cannot say what changed (``main`` exits 2)."""

    started = time.monotonic()
    try:
        changed = scope.changed_paths(repo_root, args.affected)
        snapshot = cache.TreeSnapshot.take(repo_root, scope._scope_git)  # the import memo's blobs
        inherited = scope.load_manifest(getattr(args, "manifest", None) or repo_root / scope._DEFAULT_MANIFEST)
    except (OSError, RuntimeError) as exc:
        print(f"error: --affected cannot read the change or the upstream manifest: {exc}", file=sys.stderr)
        return None
    records = records_from_store(store, [scope._rel_posix(f, repo_root) for f in files])
    graph = ImportGraph(repo_root, snapshot.blob, load_import_memo(store.root))
    named = [r for r in roots if r.is_file()]
    idle_box = scope.load_path_list(repo_root / scope.IDLE_BOX_LIST)
    sel = select_affected(
        files, repo_root, changed, base=args.affected, records=records,
        gates=load_gate_paths(repo_root / GATE_PATHS_LIST), named=named, skipped=skip_rows, idle_box=idle_box,
        sample_pool={scope._rel_posix(f, repo_root) for f in files} - inherited, graph=graph,
    )
    save_import_memo(store.root, graph.fresh)
    sel.seconds = time.monotonic() - started  # the store read and the walk are part of the cost
    for line in sel.lines():
        print(line, flush=True)
    for path in sel.skipped_red:
        rel = scope._rel_posix(path, repo_root)
        print(f"  skipped (upstream skip list; name the file to run it): {rel}  # {skip_rows[rel].why}")
    if sel.idle_box:
        print(f"  idle-box: {len(sel.idle_box)} file(s) not run — scripts/run_tests_idle.sh, box idle (owner ruling 2026-10-10)")
    return sel
