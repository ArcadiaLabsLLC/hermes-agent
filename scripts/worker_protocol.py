#!/usr/bin/env python3
"""The worker-count protocol's instruments: a saturation sampler, the fixed sample, a receipt.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §4 stage 1. The six
measurement runs (8, 12, 16, 8, 12, 16 workers, idle box) are stage 2 and are not run here.

* ``SaturationSampler`` -- a thread sampling system-wide ``psutil.cpu_percent(interval=5)``
  and memory while a run goes; ``summary()`` gives ``cpu_busy_pct`` mean/p90 and
  ``mem_peak_pct``. It stops (and is joined) with the run.
* ``sample`` -- writes ``scripts/worker_protocol_sample.txt``: every file whose last attempt
  took >= 60 s in a whole-tree gate log, plus 200 files drawn by ``random.Random(7)`` from the
  0.5-4 s population (the seed is the sample's identity). Skip-listed files and files no
  longer in the tree are left out: a NAMED skip-listed file runs, and the P0 rows froze
  this box.
* ``measure`` -- runs one command under the sampler and appends a receipt line (workers,
  exit code, wall, saturation, and the bundled runner's own ledger line for that run).
  The runner family is not edited; the receipt carries what ``RunLedger.summary`` carries.

  python scripts/worker_protocol.py measure --workers 12 -- \\
      "C:/Program Files/Git/bin/bash.exe" scripts/run_tests_bundled.sh --file-retries 0 -j 12 \\
      $(cat scripts/worker_protocol_sample.txt)
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

#: a progress line of the bundled runner: ``[ n/N] ✓ tests/x.py (bundle, 1.2s) {...}``
_PROGRESS = re.compile(r"^\[\s*\d+/\d+\] . (tests[/\\]\S+?\.py) \(\w[\w -]*?(?:,[^)]*?)?, ([\d.]+)s\)", re.M)
RUNS_FILE = ".pytest_cache/hermes_bundled_runs.jsonl"
RECEIPTS_FILE = ".pytest_cache/hermes_worker_protocol.jsonl"
SKIP_LIST = "tests/fixtures/upstream_skip_list.txt"
SAMPLE_FILE = "scripts/worker_protocol_sample.txt"


def _psutil_cpu(interval: float) -> float:
    import psutil

    return psutil.cpu_percent(interval=interval)


def _psutil_mem() -> float:
    import psutil

    return psutil.virtual_memory().percent


class SaturationSampler:
    """Samples CPU busy % (each sample blocks ``interval`` seconds) and memory % on a thread."""

    def __init__(self, interval: float = 5.0, cpu: Callable[[float], float] = _psutil_cpu,
                 mem: Callable[[], float] = _psutil_mem) -> None:
        self.interval, self._cpu, self._mem = interval, cpu, mem
        self.cpu_samples: List[float] = []
        self.mem_samples: List[float] = []
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="saturation-sampler", daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            busy = self._cpu(self.interval)
            if self._stop.is_set():
                break
            self.cpu_samples.append(busy)
            self.mem_samples.append(self._mem())

    def start(self) -> "SaturationSampler":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.thread.join()

    def __enter__(self) -> "SaturationSampler":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def summary(self) -> Dict[str, object]:
        cpu = sorted(self.cpu_samples)
        p90 = cpu[min(len(cpu) - 1, int(0.9 * len(cpu)))] if cpu else None
        return {
            "cpu_busy_pct": {"mean": round(sum(cpu) / len(cpu), 1) if cpu else None,
                             "p90": None if p90 is None else round(p90, 1)},
            "mem_peak_pct": round(max(self.mem_samples), 1) if self.mem_samples else None,
            "samples": len(cpu),
            "interval": self.interval,
        }


def last_attempt_seconds(log_text: str) -> Dict[str, float]:
    """rel -> seconds of the file's LAST attempt in a bundled-runner log."""

    seconds: Dict[str, float] = {}
    for match in _PROGRESS.finditer(log_text):
        seconds[match.group(1).replace("\\", "/")] = float(match.group(2))
    return seconds


def build_sample(seconds: Dict[str, float], *, exclude: Iterable[str] = (), seed: int = 7, slow: float = 60.0,
                 band: Sequence[float] = (0.5, 4.0), draw: int = 200) -> List[str]:
    """Every file >= ``slow`` seconds, plus ``draw`` files from the ``band`` population."""

    skip = set(exclude)
    heavy = sorted(rel for rel, s in seconds.items() if s >= slow and rel not in skip)
    pool = sorted(rel for rel, s in seconds.items() if band[0] <= s <= band[1] and rel not in skip)
    return heavy + sorted(random.Random(seed).sample(pool, min(draw, len(pool))))


def skip_listed(repo: Path) -> List[str]:
    path = repo / SKIP_LIST
    rows = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return [row.split(" · ", 1)[0].strip() for row in rows if row.strip() and not row.startswith("#")]


def _ledger_lines(repo: Path) -> List[str]:
    path = repo / RUNS_FILE
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def measure(command: Sequence[str], workers: int, repo: Path, *, interval: float = 5.0) -> Dict[str, object]:
    """Run ``command`` under the sampler; the receipt carries the ledger line the run appended."""

    before = len(_ledger_lines(repo))
    started = time.time()
    with SaturationSampler(interval) as sampler:
        rc = subprocess.run(list(command), cwd=str(repo), stdin=subprocess.DEVNULL).returncode
    elapsed = time.time() - started
    added = _ledger_lines(repo)[before:]
    ledger: Optional[dict] = json.loads(added[-1]) if added else None
    receipt: Dict[str, object] = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "workers": workers, "rc": rc,
                                  "elapsed": round(elapsed, 1), **sampler.summary(), "ledger": ledger}
    if ledger and ledger.get("floor_seconds") and ledger.get("elapsed"):
        receipt["floor_over_elapsed"] = round(ledger["floor_seconds"] / ledger["elapsed"], 3)
    return receipt


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="verb", required=True)
    sample = sub.add_parser("sample", help="write the fixed sample from a whole-tree gate log")
    sample.add_argument("--log", type=Path, required=True)
    sample.add_argument("--out", type=Path, default=Path(SAMPLE_FILE))
    run = sub.add_parser("measure", help="run a command under the sampler and append a receipt")
    run.add_argument("--workers", type=int, required=True)
    run.add_argument("--receipts", type=Path, default=Path(RECEIPTS_FILE))
    run.add_argument("--interval", type=float, default=5.0)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    repo = Path.cwd()
    if args.verb == "sample":
        seconds = last_attempt_seconds(args.log.read_text(encoding="utf-8", errors="replace"))
        gone = [rel for rel in seconds if not (repo / rel).is_file()]
        files = build_sample(seconds, exclude=[*skip_listed(repo), *gone])
        args.out.write_text("\n".join(files) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(files)} files to {args.out} ({len(gone)} gone from the tree left out)")
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    receipt = measure(command, args.workers, repo, interval=args.interval)
    args.receipts.parent.mkdir(parents=True, exist_ok=True)
    with args.receipts.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "ledger"}, sort_keys=True))
    return int(receipt["rc"])


if __name__ == "__main__":
    sys.exit(main())
