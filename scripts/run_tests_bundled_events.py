"""Per-file results out of one bundle process (``scripts/run_tests_bundled.py``).

The bundle plugin (``scripts/_bundle_plugin/hermes_bundle_report.py``) writes
one JSON line per session start/end, collected module and test report; this
module folds those lines into per-file tallies and decides, from them and the
process exit code, which members of a bundle must be re-run alone.

Generic on purpose (no fork paths), like the runner's core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

_CATEGORIES = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")


# ── Per-file results out of one bundle process ──────────────────────────────


@dataclass
class FileTally:
    counts: Dict[str, int] = field(default_factory=dict)
    collect_seconds: float = 0.0
    test_seconds: float = 0.0
    collect_error: bool = False
    failed_nodeids: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        out = {k: v for k, v in self.counts.items() if v}
        if self.collect_error:
            out["errors"] = out.get("errors", 0) + 1
        return out

    @property
    def clean(self) -> bool:
        return not self.collect_error and not self.counts.get("failed") and not self.counts.get("errors")


@dataclass
class BundleEvents:
    files: Dict[str, FileTally] = field(default_factory=dict)
    session_start: Optional[float] = None
    session_end: Optional[float] = None
    exit_status: Optional[int] = None


def tally_events(lines: Iterable[str]) -> BundleEvents:
    """Fold the plugin's JSON lines into per-file tallies. A torn last line
    (process killed mid-write) is ignored."""

    events = BundleEvents()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = record.get("k")
        if kind == "start":
            events.session_start = record.get("t")
        elif kind == "end":
            events.session_end = record.get("t")
            events.exit_status = record.get("rc")
        elif kind == "collect":
            tally = events.files.setdefault(record["f"], FileTally())
            tally.collect_seconds += float(record.get("d") or 0.0)
            tally.collect_error = tally.collect_error or bool(record.get("err"))
        elif kind == "test":
            tally = events.files.setdefault(record["f"], FileTally())
            tally.test_seconds += float(record.get("d") or 0.0)
            category = record.get("c") or ""
            if category == "error":
                category = "errors"
            if category in _CATEGORIES:
                tally.counts[category] = tally.counts.get(category, 0) + 1
            if record.get("n"):
                tally.failed_nodeids.append(record["n"])
    return events


def effective_bundle_rc(events: BundleEvents, bundle_rc: int) -> int:
    """The bundle's exit status once the recorder's own receipt is read.

    A process exit 0 is only a success when the recorder agrees: a recorded
    session end with a non-zero ``rc`` (bundle 26 of the chat-first-groups
    landing: exit 0, ``rc: 2``, no test events) or no session end at all
    contradicts it, and a contradicted success is a failure — its members are
    then confirmed per file, never labelled green off the exit code."""

    if bundle_rc != 0:
        return bundle_rc
    if events.session_end is None:
        return 1
    return int(events.exit_status or 0)


def members_to_rerun(member_rels: Sequence[str], events: BundleEvents, bundle_rc: int) -> List[str]:
    """The members of a non-zero bundle that must be re-run alone.

    A member is re-run when it recorded a failure or error, or recorded
    nothing at all. When the session never reached its end (killed by the
    timeout, crashed), a clean tally proves nothing for the member that was
    running and the ones queued behind it, so every member from the last one
    that recorded a test onward is re-run too. If the bundle failed but no
    member carries the failure (a session-level error), every member is
    re-run. ``bundle_rc`` is read through :func:`effective_bundle_rc`, so a
    zero exit the recorder contradicts is a failure; a zero-exit bundle the
    recorder confirms re-runs only a member that recorded nothing at all."""

    bundle_rc = effective_bundle_rc(events, bundle_rc)
    if bundle_rc == 0:
        return [rel for rel in member_rels if rel not in events.files]
    complete = set(member_rels)
    if events.session_end is None:
        ran = [i for i, rel in enumerate(member_rels) if rel in events.files and events.files[rel].counts]
        complete = set(member_rels[: ran[-1]]) if ran else set()
    rerun = [
        rel
        for rel in member_rels
        if rel not in complete or rel not in events.files or not events.files[rel].clean
    ]
    return rerun or list(member_rels)
