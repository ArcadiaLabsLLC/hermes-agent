"""What the bundled runner plans before a run and records after it.

``scripts/run_tests_bundled.py`` owns execution (bundles, solos, re-runs,
leaks). This module owns the four inputs and outputs around it, each a stage of
``docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md`` §3:

* **the upstream-red skip list** (Stage 1) — ``tests/fixtures/upstream_skip_list.txt``,
  read by :func:`load_skip_list`; a listed file runs only when named;
* **duration-budget bundles** (Stage 3) — :func:`cut_by_budget` cuts a
  directory's files into bundles by Σ cached seconds instead of a count;
* **the run ledger** (Stage 0) — :class:`RunLedger` records every process the
  run spawned and prints what the run cost: Σ per-file seconds, worker
  utilization, start-up, the seconds spent re-running red members, the
  critical-path process and the idle tail;
* **the known-red record** (Stage 2) — one JSON line per run appended to
  ``.pytest_cache/hermes_bundled_runs.jsonl`` (git-ignored), carrying each red
  file's failing node ids; a bundle member whose failing set is IDENTICAL to
  the recorded one is reported red from its bundle, never re-run alone (owner
  ruling O5). A new or changed failing set is re-run alone as before.

Generic on purpose (no fork path but the two file names), like the runner.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ── Stage 1: the upstream-red skip list ─────────────────────────────────────

SKIP_LIST = Path("tests") / "fixtures" / "upstream_skip_list.txt"
#: the class word a row's ``why`` starts with; the merge lane keys its re-check on it
SKIP_CLASSES = ("P0", "env", "upstream")
_FIELD_SEP = " · "


@dataclass(frozen=True)
class SkipRow:
    """One listed upstream test file: ``path · why · upstream SHA``."""

    path: str
    why: str
    sha: str

    @property
    def klass(self) -> str:
        head = self.why.split(":", 1)[0].strip()
        return head.split()[0] if head else ""


def parse_skip_line(line: str) -> Optional[SkipRow]:
    """A row, or None for a blank or ``#`` line. A row that does not split into
    exactly three ` · ` fields raises ``ValueError`` naming the line."""

    text = line.strip()
    if not text or text.startswith("#"):
        return None
    fields = [part.strip() for part in text.split(_FIELD_SEP)]
    if len(fields) != 3 or not all(fields):
        raise ValueError(f"skip-list row is not `path · why · upstream SHA`: {text!r}")
    return SkipRow(Path(fields[0]).as_posix(), fields[1], fields[2])


def load_skip_list(path: Path) -> Dict[str, SkipRow]:
    """Repo-relative POSIX path → row. A missing list RAISES, like the
    manifest: without it the P0 files would silently be back in every run."""

    rows: Dict[str, SkipRow] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = parse_skip_line(line)
        if row is not None:
            rows[row.path] = row
    return rows


# ── Stage 3: duration-budget bundles ────────────────────────────────────────

DEFAULT_BUNDLE_SECONDS = 120.0
DEFAULT_SOLO_SECONDS = 60.0


def cut_by_budget(members: Sequence[Tuple[Path, float]], budget: float, cap: int) -> List[List[Path]]:
    """Consecutive bundles of ``(path, estimated seconds)``, in the given order.

    A bundle closes before the member that would take its Σ estimate past
    ``budget`` or its size past ``cap``; a member alone over the budget is a
    bundle of its own. ``budget <= 0`` cuts by ``cap`` only (the count rule)."""

    bundles: List[List[Path]] = []
    current: List[Path] = []
    total = 0.0
    for path, estimate in members:
        over_budget = budget > 0 and total + estimate > budget
        if current and (over_budget or len(current) >= cap):
            bundles.append(current)
            current, total = [], 0.0
        current.append(path)
        total += estimate
    if current:
        bundles.append(current)
    return bundles


# ── Stage 0: the run ledger ─────────────────────────────────────────────────


@dataclass
class Process:
    """One pytest process the run spawned."""

    kind: str  # "bundle" | "solo" | "rerun" | "retry"
    members: List[str]
    started: float
    ended: float
    startup: Optional[float] = None  # session start − spawn, when the recorder saw it

    @property
    def wall(self) -> float:
        return self.ended - self.started


@dataclass
class RunLedger:
    """Everything Stage 0 prints, recorded as the run goes (thread-safe by the
    runner's own lock around every call)."""

    started: float = field(default_factory=time.time)
    ended: Optional[float] = None
    processes: List[Process] = field(default_factory=list)
    #: rel → collect + test seconds of the file's LAST attempt
    file_seconds: Dict[str, float] = field(default_factory=dict)
    #: rel → failing node ids of the file's last attempt (empty when clean)
    failed: Dict[str, List[str]] = field(default_factory=dict)
    #: collect + test seconds the bundle attempt of a re-run member cost
    first_attempt_seconds: float = 0.0
    known_red: List[str] = field(default_factory=list)

    def summary(self, jobs: int, *, slowest: int = 20) -> Dict[str, object]:
        ended = self.ended or time.time()
        elapsed = max(1e-9, ended - self.started)
        worker_seconds = jobs * elapsed
        busy = sum(p.wall for p in self.processes)
        work = sum(self.file_seconds.values())
        reruns = [p for p in self.processes if p.kind == "rerun"]
        critical = max(self.processes, key=lambda p: p.wall, default=None)
        return {
            "elapsed": round(elapsed, 1),
            "jobs": jobs,
            "processes": {k: sum(1 for p in self.processes if p.kind == k) for k in ("bundle", "solo", "rerun", "retry")},
            "worker_seconds": round(worker_seconds, 1),
            "busy_seconds": round(busy, 1),
            "utilization": round(busy / worker_seconds, 3),
            "work_seconds": round(work, 1),
            "work_share": round(work / worker_seconds, 3),
            "floor_seconds": round(work / max(1, jobs), 1),
            "startup_seconds": round(sum(p.startup or 0.0 for p in self.processes), 1),
            "rerun_seconds": round(sum(p.wall for p in reruns) + self.first_attempt_seconds, 1),
            "known_red": sorted(self.known_red),
            "idle_tail_seconds": round(idle_tail(self.processes, jobs, self.started, ended), 1),
            "critical": None if critical is None else {
                "kind": critical.kind, "wall": round(critical.wall, 1),
                "first": critical.members[0], "last": critical.members[-1], "files": len(critical.members),
            },
            "slowest": [
                [rel, round(s, 1)]
                for rel, s in sorted(self.file_seconds.items(), key=lambda item: item[1], reverse=True)[:slowest]
            ],
        }


def idle_tail(processes: Iterable[Process], jobs: int, started: float, ended: float) -> float:
    """Seconds from the last moment every worker was busy to the end of the
    run; the whole run when the pool never filled."""

    edges = sorted([(p.started, 1) for p in processes] + [(p.ended, -1) for p in processes])
    busy = 0
    last_full = None
    for at, delta in edges:
        before = busy
        busy += delta
        if before >= jobs > busy:
            last_full = at
        elif busy >= jobs:
            last_full = None
    if busy >= jobs:  # still full at the end (an unfinished record)
        return 0.0
    return ended - (last_full if last_full is not None else started)


def render(summary: Mapping[str, object]) -> List[str]:
    """The ``=== Run cost ===`` block printed after the Summary line."""

    procs = summary["processes"]
    lines = [
        "=== Run cost (Stage 0) ===",
        f"  processes: {procs['bundle']} bundles, {procs['solo']} solos, {procs['rerun']} re-runs alone, "
        f"{procs['retry']} straggler retries",
        f"  worker-seconds {summary['worker_seconds']}s ({summary['jobs']} × {summary['elapsed']}s); "
        f"busy {summary['busy_seconds']}s = {summary['utilization']:.0%} utilization",
        f"  Σ per-file seconds (collect + tests) {summary['work_seconds']}s = {summary['work_share']:.0%} of "
        f"worker-seconds; floor at {summary['jobs']} workers {summary['floor_seconds']}s",
        f"  start-up (spawn → session start, Σ over processes) {summary['startup_seconds']}s",
        f"  re-running red members (their bundle attempt + the run alone) {summary['rerun_seconds']}s; "
        f"{len(summary['known_red'])} known red reported from the bundle without a re-run",
        f"  idle tail (fewer than {summary['jobs']} workers busy, to the end) {summary['idle_tail_seconds']}s",
    ]
    critical = summary.get("critical")
    if critical:
        lines.append(
            f"  critical path: {critical['kind']} {critical['wall']}s, {critical['files']} file(s) "
            f"{critical['first']} … {critical['last']}"
        )
    if summary["slowest"]:
        lines.append("  slowest files:")
        lines.extend(f"    {s:>7.1f}s  {rel}" for rel, s in summary["slowest"])
    return lines


# ── Stage 2: the known-red record ───────────────────────────────────────────

#: beside pytest's own last-failed cache, in a directory git already ignores
RUNS_FILE = ".pytest_cache/hermes_bundled_runs.jsonl"


def load_known_reds(repo_root: Path) -> Dict[str, frozenset]:
    """rel → the failing node ids the LAST recorded run carried for it. A
    missing or torn record is empty: every red is then re-run alone."""

    try:
        lines = (repo_root / RUNS_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            red = json.loads(line).get("red") or {}
        except (json.JSONDecodeError, AttributeError):
            continue
        return {rel: frozenset(ids) for rel, ids in red.items() if ids}
    return {}


def is_known_red(rel: str, failed_nodeids: Sequence[str], known: Mapping[str, frozenset]) -> bool:
    """O5: a member is reported from its bundle when its failing node set is
    non-empty and identical to the last recorded run's."""

    recorded = known.get(rel)
    return bool(recorded) and frozenset(failed_nodeids) == recorded


def record_run(
    repo_root: Path,
    summary: Mapping[str, object],
    final_rc: Mapping[str, int],
    failed: Mapping[str, Sequence[str]],
    previous: Mapping[str, frozenset],
) -> Dict[str, List[str]]:
    """Append one JSON line: the run's summary plus the red map — the previous
    map with every file this run ran replaced by what it showed (red with its
    failing ids, or dropped when green). Files not run carry forward, so a
    partial run never forgets a red it did not look at."""

    red = {rel: sorted(ids) for rel, ids in previous.items()}
    for rel, rc in final_rc.items():
        ids = sorted(set(failed.get(rel) or ()))
        if rc != 0 and ids:
            red[rel] = ids
        else:
            red.pop(rel, None)
    record = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **summary, "red": dict(sorted(red.items()))}
    path = repo_root / RUNS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return red


def last_session(lines: Sequence[str]) -> List[str]:
    """The event lines of the LAST pytest session in a file several attempts
    appended to (the per-file runner's flake retry re-uses the path)."""

    start = 0
    for index, line in enumerate(lines):
        if '"k": "start"' in line:
            start = index
    return list(lines[start:])
