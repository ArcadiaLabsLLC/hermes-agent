"""``hermes harness observe snapshot-builds`` / ``turn-timing``: builds and turns in a window, from receipts.

Read-only; the derivations are ``agent_runtime.snapshot_build_census``'s and
``agent_runtime.turn_timing_census``'s.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

__layer__ = "wiring"
__all__ = ["_cmd_observe_snapshot_builds", "_cmd_observe_turn_timing"]


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


def _cmd_observe_turn_timing(args) -> int:
    """Each turn's spans against the committed baseline, on the LIVE serve's home.

    The home is the one the running serve registered (``serve_instances/<pid>.json``),
    never this CLI's sticky profile: the two differ whenever the Launcher spawned the
    serve on another profile. ``--log`` overrides it.
    """

    import json
    from datetime import timezone

    from agent_runtime import paths
    from agent_runtime.cli_format import emit_json
    from agent_runtime.snapshot_build_census import default_log_path, parse_duration
    from agent_runtime.turn_timing_census import (
        census_turn_timing, default_baseline_path, default_launcher_log, format_report, live_serve_home,
    )
    from hermes_cli.logs import LOG_FILES

    try:
        window = parse_duration(getattr(args, "since", "1h") or "1h")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline) if getattr(args, "baseline", None) else default_baseline_path()
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"baseline unreadable: {baseline_path}: {exc}", file=sys.stderr)
        return 2
    store_root = paths.store_root()
    home, serve_pid = live_serve_home(store_root)
    if getattr(args, "log", None):
        log, source = Path(args.log), "--log"
    elif home is not None:
        log, source = home / "logs" / LOG_FILES["agent"], f"live serve pid {serve_pid}"
    else:
        log, source = default_log_path(), "no live serve; this CLI's profile"
    launcher_log = Path(args.launcher_log) if getattr(args, "launcher_log", None) else default_launcher_log()
    report = census_turn_timing(store_root=store_root, log=log, launcher_log=launcher_log, baseline=baseline,
                                since=datetime.now(timezone.utc) - window)
    report["home"] = {"path": str(log.parent.parent), "source": source}
    report["baseline"]["path"] = str(baseline_path)
    print(emit_json(report) if getattr(args, "json", False) else format_report(report))
    return 0
