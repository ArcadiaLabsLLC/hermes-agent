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
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from scripts.run_tests_bundled_events import BundleEvents

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


#: a run expected to take longer than this, from a session-chain edit, says how to avoid paying it
CHAIN_SPLIT_HINT_SECONDS = 20 * 60.0


def expected_wall(estimates: Mapping[str, Optional[float]], jobs: int, default: float) -> tuple[float, str]:
    """The run's expected wall seconds before it starts, and the plan line that says so.

    The floor of any packing: ``max(Σ estimates / jobs, longest estimate)``. A file
    without a recorded time counts at ``default``. Owner, 2026-10-15: a landing
    learns it is a 2.5-hour run from this line, not 66 minutes in."""

    known = {rel: float(s) for rel, s in estimates.items() if s}
    unknown = len(estimates) - len(known)
    total = sum(known.values()) + unknown * default
    longest_rel, longest = max(known.items(), key=lambda kv: kv[1], default=("", default if unknown else 0.0))
    wall = max(total / max(1, jobs), longest)
    line = (
        f"Expected wall: ~{wall / 60:.0f} min at -j {jobs} (Σ {total / 60:.0f} worker-min over {len(estimates)} "
        f"file(s); longest {longest:.0f}s{' ' + longest_rel if longest_rel else ''}; {unknown} without a "
        f"recorded time counted at {default:.0f}s)"
    )
    return wall, line


def chain_split_hint(wall: float, chain_paths: Sequence[str]) -> Optional[str]:
    """The advice a long run caused by a session-chain edit prints up front."""

    if not chain_paths or wall < CHAIN_SPLIT_HINT_SECONDS:
        return None
    return (
        f"  this is a whole-tree run because {', '.join(chain_paths)} changed (session chain): land that change "
        "alone, or with the release merge, instead of inside a batch"
    )


# ── Stage 0: the run ledger ─────────────────────────────────────────────────

#: the process kinds the ledger counts, by a kind's first word (fast-gate §2 adds
#: the known red's one run; §3 a slow file's ``shard i/k`` and its ``whole-check``)
PROCESS_KINDS = ("bundle", "solo", "known-red", "shard", "whole-check", "rerun", "retry")

#: Retain the beginning and end of large diagnostics; scrub BEFORE cutting so
#: truncation cannot split a credential away from its identifying field name.
DIAGNOSTIC_CHARS = 64 * 1024


@dataclass(frozen=True)
class BundleDiagnostic:
    """One original abnormal attempt, independent of its members' later verdicts."""

    bundle_index: int
    members: List[str]
    process_rc: int
    session_rc: Optional[int]
    session_ended: bool
    stopped_in: Optional[str]
    failed: Dict[str, List[str]]
    output: str
    omitted_chars: int

    @classmethod
    def capture(
        cls, index: int, members: Sequence[str], rc: int, events: "BundleEvents", output: str,
        stopped_in: Optional[str],
    ) -> "BundleDiagnostic":
        from agent_runtime.redaction import scrub_secret_values

        safe = scrub_secret_values(output)
        omitted = max(0, len(safe) - DIAGNOSTIC_CHARS)
        if omitted:
            half = DIAGNOSTIC_CHARS // 2
            safe = f"{safe[:half]}\n[... {omitted} redacted characters omitted ...]\n{safe[-half:]}"
        return cls(
            index, list(members), rc, events.exit_status, events.session_end is not None, stopped_in,
            {rel: [scrub_secret_values(node) for node in tally.failed_nodeids]
             for rel, tally in events.files.items() if not tally.clean or tally.failed_nodeids},
            safe, omitted,
        )


def render_bundle_diagnostics(diagnostics: Sequence[BundleDiagnostic]) -> List[str]:
    """Print each first-attempt output once, even if several members needed a retry."""
    if not diagnostics:
        return []
    lines = ["", "=== Original bundle diagnostics (retained even when retries pass) ===",
             "Summary counts describe final attempts, not first-pass success."]
    for item in sorted(diagnostics, key=lambda entry: entry.bundle_index):
        lines.extend([
            f"--- bundle #{item.bundle_index}: process rc={item.process_rc}; "
            f"session rc={item.session_rc}; session ended={item.session_ended} ---",
            f"  ordered members: {', '.join(item.members)}",
        ])
        if item.stopped_in is not None:
            lines.append(f"  last observed member: {item.stopped_in}")
        for rel, nodes in item.failed.items():
            lines.append(f"  recorded failure: {rel}: {', '.join(nodes)}")
        lines.append(item.output.rstrip() or "(no output captured)")
    return lines


@dataclass
class Process:
    """One pytest process the run spawned."""

    kind: str  # "bundle" | "solo" | "known-red" | "rerun" | "retry"
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
    #: Only abnormal bundle attempts; retained before retry scheduling and scratch cleanup.
    bundle_diagnostics: List[BundleDiagnostic] = field(default_factory=list)

    def record_bundle_diagnostic(
        self, index: int, members: Sequence[str], rc: int, events: "BundleEvents", output: str,
        stopped_in: Optional[str] = None,
    ) -> None:
        confirmed = rc == 0 and events.session_end is not None and events.exit_status == 0
        clean = all(rel in events.files and events.files[rel].clean for rel in members)
        if not (confirmed and clean):
            self.bundle_diagnostics.append(BundleDiagnostic.capture(index, members, rc, events, output, stopped_in))

    def diagnostic_record(self) -> Dict[str, object]:
        """The existing runs.jsonl owns durability; final-red caching remains separate."""
        return {"bundle_diagnostics": [asdict(item) for item in sorted(
            self.bundle_diagnostics, key=lambda entry: entry.bundle_index,
        )]}
    def record_solo(
        self, kind: str, rel: str, started: float, session_start: Optional[float], tally, *, add: bool = False
    ) -> None:
        """One single-file process: its wall and start-up, and the file's seconds and
        failing ids from its recorder ``tally`` (None when the recorder wrote nothing).
        ``add``: one shard of the file (fast-gate §3), added to its siblings'."""

        startup = None if session_start is None else max(0.0, session_start - started)
        self.processes.append(Process(kind, [rel], started, time.time(), startup))
        if tally is not None:
            before = self.file_seconds.get(rel, 0.0) if add else 0.0
            self.file_seconds[rel] = before + tally.collect_seconds + tally.test_seconds
        failed = list(tally.failed_nodeids) if tally is not None else []
        self.failed[rel] = (self.failed.get(rel, []) if add else []) + failed

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
            "processes": {k: sum(1 for p in self.processes if p.kind.split(" ", 1)[0] == k) for k in PROCESS_KINDS},
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
        f"  processes: {procs['bundle']} bundles, {procs['solo']} solos, {procs['known-red']} known reds run once, "
        f"{procs['shard']} shards (+{procs['whole-check']} whole checks), {procs['rerun']} re-runs alone, "
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
#: ``kind`` of the line scripts/run_tests_idle.sh appends (owner ruling 2026-10-10)
IDLE_RUN_KIND = "idle"


def primary_checkout(repo_root: Path) -> Optional[Path]:
    """The clone's main worktree when ``repo_root`` is a linked worktree, else None.

    A landing worktree is cut fresh, so its own duration cache and run record are
    empty and Stages 2-3 would plan by count and re-run every red alone; both
    fall back to the primary checkout's copies (plan O4)."""

    try:
        common = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    primary = Path(common).parent
    return None if not common or primary.resolve() == Path(repo_root).resolve() else primary


def load_durations_with_primary(repo_root: Path, load) -> Dict[str, float]:
    """``load(repo_root)`` over the primary checkout's cache: a local entry wins."""

    primary = primary_checkout(repo_root)
    return {**(load(primary) if primary is not None else {}), **load(repo_root)}


def last_record(repo_root: Path, record_path: Optional[Path] = None) -> Dict[str, object]:
    """The LAST gate line of the run record; ``{}`` when it is missing or torn.
    A worktree with no record of its own reads the primary checkout's.
    ``record_path`` names the file outright (the gate store's ``runs.jsonl``)."""

    record = record_path if record_path is not None else repo_root / RUNS_FILE
    if record_path is None and not record.is_file():
        primary = primary_checkout(repo_root)
        record = primary / RUNS_FILE if primary is not None else record
    try:
        lines = record.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # the idle-box lane's line (scripts/run_tests_idle.sh) carries no red map
        if not isinstance(entry, dict) or entry.get("kind") == IDLE_RUN_KIND:
            continue
        return entry
    return {}


def load_known_reds(repo_root: Path, record_path: Optional[Path] = None) -> Dict[str, frozenset]:
    """rel → the failing node ids the LAST recorded run carried for it. A
    missing or torn record is empty: every red is then re-run alone."""

    red = last_record(repo_root, record_path).get("red") or {}
    return {rel: frozenset(ids) for rel, ids in red.items() if ids}


def load_timed_out(repo_root: Path, record_path: Optional[Path] = None) -> frozenset:
    """Files whose last attempt in the recorded runs was a TIMEOUT (killed, no
    failing ids, so absent from the red map) — known reds too (fast-gate §2)."""

    return frozenset(last_record(repo_root, record_path).get("timed_out") or ())


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
    *,
    timed_out: Iterable[str] = (),
    previous_timed_out: Iterable[str] = (),
    extra: Optional[Mapping[str, object]] = None,
    record_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Append one JSON line: the run's summary plus the red map — the previous
    map with every file this run ran replaced by what it showed (red with its
    failing ids, or dropped when green). Files not run carry forward, so a
    partial run never forgets a red it did not look at. ``timed_out`` (files
    whose final attempt was a timeout) is carried forward the same way.
    ``extra`` adds keys a caller carries itself (the shard planner's ``tests``).
    ``record_path`` names the file outright (the gate store's ``runs.jsonl``, fast-gate §1)."""

    red = {rel: sorted(ids) for rel, ids in previous.items()}
    for rel, rc in final_rc.items():
        ids = sorted(set(failed.get(rel) or ()))
        if rc != 0 and ids:
            red[rel] = ids
        else:
            red.pop(rel, None)
    late = sorted((set(previous_timed_out) - set(final_rc)) | set(timed_out))
    record = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **summary, "red": dict(sorted(red.items())), "timed_out": late}
    record.update(extra or {})
    path = record_path if record_path is not None else repo_root / RUNS_FILE
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
