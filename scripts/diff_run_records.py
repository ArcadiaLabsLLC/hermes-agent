"""Diff two bundled runs from the gate store: what a chain change turned red, and what it fixed.

    python scripts/diff_run_records.py OFF_RUN ON_RUN [--off-line -2] [--on-line -1] [--store DIR]

``OFF_RUN`` / ``ON_RUN`` are the ``run`` ids of ``diagnosis.jsonl``; ``--off-line`` / ``--on-line``
index ``runs.jsonl`` (Python indexing, default the last two lines), whose ``red`` map carries files
a run did not look at, so the red sets are restricted to the files each run's diagnosis names.
Prints (a) NEW reds (red in ON, not OFF) with their phase — ``teardown`` when the ON diagnosis lists
the node in ``teardown_error_ids``, else ``call/setup``; (b) FIXED reds; (c) the
``body_patches`` / ``late_fixture_patches`` / ``teardown_errors`` population per run; (d) Σ phase
seconds and wall per run. Read-only; p10 S-A2 (``docs/agent-runtime-harness/planned/p10-suite-2026-10-19.md``).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

COUNTS = ("body_patches", "late_fixture_patches", "teardown_errors")
SECONDS = ("collect", "setup", "call", "teardown")


def _lines(path: Path) -> list[dict]:
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def _default_store() -> Path:
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent / ".pytest_cache" / "hermes_gate"


def side(store: Path, run: str, line: int) -> dict:
    diag = {d["f"]: d for d in _lines(store / "diagnosis.jsonl") if d.get("run") == run}
    record = _lines(store / "runs.jsonl")[line]
    red = {(rel, node) for rel, ids in (record.get("red") or {}).items() if rel in diag for node in ids}
    torn = {node for d in diag.values() for node in d.get("teardown_error_ids") or ()}
    counts = {c: sum(int(d.get(c) or 0) for d in diag.values()) for c in COUNTS}
    files = {c: sum(1 for d in diag.values() if d.get(c)) for c in COUNTS}
    seconds = {p: round(sum(float(d.get(p) or 0.0) for d in diag.values()), 1) for p in SECONDS}
    return {"files": len(diag), "red": red, "torn": torn, "counts": counts, "count_files": files,
            "seconds": seconds, "wall": record.get("elapsed"), "timed_out": sorted(record.get("timed_out") or ()),
            "diag": diag}


def diff(off: dict, on: dict) -> dict:
    new, fixed = sorted(on["red"] - off["red"]), sorted(off["red"] - on["red"])
    return {"new": [(node, "teardown" if node in on["torn"] else "call/setup") for _rel, node in new],
            "fixed": [node for _rel, node in fixed]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("off_run"), parser.add_argument("on_run")
    parser.add_argument("--off-line", type=int, default=-2), parser.add_argument("--on-line", type=int, default=-1)
    parser.add_argument("--store", type=Path, default=None)
    args = parser.parse_args(argv)
    store = args.store or _default_store()
    off, on = side(store, args.off_run, args.off_line), side(store, args.on_run, args.on_line)
    found = diff(off, on)
    for name, run in (("OFF", off), ("ON", on)):
        print(f"{name}: files {run['files']}, red nodes {len(run['red'])}, timed out {len(run['timed_out'])}, "
              f"wall {run['wall']} s, Σ {run['seconds']}, tests {run['counts']}, files {run['count_files']}")
    print(f"NEW ({len(found['new'])}):")
    for node, phase in found["new"]:
        print(f"  {phase:10} {node}")
    print(f"FIXED ({len(found['fixed'])}):")
    for node in found["fixed"]:
        print(f"  {node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
