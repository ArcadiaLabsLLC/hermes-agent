"""Which tests see ``load_config_readonly`` defer to a patched ``load_config`` — from the ledger.

The fork moved some upstream readers from ``hermes_cli.config.load_config`` to
``load_config_readonly`` (an import must not scaffold the home). Upstream's tests of
those readers patch ``load_config``; the read-through fixture in
``tests/_downstream/conftest_plugin.py`` lets that patch reach the reader. Which
tests get it is computed, not hand-kept (plan ``design-sweep-d3-2026-10-10.md`` D3.06):

1. WHICH readers: the upstream-footprint ledger rows whose reason carries
   :data:`READER_MOVED` — the ledger is the one source; no constant mirror.
2. WHICH tests: a test file that imports a reader module, or imports a repo module that
   imports one (one hop of the AST import graph,
   ``scripts/run_tests_bundled.py::imported_modules``). The full transitive closure
   reaches 6,135 of 6,601 test files (measured 2026-10-10) and would be the blanket
   read-through the D3.06 design refuses; one hop reaches 832.
3. WHEN: only while ``hermes_cli.config.load_config`` is not its own definition (an
   upstream patch is in place) — decided at call time by the fixture.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "docs" / "agent-runtime-harness" / "planned" / "upstream-footprint-ledger.md"

#: The spelling a ledger row uses to say the fork moved an upstream reader to the
#: readonly loader. ``tests/scripts/test_upstream_footprint.py`` holds rows to it.
READER_MOVED = "reader moved to `load_config_readonly`"

_ROW_PATH = re.compile(r"^\|\s*`([^`]+\.py)`\s*\|")


def readers_from_ledger(text: str) -> frozenset[str]:
    """Module names of the ledger rows whose reason carries :data:`READER_MOVED`."""
    modules = set()
    for line in text.splitlines():
        match = _ROW_PATH.match(line)
        if match and READER_MOVED in line:
            path = match[1][: -len(".py")]
            modules.add(path[: -len("/__init__")] if path.endswith("/__init__") else path)
    return frozenset(module.replace("/", ".") for module in modules)


@functools.lru_cache(maxsize=1)
def fork_readonly_readers() -> frozenset[str]:
    """:func:`readers_from_ledger` over the committed ledger, read once per process."""
    return readers_from_ledger(LEDGER.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _module_file(module: str) -> Path | None:
    base = REPO_ROOT.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _repo_modules(names: set[str]) -> set[str]:
    """Every repo module a set of imported names loads (``a.b.c`` also loads ``a`` and ``a.b``)."""
    out = set()
    for name in names:
        parts = name.split(".")
        for end in range(1, len(parts) + 1):
            prefix = ".".join(parts[:end])
            if _module_file(prefix) is not None:
                out.add(prefix)
    return out


def _imports_of(path: Path) -> set[str]:
    from scripts.run_tests_bundled import imported_modules  # lazy: the runner module costs ~0.2 s

    rel = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.name
    return _repo_modules(imported_modules(path, rel))


@functools.lru_cache(maxsize=None)
def _module_imports(module: str) -> frozenset[str]:
    path = _module_file(module)
    return frozenset(_imports_of(path)) if path is not None else frozenset()


def reaches_a_reader(direct: set[str], readers: frozenset[str]) -> bool:
    """True when ``direct`` (a test file's repo imports) or one hop past it names a reader."""
    if direct & readers:
        return True
    return any(_module_imports(module) & readers for module in direct)


@functools.lru_cache(maxsize=None)
def file_reads_through(path: str) -> bool:
    """Whether the test file at ``path`` imports a fork-moved reader within one hop."""
    readers = fork_readonly_readers()
    return bool(readers) and reaches_a_reader(_imports_of(Path(path).resolve()), readers)


_ADDED_READONLY_IMPORT = re.compile(
    r"^\+(?!\+\+).*(?:from\s+hermes_cli\.config\s+import\s+[^#\n]*\bload_config_readonly\b"
    r"|hermes_cli\.config\.load_config_readonly\b)")


def readonly_reader_moves(diff_text: str) -> set[str]:
    """Paths whose diff ADDS an import of ``hermes_cli.config.load_config_readonly``.

    Over-approximates a reader move (a new import is how the fork moves a reader off
    ``load_config``); the ledger rows of these paths must carry :data:`READER_MOVED`.
    """
    moves, path = set(), None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[len("+++ b/"):] if line.startswith("+++ b/") else None
        elif path and _ADDED_READONLY_IMPORT.match(line):
            moves.add(path)
    return moves
