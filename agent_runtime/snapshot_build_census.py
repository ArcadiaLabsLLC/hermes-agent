"""Every snapshot build in a window, from its receipts (h-snap-worker, owner ask 2026-10-06).

Reads ``agent.log`` and its rotations; writes nothing; safe against a live serve's
log. Two receipt families are builds: ``snapshot_build_core role=led`` (a led build,
``agent_runtime/snapshot/build_log.py``) and ``snapshot_build_shadow`` (the cache-hit
boot's shadow validation). ``snapshot_worker op=lost`` lines are counted as
fallbacks. A line from before the accounting fields existed has no ``executor=``
and is counted as ``unknown``, never guessed; its ``turns`` are unknown too.

``hermes harness observe snapshot-builds --since <dur> [--json]`` is the door.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

__layer__ = "wiring"

_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_PAIR = re.compile(r"([a-z_]+)=(\S+)")
_LED_ANCHOR = "snapshot_build_core role=led "
_SHADOW_ANCHOR = "snapshot_build_shadow "
_LOST_ANCHOR = "snapshot_worker op=lost "
_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}

EXECUTOR_UNKNOWN = "unknown"


def parse_duration(text: str) -> timedelta:
    """``90s`` / ``30m`` / ``2h`` / ``1d``; anything else is a ``ValueError``."""

    match = _DURATION.match(str(text).strip().lower())
    if not match:
        raise ValueError(f"duration must look like 90s, 30m, 2h or 1d, not {text!r}")
    return timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def log_files(path: Path) -> list[Path]:
    """``agent.log`` and its numbered rotations, oldest first."""

    rotated = []
    for candidate in path.parent.glob(path.name + ".*"):
        suffix = candidate.name[len(path.name) + 1:]
        if suffix.isdigit():
            rotated.append((int(suffix), candidate))
    ordered = [item for _, item in sorted(rotated, reverse=True)]
    if path.exists():
        ordered.append(path)
    return ordered


def read_lines(files: Iterable[Path]) -> Iterable[str]:
    for file in files:
        try:
            with open(file, encoding="utf-8", errors="replace") as handle:
                yield from handle
        except OSError:
            continue


def _when(line: str) -> datetime | None:
    match = _TIMESTAMP.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_build_line(line: str) -> dict[str, Any] | None:
    """One build receipt's facts, or ``None`` when the line is not one."""

    if _LED_ANCHOR in line:
        kind, tail = "led", line[line.index(_LED_ANCHOR):]
    elif _SHADOW_ANCHOR in line:
        kind, tail = "shadow", line[line.index(_SHADOW_ANCHOR):]
    else:
        return None
    fields = dict(_PAIR.findall(tail))
    build_ms = fields.get("build_ms", "")
    turns = fields.get("turns")
    return {
        "kind": kind,
        "at": _when(line),
        "caller": fields.get("caller", "unknown"),
        "reason": fields.get("reason", "shadow" if kind == "shadow" else "-"),
        "build_ms": int(build_ms) if build_ms.isdigit() else None,
        "executor": fields.get("executor", EXECUTOR_UNKNOWN),
        "turns": None if turns is None else [t for t in turns.split(",") if t and t != "-"],
    }


def census_builds(lines: Iterable[str], *, since: datetime | None = None) -> dict[str, Any]:
    """The summary: builds by trigger, total and max build time, executor split, turns."""

    builds: list[dict[str, Any]] = []
    fallbacks = 0
    first = last = None
    for line in lines:
        at = _when(line)
        if since is not None and (at is None or at < since):
            continue
        if _LOST_ANCHOR in line:
            fallbacks += 1
            continue
        row = parse_build_line(line)
        if row is None:
            continue
        builds.append(row)
        first = first or row["at"]
        last = row["at"] or last
    by_trigger: dict[str, dict[str, int]] = {}
    for row in builds:
        key = f"{row['caller']}/{row['reason']}"
        slot = by_trigger.setdefault(key, {"builds": 0, "total_ms": 0, "max_ms": 0})
        slot["builds"] += 1
        slot["total_ms"] += row["build_ms"] or 0
        slot["max_ms"] = max(slot["max_ms"], row["build_ms"] or 0)
    timed = [row["build_ms"] for row in builds if row["build_ms"] is not None]
    turn_ids: list[str] = []
    with_turns = unknown_turns = 0
    for row in builds:
        if row["turns"] is None:
            unknown_turns += 1
            continue
        if row["turns"]:
            with_turns += 1
        turn_ids.extend(t for t in row["turns"] if t != "?" and not t.startswith("+") and t not in turn_ids)
    return {
        "window": {
            "since": None if since is None else since.isoformat(sep=" "),
            "first_build": None if first is None else first.isoformat(sep=" "),
            "last_build": None if last is None else last.isoformat(sep=" "),
        },
        "builds": len(builds),
        "led": sum(1 for row in builds if row["kind"] == "led"),
        "shadow": sum(1 for row in builds if row["kind"] == "shadow"),
        "total_build_ms": sum(timed),
        "max_build_ms": max(timed) if timed else 0,
        "by_trigger": dict(sorted(by_trigger.items())),
        "by_executor": dict(sorted(Counter(row["executor"] for row in builds).items())),
        "worker_fallbacks": fallbacks,
        "turns_affected": {
            "builds_with_turns": with_turns,
            "builds_turns_unknown": unknown_turns,
            "distinct_turns": len(turn_ids),
            "turn_ids": turn_ids,
        },
    }


def format_census(report: dict[str, Any]) -> str:
    executors = " ".join(f"{k}={v}" for k, v in report["by_executor"].items()) or "-"
    triggers = " ".join(f"{k}:{v['builds']}" for k, v in report["by_trigger"].items()) or "-"
    turns = report["turns_affected"]
    return (
        f"snapshot builds={report['builds']} (led={report['led']} shadow={report['shadow']}) "
        f"total_ms={report['total_build_ms']} max_ms={report['max_build_ms']} "
        f"executor[{executors}] fallbacks={report['worker_fallbacks']} "
        f"turns_affected={turns['distinct_turns']} builds_with_turns={turns['builds_with_turns']} "
        f"triggers[{triggers}]"
    )


def default_log_path() -> Path:
    from agent_runtime.core_cache_census import default_log_path as agent_log

    return agent_log()
