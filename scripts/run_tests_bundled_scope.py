"""Which discovered files a bundled run executes (``--scope``).

Scope (``--scope``) decides which discovered files run at all. ``fork``, the
default and the fork's landing gate, runs every file absent from
``tests/fixtures/upstream_manifest.txt`` plus each inherited file the change
reaches (``select_scope``): the file itself changed, its convention-mapped
source (``tests/<pkg>/test_<mod>.py`` → ``<pkg>/<mod>.py``) changed, it imports
a changed module, or a ``conftest.py`` above it changed. The change is
``git diff --name-only <--since>...HEAD`` (default ``origin/main``) plus
working-tree edits. ``full`` runs everything discovered — the weekly upstream
merge lane, where the inherited set is the thing under test. In BOTH scopes a
file on ``tests/fixtures/upstream_skip_list.txt`` (upstream-owned reds and the
P0 freeze files) does not run unless it is named on the command line.

``scripts/run_tests_bundled.py`` owns execution and re-exports these names.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


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
    full: List[Path] = field(default_factory=list)  # --scope full: every other discovered file
    excluded: List[Path] = field(default_factory=list)
    skipped_red: List[Path] = field(default_factory=list)  # on the upstream skip list, not named

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
) -> ScopeSelection:
    """The ``fork`` scope: every file NOT in ``inherited`` (the upstream
    manifest), plus each inherited file the change could reach — the file
    itself changed, the source its name maps to changed, it imports a changed
    module, or a ``conftest.py`` in one of its directories changed. Files named
    explicitly (not found by walking a directory) always run.

    A file on the upstream skip list (``skipped``) goes to ``skipped_red`` and
    nowhere else, in both scopes, unless it is named (owner ruling O1: skip
    wins over reach). ``full=True`` puts every other file in ``full``."""

    named_real = {Path(p).resolve() for p in named}
    changed_modules = {m for m in (module_of(rel) for rel in changed) if m}
    changed_conftest_dirs = {rel.rsplit("/", 1)[0] for rel in changed if rel.endswith("/conftest.py")}
    skipped = set(skipped)
    sel = ScopeSelection()
    for path in files:
        rel = _rel_posix(path, repo_root)
        if rel in skipped and path.resolve() not in named_real:
            sel.skipped_red.append(path)
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
    if args.scope == SCOPE_FULL:
        sel = select_scope(files, repo_root, set(), set(), named=named, skipped=skip_rows, full=True)
    else:
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
            return None
        sel = select_scope(files, repo_root, inherited, changed, named=named, skipped=skip_rows)
        print(
            f"Scope fork (since {args.since}, {len(changed)} changed path(s)): {len(sel.fork_only)} fork-only + "
            f"{len(sel.selected) - len(sel.fork_only)} inherited reached by the change "
            f"(touched {len(sel.touched)}, source {len(sel.source)}, importer {len(sel.importer)}, "
            f"conftest {len(sel.conftest)}, named {len(sel.named)}); "
            f"{len(sel.excluded)} inherited left to --scope full",
            flush=True,
        )
    for path in sel.skipped_red:  # a run says what it did not run, and why
        rel = _rel_posix(path, repo_root)
        print(f"  skipped (upstream skip list; name the file to run it): {rel}  # {skip_rows[rel].why}")
    return sel
