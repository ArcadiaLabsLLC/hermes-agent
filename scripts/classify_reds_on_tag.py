#!/usr/bin/env python3
"""Classify the fork's red node ids against a pure upstream release tag.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §6; runbook:
``Harness_Brain/50 — Agent Handoffs/Merging upstream.md`` step 5d.

A red on the fork's main is one of: red on the pure tag (upstream's own -- a strict
``_up_red`` row in a new ``upstream_reds_<tag>.py``), a whole-file failure on the tag (a
skip-list row), green on the tag (fork-caused, or a flake), nondeterministic on the tag
(a skip-list ``upstream:`` row, never a strict xfail), or absent on the tag (a fork test or
a renamed node). The tag worktree has no fork code, so it IS upstream's behaviour; the
authority for "red" is the tag's own ``scripts/run_tests.sh`` (one file per process).

Prints by default (owner ruling Q7); ``--write`` creates a NEW table module only.
"""

from __future__ import annotations

import argparse
import enum
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

#: ``FAILED <nodeid>`` / ``ERROR <nodeid>`` short-summary lines, with or without the
#: runner's ``  ║ `` live-failure prefix and pytest's `` - <message>`` suffix.
_SUMMARY = re.compile(r"^(?:\s*║\s?)?(FAILED|ERROR) (\S.*)$")
#: the runner's per-file header in its ``=== Failure output ===`` section
_FILE_HEADER = re.compile(r"^--- (\S.*\.py) ---$")


class Verdict(str, enum.Enum):
    UPSTREAM_RED = "UPSTREAM_RED"  # red on every tag run -> strict _up_red row
    UPSTREAM_COLLECT_ERROR = "UPSTREAM_COLLECT_ERROR"  # the whole file fails on the tag -> skip-list row
    FORK_CAUSED_OR_FLAKY = "FORK_CAUSED_OR_FLAKY"  # green on every tag run
    NONDETERMINISTIC_ON_TAG = "NONDETERMINISTIC_ON_TAG"  # red on some tag runs -> skip-list upstream: row
    ABSENT_ON_TAG = "ABSENT_ON_TAG"  # the node (or its file) does not exist at the tag


class Outcome(enum.Enum):
    RED = "red"
    PASS = "pass"
    FILE_RED = "file-red"  # the file failed with no node line of its own (collection, crash, timeout)


@dataclass(frozen=True)
class TagRun:
    """One run of the tag's runner: the node ids it named red and the files it named failed."""

    red_nodes: frozenset
    red_files: frozenset


@dataclass(frozen=True)
class Presence:
    """What exists at the tag: collected node ids, files failing collection, missing files."""

    nodes: frozenset
    collect_errors: frozenset
    missing_files: frozenset


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _nodeid_of(rest: str) -> str:
    """Strip pytest's `` - <message>`` suffix without cutting a parametrize id."""

    head, bracket, _ = rest.partition("[")
    if bracket and " " not in head:
        depth = 0
        for i, ch in enumerate(rest):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return rest[: i + 1]
    return rest.split(" - ", 1)[0].strip()


def parse_run_output(text: str) -> TagRun:
    nodes: set = set()
    files: set = set()
    for line in text.splitlines():
        header = _FILE_HEADER.match(line.strip())
        if header:
            files.add(header.group(1).replace("\\", "/"))
            continue
        match = _SUMMARY.match(line)
        if match:
            node = _nodeid_of(match.group(2)).replace("\\", "/")
            if node.startswith("tests/"):
                nodes.add(node)
                files.add(file_of(node))
    return TagRun(frozenset(nodes), frozenset(files))


def outcome(node: str, run: TagRun) -> Outcome:
    if node in run.red_nodes:
        return Outcome.RED
    path = file_of(node)
    if path in run.red_nodes:  # ``ERROR tests/x.py`` -- a collection error line
        return Outcome.FILE_RED
    if path in run.red_files and not any(n.startswith(path + "::") for n in run.red_nodes):
        return Outcome.FILE_RED
    return Outcome.PASS


def classify(nodes: Iterable[str], runs: Sequence[TagRun], presence: Presence) -> Dict[str, Verdict]:
    verdicts: Dict[str, Verdict] = {}
    for node in sorted(set(nodes)):
        path = file_of(node)
        if path in presence.missing_files:
            verdicts[node] = Verdict.ABSENT_ON_TAG
        elif path in presence.collect_errors:
            verdicts[node] = Verdict.UPSTREAM_COLLECT_ERROR
        elif node not in presence.nodes:
            verdicts[node] = Verdict.ABSENT_ON_TAG
        else:
            seen = frozenset(outcome(node, run) for run in runs)
            verdicts[node] = _VERDICT_BY_OUTCOMES.get(seen, Verdict.NONDETERMINISTIC_ON_TAG)
    return verdicts


#: The set of outcomes a node showed across the tag runs -> its verdict; any mix is
#: nondeterministic on the tag.
_VERDICT_BY_OUTCOMES: Dict[frozenset, Verdict] = {
    frozenset({Outcome.RED}): Verdict.UPSTREAM_RED,
    frozenset({Outcome.FILE_RED}): Verdict.UPSTREAM_COLLECT_ERROR,
    frozenset({Outcome.PASS}): Verdict.FORK_CAUSED_OR_FLAKY,
    frozenset(): Verdict.FORK_CAUSED_OR_FLAKY,
}


def slug(tag: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", tag).lower()


def _host_words(platform: str) -> tuple:
    return ("Windows", "_WIN") if platform == "win32" else ("POSIX", "not _WIN")


def emit_table(verdicts: Mapping[str, Verdict], tag: str, sha: str, date: str, platform: str = sys.platform) -> str:
    """An ``upstream_reds_<slug>.py`` module in the shape of ``upstream_reds_v0216.py``."""

    host, guard = _host_words(platform)
    reds = sorted(n for n, v in verdicts.items() if v is Verdict.UPSTREAM_RED)
    body = "".join(f"        {node!r},\n" for node in reds)
    return (
        f'"""Rows ({platform} only): upstream\'s OWN {host} reds at release tag {tag} -- retired by an upstream fix.\n'
        "\n"
        f"Every id here was red on every run of the pure tag ``{tag}`` (``{sha}``, a detached worktree, no\n"
        "fork code) AND red on the fork's main. Written by ``scripts/classify_reds_on_tag.py``; a\n"
        "per-test strict xfail, so an upstream fix turns the row into an XPASS(strict) red that\n"
        "retires it. Register the table in ``hooks._merge`` and the map\n"
        "``tests/_downstream/id_markers/__init__.py``.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import pytest\n"
        "\n"
        "from tests._downstream.id_markers.reasons import _up_red, _WIN\n"
        "\n"
        '__layer__ = "models"\n'
        "\n"
        f'_REASON = "red on pure upstream tag {tag} {sha} on {host} ({date} release merge)"\n'
        "\n"
        "_NODES = (\n"
        f"{body}"
        ")\n"
        "\n"
        "ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (\n"
        f"    {{node: (_up_red(_REASON),) for node in _NODES}} if {guard} else {{}}\n"
        ")\n"
    )


_SKIP_WHY = {
    Verdict.UPSTREAM_COLLECT_ERROR: "the whole file fails on the pure tag {tag} (collection error, crash or timeout)",
    Verdict.NONDETERMINISTIC_ON_TAG: "nondeterministic on the pure tag {tag} - {n} node(s) red on some runs only",
}


def emit_skip_rows(verdicts: Mapping[str, Verdict], tag: str, sha: str) -> List[str]:
    """``path · upstream: <why> · <sha>`` rows for whole-file and nondeterministic files."""

    by_file: Dict[str, Dict[Verdict, int]] = {}
    for node, verdict in verdicts.items():
        if verdict in _SKIP_WHY:
            counts = by_file.setdefault(file_of(node), {})
            counts[verdict] = counts.get(verdict, 0) + 1
    rows = []
    for path, counts in sorted(by_file.items()):
        verdict = Verdict.UPSTREAM_COLLECT_ERROR if Verdict.UPSTREAM_COLLECT_ERROR in counts else Verdict.NONDETERMINISTIC_ON_TAG
        why = _SKIP_WHY[verdict].format(tag=tag, n=counts.get(verdict, 0))
        rows.append(f"{path} · upstream: {why} · {sha}")
    return rows


def emit_report(verdicts: Mapping[str, Verdict], runs: Sequence[TagRun]) -> List[str]:
    lines = []
    for node, verdict in sorted(verdicts.items()):
        absent = verdict is Verdict.ABSENT_ON_TAG
        trail = "-" if absent else ",".join(outcome(node, run).value for run in runs)
        lines.append(f"{verdict.value:<24} {node}  [{trail}]")
    counts: Dict[str, int] = {}
    for verdict in verdicts.values():
        counts[verdict.value] = counts.get(verdict.value, 0) + 1
    lines.append("verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return lines


# ── Stage 2: the tag worktree, the tag's runner, the CLI ─────────────────────

GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")  # a bare ``bash`` from Python on Windows is WSL
DEFAULT_PYTHON = Path("C:/Users/beast/.venvs/hermes-test/Scripts/python.exe")
_SCRUB = re.compile(r"^(HERMES_|__HERMES|PYTEST_)|KEY|TOKEN|SECRET|PASSWORD", re.I)


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    """Every git call that touches the clone; ``cwd`` is the neutral directory."""

    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, timeout=600)


def _rev_parse(path: Path, *flags: str) -> Optional[str]:
    probe = subprocess.run(["git", "-C", str(path), "rev-parse", *flags], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
    return probe.stdout.strip() if probe.returncode == 0 and probe.stdout.strip() else None


def primary_of(path: Path) -> Optional[Path]:
    common = _rev_parse(path, "--path-format=absolute", "--git-common-dir")
    return Path(common).parent.resolve() if common else None


def _within(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def hermetic_env(python: Path, workers: int) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SCRUB.search(k)}
    env.update(HERMES_PYTHON=str(python), HERMES_TEST_WORKERS=str(workers), PYTHONHASHSEED="0",
               PYTHONUTF8="1", TZ="UTC", GIT_OPTIONAL_LOCKS="0")
    return env


class TagWorktree:
    """A detached worktree at ``tag``, cut and removed with ``cwd`` = the neutral directory."""

    def __init__(self, repo: Path, tag: str, neutral: Path, *, keep: bool = False) -> None:
        if _rev_parse(neutral, "--show-toplevel") is not None:
            raise SystemExit(f"error: --worktrees {neutral} is inside a git checkout; name a neutral directory")
        self.repo, self.tag, self.neutral, self.keep = repo, tag, neutral, keep
        self.path = neutral / f"hermes-tag-{slug(tag)}-{os.getpid()}"

    def __enter__(self) -> "TagWorktree":
        made = _git(["-C", str(self.repo), "worktree", "add", "--detach", str(self.path), self.tag], self.neutral)
        if made.returncode != 0:
            raise SystemExit(f"error: git worktree add failed: {made.stderr.strip()}")
        return self

    def __exit__(self, *exc: object) -> None:
        if self.keep:
            print(f"kept the tag worktree: {self.path}")
            return
        _git(["-C", str(self.repo), "worktree", "remove", "--force", str(self.path)], self.neutral)
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        _git(["-C", str(self.repo), "worktree", "prune"], self.neutral)


def run_files(worktree: Path, files: Sequence[str], repeat: int, log_dir: Path, *, bash: Path,
              python: Path, workers: int = 2) -> List[TagRun]:
    """The tag's own ``scripts/run_tests.sh`` over ``files``, ``repeat`` times; each run's log
    and exit code land side by side in ``log_dir``."""

    runs = []
    for attempt in range(1, repeat + 1):
        log = log_dir / f"tag-run-{attempt}.log"
        with log.open("w", encoding="utf-8") as handle:
            done = subprocess.run([str(bash), str(worktree / "scripts" / "run_tests.sh"), "--file-retries", "0",
                                   *files], cwd=str(worktree), env=hermetic_env(python, workers), stdout=handle,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        (log_dir / f"tag-run-{attempt}.rc").write_text(f"{done.returncode}\n", encoding="utf-8")
        print(f"tag run {attempt}/{repeat}: exit {done.returncode}, log {log}")
        runs.append(parse_run_output(log.read_text(encoding="utf-8", errors="replace")))
    return runs


def collect_present(worktree: Path, files: Iterable[str], *, python: Path) -> Presence:
    """``python -m pytest --collect-only -q <file>`` at the tag, one file per process."""

    nodes, errors, missing = set(), set(), set()
    for rel in sorted(set(files)):
        if not (worktree / rel).is_file():
            missing.add(rel)
            continue
        done = subprocess.run([str(python), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", rel],
                              cwd=str(worktree), env=hermetic_env(python, 1), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=600)
        if done.returncode not in (0, 5):
            errors.add(rel)
        nodes.update(line.strip().replace("\\", "/") for line in done.stdout.splitlines()
                     if line.strip().replace("\\", "/").startswith(rel + "::"))
    return Presence(frozenset(nodes), frozenset(errors), frozenset(missing))


def lock_drift(repo: Path, tag: str) -> int:
    """Packages ``uv.lock`` pins differently at ``tag`` and HEAD (the tag ran on main's venv)."""

    def pins(rev: str) -> Dict[str, str]:
        shown = _git(["-C", str(repo), "show", f"{rev}:uv.lock"], repo.parent)
        if shown.returncode != 0:
            return {}
        return {p["name"]: p.get("version", "") for p in tomllib.loads(shown.stdout).get("package", [])}

    old, new = pins(tag), pins("HEAD")
    return sum(1 for name in old.keys() | new.keys() if old.get(name) != new.get(name))


def _load_known_reds(repo: Path) -> Dict[str, frozenset]:
    """The last recorded gate run's red map (``run_tests_bundled_plan.load_known_reds``)."""

    spec = importlib.util.spec_from_file_location("_rtb_plan", Path(__file__).with_name("run_tests_bundled_plan.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_known_reds(repo)


def _classify_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--nodeid", action="append", default=[], help="a red node id (repeatable)")
    parser.add_argument("--from-log", type=Path, help="a gate log: its FAILED/ERROR node lines")
    parser.add_argument("--from-record", action="store_true", help="the last recorded run's red map (the default)")
    parser.add_argument("--repeat", type=int, default=2, help="tag runs (nondeterminism needs two)")
    parser.add_argument("--repo", type=Path, help="the clone (default: this script's primary checkout)")
    parser.add_argument("--worktrees", type=Path, help="a neutral directory (default: <clone parent>/worktrees)")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON, help="a venv python with pytest")
    parser.add_argument("--bash", type=Path, default=GIT_BASH if sys.platform == "win32" else Path("bash"))
    parser.add_argument("--emit", choices=("report", "table", "skip-rows"), action="append")
    parser.add_argument("--write", action="store_true", help="write the table as a NEW module, never an existing one")
    parser.add_argument("--keep", action="store_true", help="do not remove the tag worktree")
    return parser


def _red_nodes(args: argparse.Namespace, repo: Path) -> List[str]:
    nodes = list(args.nodeid)
    if args.from_log:
        nodes += parse_run_output(args.from_log.read_text(encoding="utf-8", errors="replace")).red_nodes
    if args.from_record or not (args.nodeid or args.from_log):
        nodes += [n for ids in _load_known_reds(repo).values() for n in ids]
    return sorted({n.replace("\\", "/") for n in nodes if "::" in n})


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _classify_parser().parse_args(argv)
    repo = (args.repo or primary_of(Path(__file__).parent) or Path.cwd()).resolve()
    if _within(Path.cwd(), repo):
        print(f"error: refusing to run inside the primary checkout {repo}; run from a neutral cwd",
              file=sys.stderr)
        return 2
    nodes = _red_nodes(args, repo)
    if not nodes:
        print("error: no red node ids to classify", file=sys.stderr)
        return 2
    sha = _git(["-C", str(repo), "rev-parse", "--short=10", f"{args.tag}^{{commit}}"], repo.parent).stdout.strip()
    neutral = (args.worktrees or repo.parent / "worktrees").resolve()
    with TagWorktree(repo, args.tag, neutral, keep=args.keep) as tag_tree:
        log_dir = neutral / f"{tag_tree.path.name}-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        presence = collect_present(tag_tree.path, {file_of(n) for n in nodes}, python=args.python)
        runnable = sorted({file_of(n) for n in presence.nodes} | presence.collect_errors)
        runs = run_files(tag_tree.path, runnable, args.repeat, log_dir, bash=args.bash,
                         python=args.python) if runnable else []
    verdicts = classify(nodes, runs, presence)
    drift = lock_drift(repo, args.tag)
    if drift:
        print(f"uv.lock differs: {drift} packages between {args.tag} and HEAD (the tag ran on main's venv)")
    table = emit_table(verdicts, args.tag, sha, time.strftime("%Y-%m-%d"))
    for emit in args.emit or ["report"]:
        if emit == "report":
            print("\n".join(emit_report(verdicts, runs)))
        elif emit == "skip-rows":
            print("\n".join(emit_skip_rows(verdicts, args.tag, sha)))
        else:
            print(table)
    if args.write:
        here = _rev_parse(Path.cwd(), "--show-toplevel")
        if here is None:
            print("error: --write runs from the merge worktree (it writes there, never into the primary)",
                  file=sys.stderr)
            return 2
        target = Path(here) / "tests" / "_downstream" / "id_markers" / f"upstream_reds_{slug(args.tag)}.py"
        if target.exists():
            print(f"error: {target} exists; --write creates a NEW table only", file=sys.stderr)
            return 2
        target.write_text(table, encoding="utf-8")
        print(f"wrote {target} (register it in hooks._merge and the id_markers map)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
