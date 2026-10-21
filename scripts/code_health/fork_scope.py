"""``scripts/check``'s fork scope: ruff and the footgun scanner judge fork lines only.

A red on a line :mod:`scripts.code_health.fork_lines` calls the fork's fails the check as
before; a red on an upstream-owned line is counted and printed as ``upstream (not
judged)`` and never fails it. ``--judge-all`` (a merge lane's whole-tree verdict) judges
every red. The tools are not changed: ruff runs with ``--output-format=json`` and this
module renders its one text format; the footgun scanner's ``path:line: [name]`` blocks
are filtered as printed. If the fork lines cannot be read (no base, no manifest) every
red is judged and the receipt says so.

``scripts/check`` (an upstream file) holds only the additive calls: :func:`configure`,
:data:`RUFF_ARGS`, :func:`filter_job`, :func:`report_unjudged`.
Plan: ``docs/agent-runtime-harness/planned/fork-seam-line-lint-2026-10-21.md`` F2.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from scripts.code_health.fork_lines import ForkLines, ForkLinesUnavailable

RUFF_ARGS = ["--output-format=json"]
_FOOTGUNS_SCRIPT = "check-windows-footguns.py"
_FOOTGUN_HEADER = re.compile(r"^(?P<path>\S.*?):(?P<line>\d+): \[(?P<name>[^\]]+)\]$")
_SHOWN = 5


@dataclass
class _Unjudged:
    count: int = 0
    first: list[str] = field(default_factory=list)


@dataclass
class _State:
    judge_all: bool = False
    lines: dict[tuple[str, str | None], ForkLines | str] = field(default_factory=dict)
    unjudged: dict[str, _Unjudged] = field(default_factory=dict)


_STATE = _State()
_LOCK = threading.Lock()


def configure(*, judge_all: bool) -> None:
    """Start one ``scripts/check`` run: forget the previous run's lines and counts."""
    global _STATE
    with _LOCK:
        _STATE = _State(judge_all=judge_all)


def _fork_lines(cwd: Path, env: dict[str, str] | None) -> ForkLines | str:
    """The run's :class:`ForkLines` for this tree, or the reason there are none."""
    key = (str(cwd), (env or {}).get("GIT_WORK_TREE"))
    with _LOCK:
        if key not in _STATE.lines:
            try:
                _STATE.lines[key] = ForkLines.load(cwd, env=env)
            except (ForkLinesUnavailable, OSError, subprocess.TimeoutExpired) as exc:
                _STATE.lines[key] = str(exc)
        return _STATE.lines[key]


def _job_kind(argv: list[str]) -> str | None:
    if any(str(arg).endswith(_FOOTGUNS_SCRIPT) for arg in argv):
        return "footguns"
    if RUFF_ARGS[0] in argv and "check" in argv:
        return "ruff"
    return None


def _note(name: str, location: str) -> None:
    with _LOCK:
        entry = _STATE.unjudged.setdefault(name, _Unjudged())
        entry.count += 1
        if len(entry.first) < _SHOWN:
            entry.first.append(location)


def _judged(name: str, scope: ForkLines | str, path: str, line: int, location: str) -> bool:
    if _STATE.judge_all or isinstance(scope, str) or scope.is_fork_line(path, line):
        return True
    _note(name, location)
    return False


def _scope_line(scope: ForkLines | str) -> str:
    if _STATE.judge_all:
        return "scope: every line (--judge-all)"
    if isinstance(scope, str):
        return f"scope: every line (fork lines unavailable: {scope})"
    return f"scope: fork lines only {scope.summary()}"


def _relative(path: str, cwd: Path, scope: ForkLines | str) -> str:
    if isinstance(scope, ForkLines):
        return scope.relative(path)
    try:
        return Path(path).resolve().relative_to(cwd.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def _render_ruff(proc: subprocess.CompletedProcess[str], scope: ForkLines | str,
                 cwd: Path) -> tuple[int, str] | None:
    try:
        findings = json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None
    if not isinstance(findings, list):
        return None
    judged: list[str] = []
    for item in findings:
        path = item.get("filename") or "?"
        row = int((item.get("location") or {}).get("row") or 0)
        col = int((item.get("location") or {}).get("column") or 0)
        rel = _relative(path, cwd, scope)
        location = f"{rel}:{row}:{col} {item.get('code') or 'error'} {item.get('message', '')}"
        if _judged("ruff", scope, path, row, location):
            judged.append(location)
    lines = [*judged, f"ruff: {len(judged)} judged finding(s); {_scope_line(scope)}"]
    if proc.stderr.strip():
        lines.append(proc.stderr.strip())
    return (1 if judged else 0), "\n".join(lines)


def _render_footguns(proc: subprocess.CompletedProcess[str], scope: ForkLines | str,
                     cwd: Path) -> tuple[int, str] | None:
    del cwd  # the scanner already prints repo-relative paths
    blocks: list[tuple[str, int, list[str]]] = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        match = _FOOTGUN_HEADER.match(line)
        if match:
            blocks.append((match["path"], int(match["line"]), [line]))
        elif blocks and line.startswith("    ") and len(blocks[-1][2]) < 4:
            blocks[-1][2].append(line)
    if proc.returncode != 0 and not blocks:
        return None  # the scanner failed without findings: its own output is the receipt
    judged = [block for path, line, block in blocks
              if _judged("footguns", scope, path, line, block[0])]
    lines = ["\n".join(block) for block in judged]
    lines.append(f"footguns: {len(judged)} judged finding(s); {_scope_line(scope)}")
    return (1 if judged else 0), "\n".join(lines)


def filter_job(argv: list[str], cwd: Path, env: dict[str, str] | None,
               proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    """``proc`` with its upstream-line reds set aside; any other job is returned as is."""
    kind = _job_kind([str(arg) for arg in argv])
    if kind is None:
        return proc
    scope: ForkLines | str = "--judge-all" if _STATE.judge_all else _fork_lines(Path(cwd), env)
    render = _render_ruff if kind == "ruff" else _render_footguns
    rendered = render(proc, scope, Path(cwd))
    if rendered is None:
        return proc
    code, text = rendered
    return subprocess.CompletedProcess(proc.args, code, stdout=text, stderr="")


def report_unjudged(emit=print) -> None:
    """Print each tool's upstream reds: the count and the first five locations."""
    for name, entry in sorted(_STATE.unjudged.items()):
        emit(f"\n=== {name} upstream (not judged): {entry.count} ===")
        for location in entry.first:
            emit(f"  {location}")
