#!/usr/bin/env python3
"""W0-D — the reach census: code in the god files no traced test reaches.

Plan: ``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md``
§2 Wave 0 (W0-D) and §4.3; ``god-file-program-2026-09-24.md`` §5. Its output is
the second half of the dead-code list — rows in
``Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md``.

An INSTRUMENT, not a gate: nothing reads its exit code.

The population is ``scripts/god_file_probe.py``'s: every fork production file
over 800 RAW lines (the owner's list — the census is about the files the
program opens, not only the ceiling population). The suite is enumerated from
the tree too: every tracked test file that names ``agent_runtime``,
``hermes_cli.harness`` / ``harness_parts``, or the dotted module or repo path
of a population file. It is traced through ``scripts/run_tests.sh`` with the
one variable that runner forwards for coverage (``HERMES_TEST_COVERAGE_RC``),
exactly as ``scripts/unreachable_branch_report.py`` does — whose helpers this
reuses rather than re-spelling the hermetic environment.

It lists, per file:

* **cold functions** — a function or method of >= 10 lines none of whose body
  lines executed (the outermost cold unit only; its nested defs are inside it);
* **cold arms** — an ``if``/``elif``/``else`` arm of >= 10 lines inside a
  function that DID run, whose test line executed and whose body never did.

A function row is STRUCK before it is filed when the fork's production tree
reaches the symbol statically (``ReachIndex``: registered via
``set_defaults(func=…)`` or a registering decorator, passed as a value,
called from its own file, or imported and used); struck rows are listed apart
with the reference that reaches them. Every row in a file that runs in a child
process (``SUBPROCESS_ENTRIES``, or a ``__main__`` guard) says so. Lane
Q-DEAD-B, 2026-09-25, after lane Q-DEAD-A refuted 45 of 45 harness rows the
unfiltered census filed; ``--no-static-reach`` is the unfiltered census.

**0 hits is not dead.** Field-only paths (Windows-only, service-mode,
peer-only), and anything a test OUTSIDE the traced suite reaches, read the same
way. Each row is ruled by the lane that owns its file (plan §4.3): delete,
field-only (kept, the field proof named) or untested live code (kept, a test
owed).

  python scripts/refactor_reach_census.py --keep-json .lane-logs/reach.json
  python scripts/refactor_reach_census.py --coverage-json .lane-logs/reach.json --out <md>
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import god_file_probe as probe  # noqa: E402
from scripts.unreachable_branch_report import (  # noqa: E402
    DEFAULT_FILE_TIMEOUT,
    DEFAULT_TEST_TIMEOUT,
    _combine_and_dump,
    _run_suite,
)

MIN_UNIT_LINES = 10
BROAD_TOKENS = ("agent_runtime", "hermes_cli.harness", "harness_parts")


def population(root: Path = ROOT) -> list[str]:
    return sorted(
        p for p in probe.fork_production_files(root) if probe.raw_lines(probe._source(root, p)) > probe.CEILING_CODE_LINES
    )


def suite(root: Path, files: list[str]) -> list[str]:
    """Tracked test files that name the population (broad tokens, dotted modules, script stems)."""
    tokens = set(BROAD_TOKENS)
    for path in files:
        tokens.add(probe.module_name(path))
        tokens.add(path)
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/**/test_*.py", "tests/test_*.py"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.split("\0")
    chosen = []
    for test in sorted(p for p in listing if p):
        text = (root / test).read_text(encoding="utf-8", errors="replace")
        if any(token in text for token in tokens):
            chosen.append(test)
    return chosen


def _coverage_rc(workspace: Path, data_file: Path, files: list[str]) -> Path:
    body = ["[run]", "branch = true", "parallel = true", "relative_files = true", f"data_file = {data_file}", "include ="]
    body += [f"    */{path}" for path in files]
    rc = workspace / "coveragerc"
    rc.write_text("\n".join(body) + "\n", encoding="utf-8")
    return rc


def trace(root: Path, files: list[str], tests: list[str], jobs: int | None) -> tuple[dict, int]:
    with tempfile.TemporaryDirectory(prefix="hermes-reach-census-") as tmp:
        workspace = Path(tmp)
        data_file = workspace / "coverage-data"
        rc = _coverage_rc(workspace, data_file, files)
        code = _run_suite(rc, tests, jobs, DEFAULT_TEST_TIMEOUT, DEFAULT_FILE_TIMEOUT)
        return _combine_and_dump(rc, data_file, workspace / "coverage.json"), code


@dataclass(frozen=True)
class Row:
    path: str
    unit: str
    kind: str  # "function" | "arm"
    start: int
    end: int
    entry: str | None = None  # the child-process entry the file runs under, when the trace cannot enter it
    struck: str | None = None  # the static-reach arm that reaches it; a struck row is never filed

    @property
    def lines(self) -> int:
        return self.end - self.start + 1

    def census_line(self) -> str:
        line = f"{self.path}:{self.start}-{self.end} {self.unit} {self.kind} {self.lines} lines, 0 hits"
        line += f" — runs under {self.entry}" if self.entry else ""
        return line + (f" — STRUCK, {self.struck}" if self.struck else "")


# ── static reach: what a tracer cannot see ───────────────────────────────────
#
# A traced "0 hits" says the SUITE never ran a symbol, not that nothing calls
# it. Lane Q-DEAD-A (2026-09-25) refuted 45 of 45 harness-family rows the first
# census filed: parser handlers, keyword-injected callables, own-file callees,
# and a whole package that runs in a child process. So a FUNCTION row is struck
# before it is filed when the fork's production tree references the symbol in
# one of four ways (the ``ARM_*`` names below). A symbol only a TEST references
# stays a row — that is a TEST SEAM, which the queue wants. Arms (``if`` rows)
# are not symbols and are never struck; they are tagged like every other row.
# The walk matches names and over-approximates on purpose: striking a live
# symbol costs nothing, filing one costs a lane to refute.

#: Decorators that wrap or describe a function without handing it to a caller.
#: Any OTHER decorator (``@method("…")``, ``@pytest.fixture``,
#: ``@registry.register``) is read as a registration.
NON_REGISTERING_DECORATORS = frozenset({
    "abstractmethod", "asynccontextmanager", "cache", "cached_property", "classmethod", "contextmanager",
    "dataclass", "deleter", "final", "lru_cache", "overload", "override", "property", "setter",
    "staticmethod", "total_ordering", "wraps",
})

#: Trees that run inside a CHILD process the trace never enters, and the entry
#: that starts it. Their rows are still filed, and say so. A module with an
#: ``if __name__ == "__main__"`` guard is tagged too (derived, not listed here).
SUBPROCESS_ENTRIES = (
    ("hermes_cli/harness_parts/serve/", "serve child process (`hermes harness serve`)"),
    ("mcp_serve.py", "MCP server process (`hermes mcp serve`)"),
    ("agent/transports/hermes_tools_mcp_server.py", "MCP tools server process"),
)

ARM_REGISTERED = "registered"  # (a) set_defaults(func=…) or a registering decorator
ARM_PASSED = "passed as a value"  # (b) keyword/positional argument, table entry, assignment
ARM_OWN_CALL = "called from its own file"  # (c) outside its own body
ARM_IMPORTED = "imported"  # (d) by name or through its module, and used


def _reach_dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _reach_leaf(node: ast.AST) -> str | None:
    dotted = _reach_dotted(node)
    return dotted.rsplit(".", 1)[-1] if dotted else None


@dataclass(frozen=True)
class Ref:
    path: str
    line: int
    name: str  # the leaf name
    dotted: str  # the spelling at the site, its import alias resolved
    called: bool


def _reach_aliases(path: str, tree: ast.Module) -> dict[str, str]:
    """Local name -> the dotted module or symbol it binds, for every import in the file."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            base = probe._resolve_from(path, node)
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{base}.{alias.name}"
    return aliases


def _reach_refs(path: str, tree: ast.Module) -> list[Ref]:
    """Every Name/Attribute load that is a whole reference (not the base of a longer one)."""
    aliases = _reach_aliases(path, tree)
    bases = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    callees = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    refs = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.Attribute)) or id(node) in bases:
            continue
        dotted = _reach_dotted(node)
        if dotted is None or not isinstance(node.ctx, ast.Load):
            continue
        head, _, rest = dotted.partition(".")
        resolved = aliases.get(head, head) + (f".{rest}" if rest else "")
        refs.append(Ref(path, node.lineno, dotted.rsplit(".", 1)[-1], resolved, id(node) in callees))
    return refs


def _reach_registrations(tree: ast.Module) -> tuple[set[str], set[int]]:
    """Names handed to ``set_defaults(func=…)``, and the def lines a registering decorator wraps."""
    handlers: set[str] = set()
    decorated: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _reach_leaf(node.func) == "set_defaults":
            handlers.update(_reach_leaf(k.value) or "" for k in node.keywords if k.arg == "func")
        elif isinstance(node, probe._FUNCS):
            targets = [d.func if isinstance(d, ast.Call) else d for d in node.decorator_list]
            if any(_reach_leaf(t) not in NON_REGISTERING_DECORATORS for t in targets):
                decorated.add(node.lineno)
    handlers.discard("")
    return handlers, decorated


def _reach_used_imports(path: str, tree: ast.Module) -> set[str]:
    """``module.name`` for every from-import whose bound name the file then LOADS (a bare re-export is no use)."""
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = probe._resolve_from(path, node)
            out.update(f"{base}.{a.name}" for a in node.names if (a.asname or a.name) in loaded)
    return out


def _reach_main_guarded(tree: ast.Module) -> bool:
    for stmt in tree.body:
        test = stmt.test if isinstance(stmt, ast.If) else None
        if isinstance(test, ast.Compare) and _reach_dotted(test.left) == "__name__":
            return any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators)
    return False


class ReachIndex:
    """The production references of the fork tree, built once, asked once per function row."""

    def __init__(self, root: Path, files: Iterable[str]):
        self.refs: dict[str, list[Ref]] = defaultdict(list)
        self.handlers: dict[str, str] = {}
        self.decorated: set[tuple[str, int]] = set()
        self.imports: dict[str, list[str]] = defaultdict(list)
        self.main_guarded: set[str] = set()
        for path in files:
            tree = probe._tree(root, path)
            if tree is None:
                continue
            for ref in _reach_refs(path, tree):
                self.refs[ref.name].append(ref)
            handlers, decorated = _reach_registrations(tree)
            for name in handlers:
                self.handlers.setdefault(name, path)
            self.decorated.update((path, line) for line in decorated)
            for dotted in _reach_used_imports(path, tree):
                self.imports[dotted].append(path)
            if _reach_main_guarded(tree):
                self.main_guarded.add(path)

    def strike(self, path: str, qualname: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        """The first arm that reaches the symbol statically, as ``arm: where``; None when nothing does."""
        name = node.name
        first, last = node.lineno, node.end_lineno or node.lineno
        if name in self.handlers or (path, node.lineno) in self.decorated:
            return f"{ARM_REGISTERED}: {self.handlers.get(name, f'{path}:{node.lineno}')}"
        outside = [r for r in self.refs.get(name, ()) if r.path != path or not first <= r.line <= last]
        passed = next((r for r in outside if not r.called), None)
        if passed is not None:
            return f"{ARM_PASSED}: {passed.path}:{passed.line}"
        own = next((r for r in outside if r.called and r.path == path), None)
        if own is not None:
            return f"{ARM_OWN_CALL}: {path}:{own.line}"
        return None if "." in qualname else self._imported(path, name)

    def _imported(self, path: str, name: str) -> str | None:
        module = probe.module_name(path)
        for depth in range(module.count(".") + 1):
            importers = [p for p in self.imports.get(f"{module.rsplit('.', depth)[0]}.{name}", ()) if p != path]
            if importers:
                return f"{ARM_IMPORTED}: {importers[0]}"
        via = next((r for r in self.refs.get(name, ()) if r.path != path and r.dotted == f"{module}.{name}"), None)
        return f"{ARM_IMPORTED}: {via.path}:{via.line}" if via else None

    def entry(self, path: str) -> str | None:
        """The child-process entry ``path`` runs under, if any."""
        for prefix, label in SUBPROCESS_ENTRIES:
            if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
                return label
        return "script entry (`__main__` guard, run as a process)" if path in self.main_guarded else None


def _executed(document: dict, path: str) -> set[int] | None:
    for name, entry in document.get("files", {}).items():
        if name.replace("\\", "/").endswith(path):
            return set(entry.get("executed_lines", []))
    return None


def _span_hit(executed: set[int], start: int, end: int) -> bool:
    return any(start <= line <= end for line in executed)


def _arms(node: ast.If) -> list[tuple[str, int, int, int]]:
    """``(label, test line, first body line, last body line)`` for each arm of an if-chain."""
    out, cur, label = [], node, "if"
    while True:
        out.append((label, cur.test.lineno, cur.body[0].lineno, cur.body[-1].end_lineno or cur.body[-1].lineno))
        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur, label = cur.orelse[0], "elif"
            continue
        if cur.orelse:
            out.append(("else", cur.test.lineno, cur.orelse[0].lineno, cur.orelse[-1].end_lineno or cur.orelse[-1].lineno))
        return out


def rows_for(root: Path, path: str, executed: set[int], reach: ReachIndex | None = None) -> list[Row]:
    """Every cold unit of ``path``; with ``reach``, function rows it reaches carry ``struck`` and all carry ``entry``."""
    tree = probe._tree(root, path)
    if tree is None:
        return []
    entry = reach.entry(path) if reach else None
    rows: list[Row] = []
    cold_spans: list[tuple[int, int]] = []
    for unit in probe.iter_units(path, tree):
        node = unit.node
        start, end = node.body[0].lineno, node.end_lineno or node.lineno
        if any(a <= node.lineno and end <= b for a, b in cold_spans):
            continue
        if unit.lines >= MIN_UNIT_LINES and not _span_hit(executed, start, end):
            struck = reach.strike(path, unit.qualname, node) if reach else None
            rows.append(Row(path, unit.qualname, "function", node.lineno, end, entry, struck))
            cold_spans.append((node.lineno, end))
            continue
        if not _span_hit(executed, start, end):
            continue
        orelse_ifs = {id(o) for n in ast.walk(node) if isinstance(n, ast.If) for o in n.orelse if isinstance(o, ast.If)}
        for child in probe._own_statements(node):
            if not isinstance(child, ast.If) or id(child) in orelse_ifs:
                continue
            for label, test_line, first, last in _arms(child):
                if last - first + 1 >= MIN_UNIT_LINES and test_line in executed and not _span_hit(executed, first, last):
                    rows.append(Row(path, f"{unit.qualname} [{label} @{test_line}]", "arm", first, last, entry))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage-json", type=Path, help="analyse this coverage json instead of tracing")
    parser.add_argument("--keep-json", type=Path, help="write the traced coverage json here")
    parser.add_argument("--out", type=Path, help="write the census lines (markdown) here")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    parser.add_argument("--list-suite", action="store_true")
    parser.add_argument(
        "--no-static-reach", action="store_true", help="file every cold unit (the pre-2026-09-25 census, for a before count)"
    )
    args = parser.parse_args(argv)
    root = ROOT
    files = population(root)
    tests = suite(root, files)
    if args.list_suite:
        print("\n".join(tests))
        print(f"{len(tests)} test files over {len(files)} population files")
        return 0
    suite_code = 0
    if args.coverage_json:
        document = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        suite_code = int(document.get("_suite_exit", 0))
    else:
        document, suite_code = trace(root, files, tests, args.jobs)
        document["_suite_exit"] = suite_code
        if args.keep_json:
            args.keep_json.write_text(json.dumps(document), encoding="utf-8")
    reach = None if args.no_static_reach else ReachIndex(root, probe.fork_production_files(root))
    rows: list[Row] = []
    untraced: list[str] = []
    for path in files:
        executed = _executed(document, path)
        if executed is None:
            untraced.append(path)
            continue
        rows.extend(rows_for(root, path, executed, reach))
    text = render(rows, untraced, len(files), len(tests), suite_code)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    filed = [r for r in rows if not r.struck]
    print(
        f"[reach] rows={len(filed)} struck={len(rows) - len(filed)} functions={sum(r.kind == 'function' for r in filed)} "
        f"arms={sum(r.kind == 'arm' for r in filed)} subprocess={sum(bool(r.entry) for r in filed)} "
        f"files={len(files)} untraced={len(untraced)} suite_exit={suite_code}"
    )
    return 0


def render(rows: list[Row], untraced: list[str], files: int, tests: int, suite_code: int) -> str:
    """The census note body: the filed rows, then the struck ones with the arm that reaches each."""
    filed = [r for r in rows if not r.struck]
    struck = [r for r in rows if r.struck]
    header = [
        f"# reach census — {len(filed)} rows over {files} files, {tests} traced test files, suite exit {suite_code}"
        f" ({len(struck)} struck by static reach)",
        "",
        "0 hits under the traced suite is NOT dead: field-only paths and code a test outside this suite reaches read the same way.",
        "",
    ]
    if untraced:
        header += [f"untraced (no test imported the file): {', '.join(untraced)}", ""]
    body = [row.census_line() for row in filed]
    if struck:
        body += ["", f"## struck by static reach ({len(struck)}) — a production reference the trace cannot see", ""]
        body += [row.census_line() for row in struck]
    return "\n".join(header + body) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
