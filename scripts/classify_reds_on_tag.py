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

import enum
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence

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
            seen = {outcome(node, run) for run in runs}
            if seen == {Outcome.RED}:
                verdicts[node] = Verdict.UPSTREAM_RED
            elif seen == {Outcome.FILE_RED}:
                verdicts[node] = Verdict.UPSTREAM_COLLECT_ERROR
            elif seen == {Outcome.PASS} or not seen:
                verdicts[node] = Verdict.FORK_CAUSED_OR_FLAKY
            else:
                verdicts[node] = Verdict.NONDETERMINISTIC_ON_TAG
    return verdicts


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
        trail = ",".join(outcome(node, run).value for run in runs)
        lines.append(f"{verdict.value:<24} {node}  [{trail}]")
    counts: Dict[str, int] = {}
    for verdict in verdicts.values():
        counts[verdict.value] = counts.get(verdict.value, 0) + 1
    lines.append("verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return lines
