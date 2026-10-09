"""The last N live chat turns against the committed latency budgets (h-live-check, owner 2026-10-07).

``hermes harness observe turn-timing --check`` is the door. Read-only, from receipts only:

* the serve home's ``agent.log``: ``chat_turn_accept_to_anchor`` (``turn=``);
* the persona profile's ``agent.log`` (a turn logs under the profile it runs in, so every sibling
  profile log is read): ``send_prep_receipt`` (``turn=``), then the first ``send_window_receipt``
  after it in the same file and the ``stream_gap_receipt`` of that request;
* the Launcher's ``[MissionChatTiming]`` line, joined on ``turn_id=`` when the diag log exists, for its
  ``send=`` (the cold group) and its stamp (the turn's end) only. Its UI spans (``send_to_admit``,
  ``ui_build_*``, ``ui_apply_to_paint``) are not read here: the launcher's budget registry
  (``EterniaLauncher/tool/perf_budgets/budgets.json``) owns them (owner D2, 2026-10-08).

Each turn falls in one GROUP: ``cold`` (the first turn after a serve boot, a turn within
``cold_after_boot_s`` of one, or a Launcher ``send=first_in_process``), ``after-idle`` (warm, but
the previous turn on the same chat ended over ``idle_gap_s`` earlier), else ``warm``. A
``warm_only`` budget is judged on ``warm`` and ``after-idle`` and only reported on ``cold``; the
others are judged on every group. Provider spans are reported, never judged.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

__layer__ = "wiring"

GROUPS: tuple[str, ...] = ("warm", "after-idle", "cold")

_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,(\d{3}))?")
_LAUNCHER_STAMP = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T[^\]]+)\]")
_PAIR = re.compile(r"([a-z_]+)=(\S+)")
_CHAT_PREFIX = re.compile(r"\[(persona_chat_[^\]\s]+)\]")
_MARKERS = {
    "chat_turn_accept_to_anchor ": "accept",
    "send_prep_receipt ": "prep",
    "send_window_receipt ": "window",
    "stream_gap_receipt ": "gap",
}
_LAUNCHER_MARKER = "[MissionChatTiming] "


def default_budgets_path() -> Path:
    return Path(__file__).resolve().parent / "turn_latency_budgets.json"


def load_budgets(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or default_budgets_path()).read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_local_stamp(text: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.astimezone()


def _log_stamp(line: str) -> datetime | None:
    match = _STAMP.match(line)
    if not match:
        return None
    local = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") + timedelta(
        milliseconds=int(match.group(2) or 0))
    return local.astimezone(timezone.utc)


def parse_receipt(line: str) -> dict[str, Any] | None:
    """One hermes receipt line as ``{kind, at, fields, chat}``, or ``None``."""

    for marker, kind in _MARKERS.items():
        if marker in line:
            at = _log_stamp(line)
            if at is None:
                return None
            chat = _CHAT_PREFIX.search(line.split(marker, 1)[0])
            return {"kind": kind, "at": at, "fields": dict(_PAIR.findall(line.split(marker, 1)[1])),
                    "chat": chat.group(1) if chat else None}
    return None


def parse_launcher(line: str) -> dict[str, Any] | None:
    if _LAUNCHER_MARKER not in line:
        return None
    fields = dict(_PAIR.findall(line.split(_LAUNCHER_MARKER, 1)[1]))
    if not fields.get("turn_id"):
        return None
    stamp = _LAUNCHER_STAMP.match(line)
    return {"turn": fields["turn_id"], "send": fields.get("send"),
            "at": _parse_local_stamp(stamp.group(1)) if stamp else None}


def _turn(state: dict[str, Any], turn_id: str) -> dict[str, Any]:
    return state["turns"].setdefault(turn_id, {"turn_id": turn_id, "anchor": None, "chat": None, "end": None,
                                               "spans": {}, "launcher_send": None})


def _on_accept(state: dict[str, Any], row: dict[str, Any]) -> None:
    fields = row["fields"]
    if not fields.get("turn"):
        return
    entry = _turn(state, fields["turn"])
    entry["anchor"] = row["at"]
    entry["chat"] = entry["chat"] or row["chat"]
    if _num(fields.get("total_ms")) is not None:
        entry["spans"]["accept_to_anchor"] = _num(fields["total_ms"])


def _on_prep(state: dict[str, Any], row: dict[str, Any]) -> None:
    fields = row["fields"]
    if not fields.get("turn"):
        return
    entry = state["open_prep"] = _turn(state, fields["turn"])
    if entry["anchor"] is None:
        entry["anchor"] = _parse_local_stamp(fields.get("anchored_at", "")) or row["at"]
    if _num(fields.get("total_ms")) is not None:
        entry["spans"]["send_prep_total"] = _num(fields["total_ms"])


def _on_window(state: dict[str, Any], row: dict[str, Any]) -> None:
    entry, fields = state["open_prep"], row["fields"]
    if entry is None:
        return
    state["open_prep"] = None
    request = fields.get("request", "")
    state["requests"][request] = entry
    entry["chat"] = entry["chat"] or (request.split(":", 1)[0] or None)
    entry["spans"]["conn"] = fields.get("conn")
    if _num(fields.get("server_wait_ms")) is not None:
        entry["spans"]["server_wait"] = _num(fields["server_wait_ms"])
    entry["end"] = row["at"]


def _on_gap(state: dict[str, Any], row: dict[str, Any]) -> None:
    fields = row["fields"]
    entry = state["requests"].pop(fields.get("request"), None)
    if entry is None:
        return
    if fields.get("end") == "text" and _num(fields.get("gap_ms")) is not None:
        entry["spans"]["first_event_to_text"] = _num(fields["gap_ms"])
    entry["end"] = row["at"]


#: Receipt kind (``_MARKERS``) -> its handler; one row per kind, no ladder.
_RECEIPT_HANDLERS = {"accept": _on_accept, "prep": _on_prep, "window": _on_window, "gap": _on_gap}


def collect_turns(log_sources: Iterable[Iterable[str]], launcher_lines: Iterable[str]) -> list[dict[str, Any]]:
    """Every turn a hermes receipt names, oldest first, with its spans joined.

    ``log_sources`` is one line iterable per log FILE: a send window is the first one after its
    send_prep in that same file, before the file's next send_prep.
    """

    turns: dict[str, dict[str, Any]] = {}
    for lines in log_sources:
        state = {"turns": turns, "open_prep": None, "requests": {}}
        for row in filter(None, map(parse_receipt, lines)):
            _RECEIPT_HANDLERS[row["kind"]](state, row)
    for row in filter(None, map(parse_launcher, launcher_lines)):
        if row["turn"] in turns:
            entry = turns[row["turn"]]
            entry["launcher_send"] = row["send"]
            entry["launcher"] = True
            if row["at"] is not None:
                entry["end"] = row["at"]
    return sorted((t for t in turns.values() if t["anchor"] is not None), key=lambda t: t["anchor"])


def classify(turns: list[dict[str, Any]], boots: Iterable[datetime], budgets: dict[str, Any]) -> None:
    """Stamp each turn's ``group`` and ``why`` in place (needs EVERY turn, not only the last N)."""

    boots = sorted(boots)
    cold_s, idle_s = float(budgets.get("cold_after_boot_s", 120)), float(budgets.get("idle_gap_s", 30))
    seen_boots: set[datetime] = set()
    last_end: dict[Any, datetime] = {}
    for entry in turns:
        anchor = entry["anchor"]
        boot = max((b for b in boots if b <= anchor), default=None)
        previous = last_end.get(entry["chat"]) or last_end.get(None)
        if boot is not None and boot not in seen_boots:
            entry["group"], entry["why"] = "cold", "first turn after serve boot"
        elif boot is not None and (anchor - boot).total_seconds() < cold_s:
            entry["group"], entry["why"] = "cold", f"within {cold_s:.0f} s of serve boot"
        elif entry["launcher_send"] not in (None, "warm"):
            entry["group"], entry["why"] = "cold", f"launcher send={entry['launcher_send']}"
        elif previous is not None and (anchor - previous).total_seconds() > idle_s:
            entry["group"] = "after-idle"
            entry["why"] = f"previous turn on this chat ended {(anchor - previous).total_seconds():.0f} s earlier"
        else:
            entry["group"], entry["why"] = "warm", ""
        if boot is not None:
            seen_boots.add(boot)
        end = entry["end"] or anchor
        last_end[entry["chat"]] = end
        last_end[None] = end


def _range(values: list[Any]) -> str:
    nums = [v for v in values if isinstance(v, float)]
    if nums:
        return f"{min(nums):.0f}-{max(nums):.0f} ms"
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return ",".join(f"{k}x{n}" for k, n in counts.items())


def judge(turns: list[dict[str, Any]], budgets: dict[str, Any]) -> dict[str, Any]:
    """One row per (group, span): status PASS / FAIL / INFO / REPORT / NO DATA."""

    rows = []
    for group in GROUPS:
        members = [t for t in turns if t["group"] == group]
        if not members:
            continue
        for budget in budgets.get("budgets", []):
            span = budget["span"]
            values = [t["spans"][span] for t in members if t["spans"].get(span) is not None]
            failing = [t["turn_id"] for t in members if t["spans"].get(span) is not None and (
                t["spans"][span] != budget["equals"] if "equals" in budget else t["spans"][span] > budget["max_ms"])]
            limit = f"= {budget['equals']}" if "equals" in budget else f"<= {budget['max_ms']} ms"
            if not values:
                status = "NO DATA"
            elif budget.get("warm_only") and group == "cold":
                status = "INFO"
            else:
                status = "FAIL" if failing else "PASS"
            rows.append({"group": group, "span": span, "status": status, "observed": _range(values),
                         "n": len(values), "budget": limit, "baseline": budget.get("baseline"),
                         "failing_turns": failing if status == "FAIL" else []})
        for reported in budgets.get("reported", []):
            values = [t["spans"][reported["span"]] for t in members if t["spans"].get(reported["span"]) is not None]
            rows.append({"group": group, "span": reported["span"], "status": "REPORT" if values else "NO DATA",
                         "observed": _range(values), "n": len(values), "budget": "provider (not judged)",
                         "baseline": reported.get("baseline"), "failing_turns": []})
    return {"rows": rows, "failed": sorted({r["span"] for r in rows if r["status"] == "FAIL"})}


def check(*, log_sources: Iterable[Iterable[str]], launcher_lines: Iterable[str] | None, boots: Iterable[datetime],
          budgets: dict[str, Any], last: int = 10, start: datetime | None = None,
          end: datetime | None = None) -> dict[str, Any]:
    """The whole check: collect, classify over every turn, keep the window's last ``last``, judge."""

    turns = collect_turns(log_sources, launcher_lines or ())
    classify(turns, boots, budgets)
    kept = [t for t in turns if (start is None or t["anchor"] >= start) and (end is None or t["anchor"] <= end)]
    kept = kept[-last:] if last > 0 else kept
    verdict = judge(kept, budgets)
    return {
        "seeded": budgets.get("seeded"),
        "turns": [{"turn_id": t["turn_id"], "anchor": t["anchor"].isoformat(), "group": t["group"],
                   "why": t["why"], "chat": t["chat"], "spans": t["spans"]} for t in kept],
        "groups": {g: sum(1 for t in kept if t["group"] == g) for g in GROUPS},
        "launcher_log": launcher_lines is not None,
        **verdict,
        "result": "FAIL" if verdict["failed"] else ("PASS" if kept else "NO TURNS"),
    }


def format_check(report: dict[str, Any]) -> str:
    groups = report["groups"]
    turns = report["turns"]
    span = (f"{_local(turns[0]['anchor'])} -> {_local(turns[-1]['anchor'])}" if turns else "no turns")
    lines = [f"turn-latency check: {len(turns)} turn(s) ({groups['warm']} warm, {groups['after-idle']} after-idle, "
             f"{groups['cold']} cold) {span}; baseline {report['seeded']}"]
    if not report["launcher_log"]:
        lines.append("  launcher diag log absent: no launcher send= for the cold group; every span still checked")
    for turn in turns:
        if turn["group"] != "warm":
            lines.append(f"  {turn['group']:<10} {turn['turn_id']}  ({turn['why']})")
    for row in report["rows"]:
        failing = f"  turns: {', '.join(row['failing_turns'])}" if row["failing_turns"] else ""
        lines.append(f"[{row['group']:<10}] {row['status']:<7} {row['span']:<20} {row['observed']:<16} "
                     f"budget {row['budget']:<22} baseline {row['baseline']}{failing}")
    lines.append(f"result: {report['result']}" + (f" ({', '.join(report['failed'])})" if report["failed"] else ""))
    return "\n".join(lines)


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def serve_boots(store_root: Path) -> list[datetime]:
    """Every serve start the store remembers: live ``<pid>.json`` and each ``<pid>.stderr.log`` header."""

    boots = []
    folder = Path(store_root) / "serve_instances"
    for path in folder.glob("*.json"):
        if path.name.endswith(".ended.json"):
            continue
        try:
            stamp = _parse_local_stamp(json.loads(path.read_text(encoding="utf-8")).get("started_at", ""))
        except (OSError, ValueError, AttributeError):
            stamp = None
        if stamp:
            boots.append(stamp)
    for path in folder.glob("*.stderr.log"):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                head = handle.readline()
        except OSError:
            continue
        match = re.search(r"started=(\S+)", head)
        if match and _parse_local_stamp(match.group(1)):
            boots.append(_parse_local_stamp(match.group(1)))
    return sorted(set(boots))


def agent_logs(home: Path) -> list[Path]:
    """The serve home's ``agent.log`` (rotations included) and every profile's current ``agent.log``."""

    from agent_runtime.snapshot_build_census import log_files

    found = list(log_files(home / "logs" / "agent.log"))
    for pattern in (home.parent.glob("*/logs/agent.log"), (home / "profiles").glob("*/logs/agent.log")):
        found.extend(pattern)
    unique: dict[str, Path] = {}
    for path in found:
        if path.exists():
            unique.setdefault(str(path.resolve()).lower(), path)
    return list(unique.values())


def parse_local(text: str) -> datetime:
    """``YYYY-MM-DD HH:MM[:SS]`` in local time (or ISO with an offset), as aware UTC."""

    stamp = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return (stamp if stamp.tzinfo else stamp.astimezone()).astimezone(timezone.utc)
