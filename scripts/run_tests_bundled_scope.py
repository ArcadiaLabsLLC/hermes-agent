"""Which discovered files a bundled run executes (``--scope``).

Scope (``--scope``) decides which discovered files run at all. ``fork``, the
default and the fork's landing gate, runs every file absent from
``tests/fixtures/upstream_manifest.txt`` plus each inherited file the change
reaches (``select_scope``): the file itself changed, its convention-mapped
source (``tests/<pkg>/test_<mod>.py`` → ``<pkg>/<mod>.py``) changed, it imports
a changed module, or a ``conftest.py`` above it changed. The change is
``git diff --name-only <--since>...HEAD`` (default ``origin/main``) plus
working-tree edits; after a release merge it is ``--since-merge <merge>``
(``merge_change``: what the merge itself produced, plus what came after it,
less each conftest whose standing fork hunk the merge left unchanged). ``full`` runs everything discovered — the weekly upstream
merge lane, where the inherited set is the thing under test. In BOTH scopes a
file on ``tests/fixtures/upstream_skip_list.txt`` (upstream-owned reds and the
P0 freeze files) does not run unless it is named on the command line, and nor
does a file on ``scripts/test_idle_box_files.txt`` (the timing files that run
only on an idle box: ``scripts/run_tests_idle.sh``).

``scripts/run_tests_bundled.py`` owns execution and re-exports these names.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


def _rel_posix(path: Path, repo_root: Path) -> str:
    """Repo-relative POSIX spelling (``run_tests_parallel._format_file``'s answer)."""

    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


SCOPE_FORK = "fork"
SCOPE_FULL = "full"
_DEFAULT_MANIFEST = Path("tests") / "fixtures" / "upstream_manifest.txt"
_DEFAULT_SINCE = "origin/main"
#: files that run only on an idle box, serial (owner ruling 2026-10-10; design sweep D3.01)
IDLE_BOX_LIST = Path("scripts") / "test_idle_box_files.txt"


def load_path_list(path: Path) -> frozenset[str]:
    """Repo-relative POSIX paths a list file names: one per line, ``#`` starts a
    comment (the reason belongs on the path's line), blank lines ignored. A
    missing file names nothing."""

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    entries = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return frozenset(Path(entry).as_posix() for entry in entries if entry)


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


def _git(repo_root: Path, *args: str) -> str:
    """``git -C <repo_root> <args>``'s stdout. Raises ``RuntimeError`` when git
    cannot answer, so an unknown diff is never read as an empty one."""

    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _git_paths(repo_root: Path, *args: str) -> set[str]:
    return {Path(line.strip()).as_posix() for line in _git(repo_root, *args).splitlines() if line.strip()}


def changed_paths(repo_root: Path, since: str) -> set[str]:
    """Paths the work under test changed: ``git diff --name-only <since>...HEAD``
    plus the tracked working-tree edits (``git diff --name-only HEAD``). Raises
    ``RuntimeError`` when git cannot answer, so an unknown diff is never read
    as an empty one."""

    out: set[str] = set()
    for spec in ([f"{since}...HEAD"], ["HEAD"]):
        out |= _git_paths(repo_root, "diff", "--name-only", *spec)
    return out


def merge_parents(repo_root: Path, merge_sha: str) -> List[str]:
    """``merge_sha``'s parents; ``RuntimeError`` unless it is a merge HEAD descends from."""

    parents = _git(repo_root, "rev-list", "--parents", "-n", "1", merge_sha).split()[1:]
    if len(parents) < 2:
        raise RuntimeError(f"--since-merge {merge_sha} is not a merge commit")
    try:
        _git(repo_root, "merge-base", "--is-ancestor", merge_sha, "HEAD")
    except RuntimeError:
        raise RuntimeError(f"--since-merge {merge_sha} is not an ancestor of HEAD") from None
    return parents


def changed_paths_for_merge(repo_root: Path, merge_sha: str) -> set[str]:
    """The change a release merge's gate tests (D3.07): the paths whose blob
    differs from BOTH parents of ``merge_sha`` (git's combined diff — the
    merge's resolutions and the fork hunks it re-applied onto upstream's new
    versions), plus ``<merge>..HEAD`` (the ``fix(merge)`` commits) and the
    working-tree edits. An upstream change the merge took verbatim is not in
    it: upstream tested it at the tag, and ``--scope full`` remains the weekly
    lane's instrument for the whole inherited set."""

    _, merged, after = _merge_parts(repo_root, merge_sha)
    return merged | after


def _merge_parts(repo_root: Path, merge_sha: str) -> Tuple[List[str], set[str], set[str]]:
    """``(parents, combined-diff paths, paths changed after the merge)``."""

    parents = merge_parents(repo_root, merge_sha)
    merged = _git_paths(repo_root, "diff-tree", "-c", "--no-commit-id", "--name-only", "-r", merge_sha)
    return parents, merged, changed_paths(repo_root, merge_sha)


def _delta_lines(diff: str) -> List[str]:
    """The ``+``/``-`` lines of a one-file ``git diff -U0``: what it changes, not where."""

    lines = diff.splitlines()
    first_hunk = next((i for i, line in enumerate(lines) if line.startswith("@@")), len(lines))
    return [line for line in lines[first_hunk:] if line[:1] in ("+", "-")]


def conftest_hunk_unchanged(repo_root: Path, path: str, merge_sha: str) -> bool:
    """True when the fork's hunk in ``path`` is identical across the merge: the
    fork's delta at the previous upstream point (``merge-base(parent1, parent2)
    → parent1``) has the same ``+``/``-`` lines as its delta at the tag
    (``parent2 → merge``). The merge then re-applied the fork's hunk and changed
    nothing of it; upstream tested its own part at the tag."""

    parents = merge_parents(repo_root, merge_sha)
    base = _git(repo_root, "merge-base", parents[0], parents[1]).strip()

    def delta(old: str, new: str) -> List[str]:
        return _delta_lines(_git(repo_root, "diff", "-U0", "--no-color", "--no-ext-diff", old, new, "--", path))

    return delta(base, parents[0]) == delta(parents[1], merge_sha)


@dataclass
class MergeChange:
    """What ``--since-merge`` treats as changed, and what it left out (D3.07)."""

    merge: str
    merged: set[str]  # its combined diff: paths whose blob differs from BOTH parents
    after: set[str]  # ``<merge>..HEAD`` and working-tree edits
    first_parent: int  # paths of ``git diff <parent1> <merge>``, the spelling this replaces
    standing: List[str]  # conftests in ``merged`` whose fork hunk the merge left unchanged

    @property
    def paths(self) -> set[str]:
        return (self.merged | self.after) - set(self.standing)

    def account(self) -> str:
        return (
            f"Since merge {self.merge}: {len(self.merged)} path(s) in its combined diff (against its first "
            f"parent: {self.first_parent}) + {len(self.after)} after it; conftest(s) whose fork hunk the merge "
            f"left unchanged, not reaching: {', '.join(self.standing) or 'none'}"
        )


def merge_change(repo_root: Path, merge_sha: str) -> MergeChange:
    """``changed_paths_for_merge`` less each ``conftest.py`` the merge only
    re-applied a standing fork hunk to (``conftest_hunk_unchanged``) and nothing
    after the merge touched: such a conftest is "changed" against the tag
    forever, and would otherwise reach every upstream test below it."""

    parents, merged, after = _merge_parts(repo_root, merge_sha)
    standing = sorted(
        rel for rel in merged - after
        if rel.rsplit("/", 1)[-1] == "conftest.py" and conftest_hunk_unchanged(repo_root, rel, merge_sha)
    )
    first_parent = len(_git_paths(repo_root, "diff", "--name-only", parents[0], merge_sha))
    return MergeChange(merge_sha, merged, after, first_parent, standing)


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
    full: List[Path] = field(default_factory=list)  # --scope full: every other discovered file
    excluded: List[Path] = field(default_factory=list)
    skipped_red: List[Path] = field(default_factory=list)  # on the upstream skip list, not named
    idle_box: List[Path] = field(default_factory=list)  # on the idle-box list, not named

    @property
    def selected(self) -> List[Path]:
        return sorted(
            self.fork_only + self.touched + self.source + self.importer + self.conftest + self.named + self.full,
            key=lambda p: str(p),
        )


def select_scope(
    files: Sequence[Path],
    repo_root: Path,
    inherited: set[str],
    changed: set[str],
    named: Iterable[Path] = (),
    skipped: Iterable[str] = (),
    full: bool = False,
    idle_box: Iterable[str] = (),
) -> ScopeSelection:
    """The ``fork`` scope: every file NOT in ``inherited`` (the upstream
    manifest), plus each inherited file the change could reach — the file
    itself changed, the source its name maps to changed, it imports a changed
    module, or a ``conftest.py`` in one of its directories changed. Files named
    explicitly (not found by walking a directory) always run.

    A file on the upstream skip list (``skipped``) goes to ``skipped_red`` and
    nowhere else, in both scopes, unless it is named (owner ruling O1: skip
    wins over reach). A file on the idle-box list (``idle_box``) goes to
    ``idle_box`` the same way: it runs only when named, or on an idle box
    through ``scripts/run_tests_idle.sh`` (owner ruling 2026-10-10). ``full=True``
    puts every other file in ``full``."""

    named_real = {Path(p).resolve() for p in named}
    changed_modules = {m for m in (module_of(rel) for rel in changed) if m}
    changed_conftest_dirs = {rel.rsplit("/", 1)[0] for rel in changed if rel.endswith("/conftest.py")}
    skipped, idle_box = set(skipped), set(idle_box)
    sel = ScopeSelection()
    for path in files:
        rel = _rel_posix(path, repo_root)
        if rel in skipped and path.resolve() not in named_real:
            sel.skipped_red.append(path)
        elif rel in idle_box:
            (sel.named if path.resolve() in named_real else sel.idle_box).append(path)
        elif full:
            (sel.named if path.resolve() in named_real else sel.full).append(path)
        elif rel not in inherited:
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


def select_for_run(args, files: List[Path], repo_root: Path, roots: List[Path], skip_rows) -> Optional[ScopeSelection]:
    """``main``'s scope step: the selection for ``args.scope``, its one-line
    account printed, and every skip-listed file named. ``None`` when the fork
    scope cannot tell fork from inherited files (``main`` exits 2)."""

    named = [r for r in roots if r.is_file()]
    idle_box = load_path_list(repo_root / IDLE_BOX_LIST)
    if args.scope == SCOPE_FULL:
        sel = select_scope(files, repo_root, set(), set(), named=named, skipped=skip_rows, full=True, idle_box=idle_box)
    else:
        manifest = args.manifest or repo_root / _DEFAULT_MANIFEST
        try:
            inherited = load_manifest(manifest)
            if args.since_merge:
                merge = merge_change(repo_root, args.since_merge)
                changed, since = merge.paths, f"merge {args.since_merge}"
                print(merge.account(), flush=True)
            else:
                changed, since = changed_paths(repo_root, args.since), args.since
        except (OSError, RuntimeError) as exc:
            print(
                f"error: --scope fork cannot tell fork from inherited files: {exc}\n"
                "       fix the cause, or run --scope full",
                file=sys.stderr,
            )
            return None
        sel = select_scope(files, repo_root, inherited, changed, named=named, skipped=skip_rows, idle_box=idle_box)
        print(
            f"Scope fork (since {since}, {len(changed)} changed path(s)): {len(sel.fork_only)} fork-only + "
            f"{len(sel.selected) - len(sel.fork_only)} inherited reached by the change "
            f"(touched {len(sel.touched)}, source {len(sel.source)}, importer {len(sel.importer)}, "
            f"conftest {len(sel.conftest)}, named {len(sel.named)}); "
            f"{len(sel.excluded)} inherited left to --scope full",
            flush=True,
        )
    for path in sel.skipped_red:  # a run says what it did not run, and why
        rel = _rel_posix(path, repo_root)
        print(f"  skipped (upstream skip list; name the file to run it): {rel}  # {skip_rows[rel].why}")
    if sel.idle_box:
        print(f"  idle-box: {len(sel.idle_box)} file(s) not run — scripts/run_tests_idle.sh, box idle (owner ruling 2026-10-10)")
    return sel
