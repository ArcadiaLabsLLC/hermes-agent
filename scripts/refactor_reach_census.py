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
from dataclasses import dataclass
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

    @property
    def lines(self) -> int:
        return self.end - self.start + 1

    def census_line(self) -> str:
        return f"{self.path}:{self.start}-{self.end} {self.unit} {self.kind} {self.lines} lines, 0 hits"


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


def rows_for(root: Path, path: str, executed: set[int]) -> list[Row]:
    tree = probe._tree(root, path)
    if tree is None:
        return []
    rows: list[Row] = []
    cold_spans: list[tuple[int, int]] = []
    for unit in probe.iter_units(path, tree):
        node = unit.node
        start, end = node.body[0].lineno, node.end_lineno or node.lineno
        if any(a <= node.lineno and end <= b for a, b in cold_spans):
            continue
        if unit.lines >= MIN_UNIT_LINES and not _span_hit(executed, start, end):
            rows.append(Row(path, unit.qualname, "function", node.lineno, end))
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
                    rows.append(Row(path, f"{unit.qualname} [{label} @{test_line}]", "arm", first, last))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage-json", type=Path, help="analyse this coverage json instead of tracing")
    parser.add_argument("--keep-json", type=Path, help="write the traced coverage json here")
    parser.add_argument("--out", type=Path, help="write the census lines (markdown) here")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    parser.add_argument("--list-suite", action="store_true")
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
    rows: list[Row] = []
    untraced: list[str] = []
    for path in files:
        executed = _executed(document, path)
        if executed is None:
            untraced.append(path)
            continue
        rows.extend(rows_for(root, path, executed))
    header = [
        f"# reach census — {len(rows)} rows over {len(files)} files, {len(tests)} traced test files, suite exit {suite_code}",
        "",
        "0 hits under the traced suite is NOT dead: field-only paths and code a test outside this suite reaches read the same way.",
        "",
    ]
    if untraced:
        header += [f"untraced (no test imported the file): {', '.join(untraced)}", ""]
    body = [row.census_line() for row in rows]
    text = "\n".join(header + body) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    print(
        f"[reach] rows={len(rows)} functions={sum(r.kind == 'function' for r in rows)} "
        f"arms={sum(r.kind == 'arm' for r in rows)} files={len(files)} untraced={len(untraced)} suite_exit={suite_code}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
