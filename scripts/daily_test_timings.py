"""Per-test timings for the daily full run (row FH-DAILY-RUN-TIMES-EVERY-TEST).

Owner 2026-11-20: "make sure this script times it prints a timing log for every test we need this to
check for things that hang or take longer than they should". The runners already keep per-FILE
seconds (``test_durations.json``, the bundled runner's ``runs.jsonl``); nothing named a single test,
and a file killed at its timeout left no name for the test that hung.

Two halves, one module:

* **The pytest plugin.** ``scripts/daily_full_run.sh`` passes ``-p scripts.daily_test_timings
  --daily-test-timings=<dir>`` (after ``--``, so every per-file process of ``run_tests.sh`` and every
  bundle of the bundled runner gets it). Each pytest process appends to ``<dir>/<pid>.jsonl``: a
  ``start`` line when a test starts and an ``end`` line (node id, seconds, outcome) when it finishes,
  each written and flushed at once, so a process killed mid-test leaves its ``start`` with no ``end``.
  Without the option the plugin does nothing.
* **The report.** ``python scripts/daily_test_timings.py <dir> <out.json>`` folds the files into one
  JSON (every test, slowest first, and every test that started but never finished) and prints the
  lines ``daily_full_run.sh`` adds to ``summary.txt``. Exit 0 always once it wrote the JSON (the
  step's own exit is the red), 2 on usage.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

#: a test this slow is named in the summary. Every test runs under ``--timeout=30`` (``addopts``), so
#: a test past 10 s is a third of the way to being killed; a unit test that long is nearly always
#: waiting (a sleep, a subprocess, a network retry), which is what the owner asked to see.
SLOW_TEST_SECONDS = 10.0
#: how many of the slowest tests the summary names per step, whatever their seconds: enough to see
#: the head of the distribution without burying the step's other lines.
SLOWEST_SHOWN = 10
OPTION = "--daily-test-timings"

_DEST = "daily_test_timings"
_RANK = {"passed": 0, "skipped": 1, "xfailed": 1, "xpassed": 2, "failed": 3, "error": 4}


# ── the plugin ──────────────────────────────────────────────────────────────────────────────────


def pytest_addoption(parser) -> None:
    parser.addoption(OPTION, dest=_DEST, default=None, metavar="DIR",
                     help="append one start and one end line per test to DIR/<pid>.jsonl (the daily full run)")


def pytest_configure(config) -> None:
    where = config.getoption(_DEST)
    if where:
        config.pluginmanager.register(_Recorder(Path(where)), "daily-test-timings-recorder")


class _Recorder:
    def __init__(self, where: Path) -> None:
        where.mkdir(parents=True, exist_ok=True)
        # Line-buffered append: each line reaches the file as it is written, so a SIGKILL loses nothing
        # already recorded. MUTATION: buffer the file (drop buffering=1) and
        # test_a_test_that_never_finishes_is_named_unfinished reddens — the killed process's start
        # line never reaches the disk.
        self._out = open(where / f"{os.getpid()}.jsonl", "a", encoding="utf-8", buffering=1)
        self._phases: dict[str, list] = {}

    def _write(self, record: dict) -> None:
        try:
            self._out.write(json.dumps(record, separators=(",", ":")) + "\n")
        except (OSError, ValueError):  # a closed or full disk never fails the test it records
            pass

    def pytest_runtest_logstart(self, nodeid, location) -> None:
        self._phases[nodeid] = []
        self._write({"e": "start", "id": nodeid, "t": round(time.time(), 3)})

    def pytest_runtest_logreport(self, report) -> None:
        self._phases.setdefault(report.nodeid, []).append(report)

    def pytest_runtest_logfinish(self, nodeid, location) -> None:
        reports = self._phases.pop(nodeid, [])
        self._write({"e": "end", "id": nodeid, "s": round(sum(r.duration for r in reports), 4),
                     "o": _worst_phase(reports), "t": round(time.time(), 3)})

    def pytest_unconfigure(self, config) -> None:
        self._out.close()


def _worst_phase(reports) -> str:
    """One word per test: the worst of its phases (a teardown error beats a passed call)."""

    word = "passed"
    for report in reports:
        if report.failed:
            this = "failed" if report.when == "call" else "error"
        elif report.skipped:
            this = "xfailed" if hasattr(report, "wasxfail") else "skipped"
        elif hasattr(report, "wasxfail") and report.when == "call":
            this = "xpassed"
        else:
            continue
        if _RANK[this] > _RANK[word]:
            word = this
    return word


# ── the report ──────────────────────────────────────────────────────────────────────────────────


def fold(where: Path, now: float | None = None) -> dict:
    """Every test the files under ``where`` record, slowest first, and the ones that never finished."""

    now = time.time() if now is None else now
    results: list[dict] = []
    unfinished: list[dict] = []
    for path in sorted(where.glob("*.jsonl")):
        pid = path.stem
        open_starts: dict[str, float] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:  # a line cut short by a kill mid-write
                continue
            if not isinstance(record, dict) or "id" not in record:
                continue
            if record.get("e") == "start":
                open_starts[record["id"]] = record.get("t", now)
            elif record.get("e") == "end":
                open_starts.pop(record["id"], None)
                results.append({"nodeid": record["id"], "seconds": record.get("s", 0.0),
                                "outcome": record.get("o", "?"), "pid": pid})
        # MUTATION: skip this loop and test_a_test_that_never_finishes_is_named_unfinished reddens.
        for nodeid, started in open_starts.items():
            unfinished.append({"nodeid": nodeid, "pid": pid, "started": started,
                               "running_seconds": round(max(0.0, now - started), 1)})
    finished = {r["nodeid"] for r in results}
    for entry in unfinished:
        entry["finished_on_retry"] = entry["nodeid"] in finished
    results.sort(key=lambda r: (-r["seconds"], r["nodeid"]))
    unfinished.sort(key=lambda u: u["started"])
    return {"tests": len(results), "threshold_seconds": SLOW_TEST_SECONDS,
            "slow": sum(1 for r in results if r["seconds"] >= SLOW_TEST_SECONDS),
            "unfinished": unfinished, "results": results}


def summary_lines(folded: dict, json_path: str) -> list[str]:
    """The lines ``summary.txt`` carries under the step's own line."""

    unfinished = folded["unfinished"]
    # A file the runner re-ran (a red, a timeout) times its tests once per attempt: the summary names
    # each test once, at its slowest attempt, and says how many attempts there were; the JSON keeps all.
    attempts: dict[str, int] = {}
    for result in folded["results"]:
        attempts[result["nodeid"]] = attempts.get(result["nodeid"], 0) + 1
    seen: set[str] = set()
    ranked = []
    for result in folded["results"]:  # slowest first, so the first sighting is the slowest attempt
        if result["nodeid"] not in seen:
            seen.add(result["nodeid"])
            ranked.append({**result, "attempts": attempts[result["nodeid"]]})
    slow = [r for r in ranked if r["seconds"] >= SLOW_TEST_SECONDS]
    lines = [f"    timings: {folded['tests']} test(s) timed, {len(slow)} over {SLOW_TEST_SECONDS:g}s, "
             f"{len(unfinished)} never finished — {json_path}"]
    # MUTATION: drop this loop and test_a_test_that_never_finishes_is_named_unfinished reddens.
    for entry in unfinished:
        retry = "; it passed or failed on a later attempt" if entry["finished_on_retry"] else ""
        started = time.strftime("%H:%M:%SZ", time.gmtime(entry["started"]))
        lines.append(f"    NEVER FINISHED (hung or killed): {entry['nodeid']} — started {started}, "
                     f"ran ≥{entry['running_seconds']:g}s, pid {entry['pid']}{retry}")
    for result in slow:
        lines.append(f"    over {SLOW_TEST_SECONDS:g}s: {_one(result)}")
    if ranked:
        lines.append(f"    slowest {min(SLOWEST_SHOWN, len(ranked))}:")
        lines.extend(f"      {_one(result)}" for result in ranked[:SLOWEST_SHOWN])
    return lines


def _one(result: dict) -> str:
    tries = f" ({result['attempts']} attempts)" if result["attempts"] > 1 else ""
    return f"{result['seconds']:.2f}s {result['outcome']} {result['nodeid']}{tries}"


# ── the shared per-file record ──────────────────────────────────────────────────────────────────
#
# FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET: ``scripts/prepush.sh`` splits a slow touched file
# into node-id shards, but read only the tree's own untracked ``test_durations.json``, so a fresh lane
# tree ran every heavy file whole on one worker. The daily run's per-test times are the record a fresh
# tree falls back to: the fold below writes each file's seconds, its slowest test and its test count
# into ONE file in the clone's git common directory, which every worktree of the clone shares. It is
# this machine's record (a Windows box keeps its own), and it is not a second timing system: it is
# this module's own fold, kept current by each daily run.

#: the shared record's name, in ``git rev-parse --git-common-dir``.
SHARED_RECORD_NAME = "hermes-test-timings.json"


def file_timings(folded: dict) -> dict[str, list]:
    """``{file: [seconds, slowest test's seconds, tests]}`` from one fold.

    A test timed on several attempts counts at its slowest; a test that never finished counts at
    the seconds it ran before it was killed, so a file cut off at its timeout is never recorded as
    fast."""

    per_test: dict[str, float] = {}
    for result in folded["results"]:
        nodeid = result["nodeid"]
        per_test[nodeid] = max(per_test.get(nodeid, 0.0), float(result["seconds"]))
    for entry in folded["unfinished"]:
        nodeid = entry["nodeid"]
        if nodeid not in per_test:
            per_test[nodeid] = float(entry["running_seconds"])
    files: dict[str, list] = {}
    for nodeid, seconds in per_test.items():
        path = nodeid.split("::", 1)[0].replace("\\", "/")
        row = files.setdefault(path, [0.0, 0.0, 0])
        row[0] += seconds
        row[1] = max(row[1], seconds)
        row[2] += 1
    return {path: [round(row[0], 2), round(row[1], 2), row[2]] for path, row in files.items()}


def read_shared_record(record: Path) -> dict[str, list]:
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        files = data["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {k: v for k, v in files.items() if isinstance(v, list) and len(v) == 3} if isinstance(files, dict) else {}


def update_shared_record(folded: dict, record: Path, now: float | None = None) -> int:
    """Merge one fold's files into *record*; files this fold did not run keep their last entry.

    One line per file (``"tests/a/test_x.py": [72.82, 36.5, 2],``) so the shell reads a file's entry
    with one ``grep``. Written whole and swapped in, so a reader never sees half a record."""

    merged = read_shared_record(record)
    fresh = file_timings(folded)
    if not fresh:
        return 0
    merged.update(fresh)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))
    lines = [f'{{"schema": 1, "updated": "{stamp}", "files": {{']
    rows = [f"  {json.dumps(path)}: {json.dumps(merged[path])}" for path in sorted(merged)]
    lines.append(",\n".join(rows))
    lines.append("}}")
    staged = record.with_name(f"{record.name}.{os.getpid()}.tmp")
    staged.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(staged, record)
    return len(fresh)


def main(argv: list[str]) -> int:
    shared = None
    if len(argv) == 4 and argv[2] == "--shared-record":
        shared, argv = Path(argv[3]), argv[:2]
    if len(argv) != 2:
        print("usage: python scripts/daily_test_timings.py <timings-dir> <out.json> [--shared-record <file>]",
              file=sys.stderr)
        return 2
    where, out = Path(argv[0]), Path(argv[1])
    folded = fold(where)  # a missing directory globs to nothing
    out.write_text(json.dumps(folded, indent=1) + "\n", encoding="utf-8")
    if shared is not None:
        try:
            count = update_shared_record(folded, shared)
        except OSError as exc:  # the record is a convenience for prepush; the step's own report stands
            print(f"    shared timings: not written ({exc})")
        else:
            if count:
                print(f"    shared timings: {count} file(s) into {shared}")
    if not where.is_dir():
        print(f"    timings: none recorded (no {where}) — {out}")
        return 0
    for line in summary_lines(folded, str(out)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
