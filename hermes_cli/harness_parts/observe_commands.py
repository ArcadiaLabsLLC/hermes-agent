"""``hermes harness observe snapshot-builds``: every snapshot build in a window, from its receipts.

Read-only; the derivation is ``agent_runtime.snapshot_build_census``'s.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

__layer__ = "wiring"
__all__ = ["_cmd_observe_snapshot_builds"]


def _cmd_observe_snapshot_builds(args) -> int:
    from agent_runtime.cli_format import emit_json
    from agent_runtime.snapshot_build_census import (
        census_builds, default_log_path, format_census, log_files, parse_duration, read_lines,
    )

    try:
        window = parse_duration(getattr(args, "since", "1h") or "1h")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    log = Path(args.log) if getattr(args, "log", None) else default_log_path()
    files = log_files(log)
    report = census_builds(read_lines(files), since=datetime.now() - window)
    report["window"]["files"] = [str(path) for path in files]
    print(emit_json(report) if getattr(args, "json", False) else format_census(report))
    return 0
