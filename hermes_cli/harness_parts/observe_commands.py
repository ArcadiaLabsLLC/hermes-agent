"""``hermes harness observe snapshot-builds`` / ``turn-timing``: builds and turns in a window, from receipts.

Read-only; the derivations are ``agent_runtime.snapshot_build_census``'s and
``agent_runtime.turn_timing_census``'s.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from agent_runtime.root_observability import attach_root_observability

__layer__ = "wiring"
__all__ = ["_cmd_observe_snapshot_builds", "_cmd_observe_turn_check", "_cmd_observe_turn_timing"]


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
    from agent_runtime import paths
    from agent_runtime.turn_timing_census import live_serve_home
    from hermes_cli.logs import LOG_FILES

    home, serve_pid = live_serve_home(paths.store_root())
    if getattr(args, "log", None):
        log, source = Path(args.log), "--log"
    elif home is not None:
        log, source = home / "logs" / LOG_FILES["agent"], f"live serve pid {serve_pid}"
    else:
        log, source = default_log_path(), "no live serve; this CLI's profile"
    files = log_files(log)
    report = census_builds(read_lines(files), since=datetime.now() - window)
    report["window"]["files"] = [str(path) for path in files]
    report["home"] = {"path": str(log.parent.parent), "source": source}
    print(emit_json(attach_root_observability(report)) if getattr(args, "json", False) else format_census(report))
    return 0


def _cmd_observe_turn_timing(args) -> int:
    """Each turn's spans against the committed baseline, on the LIVE serve's home.

    The home is the one the running serve registered (``serve_instances/<pid>.json``),
    never this CLI's sticky profile: the two differ whenever the Launcher spawned the
    serve on another profile. ``--log`` overrides it.
    """

    if getattr(args, "check", False):
        return _cmd_observe_turn_check(args)

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
    print(emit_json(attach_root_observability(report)) if getattr(args, "json", False) else format_report(report))
    return 0


def _cmd_observe_turn_check(args) -> int:
    """``turn-timing --check``: the last N turns' receipts against the committed latency budgets.

    Reads the live serve's home log and every sibling profile's (a turn logs under the profile it
    runs in), and the Launcher diag log when one exists. Exit 1 on any FAIL, 2 when nothing to judge.
    """

    from agent_runtime import paths
    from agent_runtime.cli_format import emit_json
    from agent_runtime.snapshot_build_census import default_log_path, read_lines
    from agent_runtime.turn_latency_check import (
        agent_logs, check, format_check, load_budgets, parse_local, serve_boots,
    )
    from agent_runtime.turn_timing_census import default_launcher_log, live_serve_home

    try:
        budgets = load_budgets(Path(args.budgets) if getattr(args, "budgets", None) else None)
        start = parse_local(args.from_time) if getattr(args, "from_time", None) else None
        end = parse_local(args.to_time) if getattr(args, "to_time", None) else None
    except (OSError, ValueError) as exc:
        print(f"turn-timing --check: {exc}", file=sys.stderr)
        return 2
    store_root = paths.store_root()
    if getattr(args, "log", None):
        logs = [Path(args.log)]
    else:
        home, _pid = live_serve_home(store_root)
        logs = agent_logs(home) if home is not None else agent_logs(default_log_path().parent.parent)
    launcher_path = Path(args.launcher_log) if getattr(args, "launcher_log", None) else default_launcher_log()
    launcher_lines = (list(read_lines([launcher_path])) if launcher_path is not None and launcher_path.exists()
                      else None)
    report = check(log_sources=[read_lines([path]) for path in logs], launcher_lines=launcher_lines,
                   boots=serve_boots(store_root), budgets=budgets, last=getattr(args, "last", 10) or 0,
                   start=start, end=end)
    report["logs"] = [str(path) for path in logs]
    report["launcher_log_path"] = str(launcher_path) if launcher_lines is not None else None
    print(emit_json(attach_root_observability(report)) if getattr(args, "json", False) else format_check(report))
    if report["result"] == "FAIL":
        return 1
    return 2 if report["result"] == "NO TURNS" else 0
