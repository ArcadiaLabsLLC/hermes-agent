"""Every chat turn in a window, span by span, against a committed baseline (h-perf-guard, owner ask 2026-10-06).

Read-only, three sources joined per turn on the client message id:

* the turn record's ``phases`` (``<store>/mission_chat_turns/*.json``, schema v3): the marks a
  turn passed, in ms from its anchor, cut here into consecutive SEGMENTS so a regression is
  named where it happened rather than smeared over every later mark;
* the serve's ``chat_turn_accept_to_anchor`` receipt (``agent.log`` and its rotations): the
  accept -> anchor span, joined on its ``turn=`` key, or for a line written before that key
  existed, on the anchor instant (within :data:`ANCHOR_JOIN_S`);
* the Launcher's ``[MissionChatTiming]`` diag line, joined on ``turn_id=``: the spans no hermes
  receipt can see (send -> admit, settle).

A span is REGRESSED when it is over :data:`REGRESSION_RATIO` x its baseline and at least
:data:`REGRESSION_FLOOR_MS` over it (3 ms against 1 ms is noise, not a regression); a count is
regressed when it is over its baseline at all. The two provider spans (:data:`PROVIDER_SPANS`)
are named apart. ``hermes harness observe turn-timing`` is the door.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from agent_runtime.snapshot_build_census import log_files, read_lines

__layer__ = "wiring"

REGRESSION_RATIO = 1.5
REGRESSION_FLOOR_MS = 25
ANCHOR_JOIN_S = 1.0

#: Segment name -> (from mark, to mark) on the turn record's ``phases``; in turn order.
SEGMENTS: tuple[tuple[str, str, str], ...] = (
    ("anchor_to_write_ahead", "request_received", "write_ahead"),
    ("write_ahead_to_agent_ready", "write_ahead", "agent_ready"),
    ("agent_ready_to_request_sent", "agent_ready", "request_sent"),
    ("request_sent_to_headers", "request_sent", "response_headers"),
    ("headers_to_first_byte", "response_headers", "provider_first_byte"),
    ("first_byte_to_stream_done", "provider_first_byte", "stream_done"),
    ("stream_done_to_projected", "stream_done", "projected"),
    ("anchor_to_request_sent", "request_received", "request_sent"),
)
#: The provider's own time: reported and compared, but kept apart so a slow vendor is never read
#: as a hermes regression.
PROVIDER_SPANS: frozenset[str] = frozenset({"request_sent_to_headers", "headers_to_first_byte"})
#: Counters off the same ``phases`` block: any value over the baseline is a regression.
COUNTS: tuple[str, ...] = ("visibility_bundle_builds", "builds_overlapped", "prewarm_overlapped")
#: ``[MissionChatTiming]`` keys (launcher ``agent_console_turn_timeline.dart``), ``_ms`` dropped.
LAUNCHER_SPANS: tuple[str, ...] = (
    "enqueue_to_dispatch", "send_to_admit", "admit_to_first_delta", "first_delta_to_end", "end_to_settle",
)

_PAIR = re.compile(r"([a-z_]+)=(\S+)")
_LOG_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,(\d{3}))?")
_ACCEPT_ANCHOR = "chat_turn_accept_to_anchor "
_LAUNCHER_ANCHOR = "[MissionChatTiming] "


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc(text: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def read_turn_records(store_root: Path, *, since: datetime) -> list[dict[str, Any]]:
    """Every turn record anchored at or after ``since`` (aware UTC), oldest first."""

    turns = []
    for path in sorted((Path(store_root) / "mission_chat_turns").glob("*.json")):
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for turn_id, record in (session.items() if isinstance(session, dict) else ()):
            phases = record.get("phases") if isinstance(record, dict) else None
            anchored = _utc(phases.get("anchored_at", "")) if isinstance(phases, dict) else None
            if anchored is None or anchored < since:
                continue
            timing = record.get("profile_timing") or {}
            turns.append({"turn_id": str(turn_id), "anchored_at": anchored, "phases": phases,
                          "actor_reused": timing.get("resident_actor_reused")})
    return sorted(turns, key=lambda turn: turn["anchored_at"])


def parse_accept_line(line: str) -> dict[str, Any] | None:
    """One ``chat_turn_accept_to_anchor`` receipt, stamped in aware UTC, or ``None``."""

    if _ACCEPT_ANCHOR not in line:
        return None
    match = _LOG_STAMP.match(line)
    if not match:
        return None
    local = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") + timedelta(
        milliseconds=int(match.group(2) or 0))
    fields = dict(_PAIR.findall(line.split(_ACCEPT_ANCHOR, 1)[1]))
    return {"at": local.astimezone(timezone.utc), "turn": fields.get("turn"),
            "accept_queue": _int(fields.get("queue_ms")), "accept_to_anchor": _int(fields.get("total_ms"))}


def parse_launcher_line(line: str) -> dict[str, Any] | None:
    """One ``[MissionChatTiming]`` line's turn id and launcher spans, or ``None``."""

    if _LAUNCHER_ANCHOR not in line:
        return None
    fields = dict(_PAIR.findall(line.split(_LAUNCHER_ANCHOR, 1)[1]))
    if not fields.get("turn_id"):
        return None
    spans = {name: _int(fields.get(f"{name}_ms")) for name in LAUNCHER_SPANS}
    return {"turn": fields["turn_id"], **{k: v for k, v in spans.items() if v is not None}}


def turn_spans(turn: dict[str, Any]) -> dict[str, int]:
    """The record's segments and counts; a segment whose either mark is absent has no key."""

    phases = turn["phases"]
    spans = {}
    for name, start, end in SEGMENTS:
        a, b = _int(phases.get(start)), _int(phases.get(end))
        if a is not None and b is not None:
            spans[name] = max(0, b - a)
    for name in COUNTS:
        if _int(phases.get(name)) is not None:
            spans[name] = _int(phases.get(name))
    return spans


def join_turns(turns: list[dict[str, Any]], log_lines: Iterable[str],
               launcher_lines: Iterable[str]) -> list[dict[str, Any]]:
    """Each turn with every span the three sources hold for it."""

    accepts = [row for row in map(parse_accept_line, log_lines) if row]
    launcher = {row["turn"]: row for row in map(parse_launcher_line, launcher_lines) if row}
    joined = []
    for turn in turns:
        spans = turn_spans(turn)
        accept = next((row for row in accepts if row["turn"] == turn["turn_id"]), None)
        if accept is None:
            near = [row for row in accepts if row["turn"] is None
                    and abs((row["at"] - turn["anchored_at"]).total_seconds()) <= ANCHOR_JOIN_S]
            accept = min(near, key=lambda row: abs(row["at"] - turn["anchored_at"]), default=None)
        if accept is not None:
            spans.update({k: accept[k] for k in ("accept_queue", "accept_to_anchor") if accept[k] is not None})
        spans.update({k: v for k, v in (launcher.get(turn["turn_id"]) or {}).items() if k != "turn"})
        joined.append({**turn, "spans": spans})
    return joined


def compare(joined: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Each turn's spans against ``baseline``; ``regressed`` names the spans over it."""

    base_ms, base_counts = baseline.get("spans_ms") or {}, baseline.get("counts") or {}
    rows = []
    for turn in joined:
        spans, regressed, provider = {}, [], []
        for name, value in turn["spans"].items():
            base = base_counts.get(name) if name in COUNTS else base_ms.get(name)
            over = base is not None and (
                value > base if name in COUNTS
                else value > REGRESSION_RATIO * base and value - base >= REGRESSION_FLOOR_MS)
            spans[name] = {"value": value, "baseline": base,
                           "ratio": round(value / base, 2) if base else None, "regressed": over}
            if over:
                (provider if name in PROVIDER_SPANS else regressed).append(name)
        rows.append({"turn_id": turn["turn_id"], "anchored_at": turn["anchored_at"].isoformat(),
                     "actor_reused": turn["actor_reused"], "spans": spans, "regressed": regressed,
                     "provider_regressed": provider})
    return rows


def census_turn_timing(*, store_root: Path, log: Path, launcher_log: Path | None, baseline: dict[str, Any],
                       since: datetime) -> dict[str, Any]:
    """The whole report: the window, its sources, and every turn compared."""

    turns = read_turn_records(store_root, since=since)
    launcher_files = log_files(launcher_log) if launcher_log is not None else []
    joined = join_turns(turns, read_lines(log_files(log)), read_lines(launcher_files))
    rows = compare(joined, baseline)
    return {
        "window": {"since": since.isoformat(), "log": str(log),
                   "launcher_log": [str(p) for p in launcher_files], "store_root": str(store_root)},
        "baseline": {"seeded": baseline.get("seeded"), "ratio": REGRESSION_RATIO, "floor_ms": REGRESSION_FLOOR_MS},
        "turns": rows,
        "regressed_turns": sum(1 for row in rows if row["regressed"]),
        "provider_regressed_turns": sum(1 for row in rows if row["provider_regressed"]),
    }


def format_report(report: dict[str, Any]) -> str:
    window, base = report["window"], report["baseline"]
    lines = [f"turn-timing since {window['since']}: {len(report['turns'])} turn(s), "
             f"{report['regressed_turns']} regressed on hermes spans, {report['provider_regressed_turns']} on "
             f"provider spans (>{base['ratio']}x baseline {base['seeded']})",
             f"  home: {report.get('home', {}).get('path')} ({report.get('home', {}).get('source')})"]
    for row in report["turns"]:
        reused = {True: "reused", 1: "reused", False: "built", 0: "built"}.get(row["actor_reused"], "?")
        lines.append(f"turn {row['turn_id']}  {row['anchored_at']}  actor={reused}")
        for name, span in row["spans"].items():
            unit = "" if name in COUNTS else " ms"
            base_text = "-" if span["baseline"] is None else f"{span['baseline']}{unit}"
            flag = f"  REGRESSED {span['ratio']}x" if span["regressed"] and span["ratio"] else (
                "  REGRESSED" if span["regressed"] else "")
            if flag and name in PROVIDER_SPANS:
                flag += " (provider)"
            lines.append(f"  {name:<28} {span['value']:>7}{unit:<3} base {base_text:>9}{flag}")
    return "\n".join(lines)


def default_baseline_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "turn_timing_baseline.json"


def default_launcher_log() -> Path | None:
    """The newest ``<system-temp>/eternia_launcher_diag[.<profile>].log``, if one exists."""

    import tempfile

    found = sorted(Path(tempfile.gettempdir()).glob("eternia_launcher_diag*.log"),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    return found[0] if found else None


def live_serve_home(store_root: Path) -> tuple[Path | None, int | None]:
    """The home the LIVE serve registered (``serve_instances/<pid>.json``), newest first."""

    from agent_runtime.serve_registry import CLASSIFICATION_LIVE, list_serve_instances

    live = [row for row in list_serve_instances(store_root)
            if row.get("classification") == CLASSIFICATION_LIVE and row.get("hermes_home")]
    if not live:
        return None, None
    row = max(live, key=lambda item: str(item.get("started_at") or ""))
    return Path(row["hermes_home"]), row.get("pid")
