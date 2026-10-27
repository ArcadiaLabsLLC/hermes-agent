"""CI-3 acceptance: does one gesture's correlation token join send -> serve -> fold, in order?

    python scripts/correlation_id_acceptance.py --token <minted id> \\
        --receipts <app-support>/diagnostics/mission_transport/receipts.jsonl \\
        --serve-log <HERMES_HOME>/logs/agent.log [--serve-utc-offset-minutes N] [--json]

Perform ONE office gesture (a delete or a drag) on your own build, copy its token from the
receipt, then run this. Reads the two logs and writes NOTHING. The hop rules live in
:mod:`agent_runtime.correlation_acceptance`; this file is argv, IO and an exit code.

Exit codes: ``0`` joined in order; ``1`` a hop is missing (or a log could not be read) — never a
pass; ``2`` every hop is present but out of order (a clock or a zone, or a real defect).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_JOINED = 0
EXIT_MISSING = 1
EXIT_OUT_OF_ORDER = 2


def _local_offset() -> timedelta:
    return datetime.now().astimezone().utcoffset() or timedelta(0)


def main(argv: list[str] | None = None) -> int:
    from agent_runtime.correlation_acceptance import VERDICT_JOINED, VERDICT_MISSING, join_token

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--token", required=True, help="the gesture's minted correlation id")
    parser.add_argument("--receipts", type=Path, action="append", required=True,
                        help="launcher receipts.jsonl (repeatable: rotated segments too)")
    parser.add_argument("--serve-log", type=Path, action="append", required=True,
                        help="the serve child's agent.log (repeatable)")
    parser.add_argument("--serve-utc-offset-minutes", type=int, default=None,
                        help="the serve log's local-time offset from UTC (default: this machine's)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    sources = []
    for path in [*args.receipts, *args.serve_log]:
        try:
            sources.append((str(path), Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()))
        except OSError as exc:
            print(f"correlation acceptance: cannot read {path}: {type(exc).__name__}: {exc} — UNMEASURED",
                  file=sys.stderr)
            return EXIT_MISSING
    offset = (timedelta(minutes=args.serve_utc_offset_minutes)
              if args.serve_utc_offset_minutes is not None else _local_offset())
    report = join_token(args.token, sources, serve_offset=offset)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"correlation {args.token}: {report['verdict']} ({report['sightings']} sightings)")
        for name, hop in report["hops"].items():
            print(f"  {name:5} {hop['at']}  {hop['detail']}  [{hop['source']}]")
        for name in report["missing"]:
            print(f"  {name:5} MISSING — not a pass")
    if report["verdict"] == VERDICT_JOINED:
        return EXIT_JOINED
    return EXIT_MISSING if report["verdict"] == VERDICT_MISSING else EXIT_OUT_OF_ORDER


if __name__ == "__main__":
    raise SystemExit(main())
