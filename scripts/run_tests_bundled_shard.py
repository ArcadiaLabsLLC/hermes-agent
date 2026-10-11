"""Sharding slow files by node id, only when a run is tail-bound (fast-gate §3).

A cold whole-tree run is WORK-bound: an LPT packing of 2026-10-10's 6,422
files moved by +1 to +3 % when every slow file was split, i.e. nothing. A
small run (a warm-cache gate, a landing of a few hundred files) is TAIL-bound:
its makespan is its single longest file. So the planner shards only when
``Σ estimates / jobs < 2 × max estimate``, and only a file whose CACHED green
duration is ≥ 90 s and whose recorded test count is ≥ 2k, into
``k = min(4, ceil(duration / 45))`` processes, each running
``-p hermes_shard --hermes-shard=i/k`` (``scripts/_bundle_plugin/hermes_shard.py``).

A known red is never sharded (it runs once, whole, so its failing set stays
comparable with the record), nor is a file on ``scripts/test_files_unsharded.txt``.

:class:`ShardJoin` turns the k shard outcomes back into ONE outcome per file:
green when every shard is; when a shard is red the file runs once WHOLE
(sharded files are never known reds, so their last whole run was green): green
whole → the file is green and printed as an unsharded-list candidate with the
observed shard diff; red whole → an ordinary red.

Generic on purpose (no fork path but the list's name), like the runner's core.
"""

from __future__ import annotations

import dataclasses
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

#: files that need intra-file order: one per line, ``#`` starts the observed diff
UNSHARDED_LIST = Path("scripts") / "test_files_unsharded.txt"
SHARD_PLUGIN = "hermes_shard"
#: a file is a shard candidate from this many cached green seconds
SHARD_MIN_SECONDS = 90.0
SECONDS_PER_SHARD = 45.0
MAX_SHARDS = 4
#: a shard is worth its repeated collection only with at least this many tests
TESTS_PER_SHARD = 2
#: ``FileOutcome.via`` of the one whole run after a red shard
WHOLE_CHECK_VIA = "whole-check"


def tail_bound(estimates: Sequence[float], jobs: int) -> bool:
    """True when the run's longest file, not its total work, sets the makespan."""

    return bool(estimates) and sum(estimates) / max(1, jobs) < 2.0 * max(estimates)


def shard_count(seconds: Optional[float], tests: int) -> int:
    """``k`` for one file: 1 (whole) unless it is slow enough and has ≥ 2k tests."""

    if not seconds or seconds < SHARD_MIN_SECONDS:
        return 1
    k = min(MAX_SHARDS, math.ceil(seconds / SECONDS_PER_SHARD))
    return k if tests >= TESTS_PER_SHARD * k else 1


@dataclass
class ShardPlan:
    """rel → k (≥ 2) for the files this run splits, and the record's test counts."""

    counts: Dict[str, int] = field(default_factory=dict)
    tail_bound: bool = False
    tests: Dict[str, int] = field(default_factory=dict)

    def line(self) -> str:
        if not self.tail_bound:
            return "work-bound: no sharding"
        return f"tail-bound: sharding {len(self.counts)} files into {sum(self.counts.values())} shards"

    def record(self, ran: Mapping[str, Tuple[float, int]]) -> Dict[str, object]:
        """The run record's ``tests`` key after this run (:func:`tests_after`)."""

        return {"tests": tests_after(self.tests, ran)}

    def vias(self, rel: str) -> List[Tuple[str, List[str]]]:
        """``(via, extra pytest args)`` per shard of ``rel``; ``[]`` when it runs whole."""

        k = self.counts.get(rel, 1)
        if k < 2:
            return []
        return [(f"shard {i}/{k}", ["-p", SHARD_PLUGIN, f"--hermes-shard={i}/{k}"]) for i in range(k)]


def plan_shards(
    estimates: Mapping[str, float],
    green: Mapping[str, Optional[float]],
    tests: Mapping[str, int],
    jobs: int,
    exclude: frozenset,
) -> ShardPlan:
    """The run's :class:`ShardPlan`: nothing unless the run is tail-bound."""

    bound = tail_bound(list(estimates.values()), jobs)
    counts = {} if not bound else {
        rel: k
        for rel in estimates
        if rel not in exclude and (k := shard_count(green.get(rel), int(tests.get(rel) or 0))) >= 2
    }
    return ShardPlan(counts, bound, dict(tests))


def tests_after(previous: Mapping[str, int], ran: Mapping[str, Tuple[float, int]]) -> Dict[str, int]:
    """The record's test counts after a run: every file the run ran is replaced
    by what it showed (kept when it took ≥ ``SHARD_MIN_SECONDS``, the only files
    the planner asks about), files it did not run carry forward."""

    out = {rel: n for rel, n in previous.items() if rel not in ran}
    out.update({rel: n for rel, (seconds, n) in ran.items() if seconds >= SHARD_MIN_SECONDS and n > 0})
    return dict(sorted(out.items()))


class ShardJoin:
    """Collects a sharded file's shard outcomes into one outcome (thread-safe).

    ``feed`` returns the outcomes to record now: ``[]`` while shards are
    pending or the whole run is under way, the joined outcome when every shard
    is green, the whole run's outcome when it lands; any other outcome passes
    straight through."""

    def __init__(self, plan: ShardPlan, rel_of: Callable[[Path], str]) -> None:
        self._plan = plan
        self._rel_of = rel_of
        self._lock = threading.Lock()
        self._pending: Dict[str, list] = {}
        self._red_shards: Dict[str, str] = {}
        #: unsharded-list candidate lines: ``<rel>  # observed: …``
        self.candidates: List[str] = []

    def feed(self, outcome, run_solo: Callable[[Path, str, Optional[int]], None]) -> list:
        """``run_solo(path, via, bundle_index)`` is the runner's single-file
        process, called for the whole run (its outcome comes back through here)."""

        rel = self._rel_of(outcome.file)
        k = self._plan.counts.get(rel, 1)
        if outcome.via == WHOLE_CHECK_VIA:
            return [self._after_whole(rel, outcome)]
        if outcome.via not in {via for via, _args in self._plan.vias(rel)}:
            return [outcome]
        with self._lock:
            shards = self._pending.setdefault(rel, [])
            shards.append(outcome)
            if len(shards) < k:
                return []
            del self._pending[rel]
        red = [s for s in shards if s.rc != 0]
        if not red:
            return [self._joined(shards, k)]
        with self._lock:
            self._red_shards[rel] = "; ".join(f"{s.via} {s.summary}" for s in sorted(red, key=lambda s: s.via))
        run_solo(outcome.file, WHOLE_CHECK_VIA, None)
        return []

    @staticmethod
    def _joined(shards: list, k: int):
        summary: Dict[str, int] = {}
        for shard in shards:
            for key, value in shard.summary.items():
                summary[key] = summary.get(key, 0) + value
        output = "\n".join(s.output for s in sorted(shards, key=lambda s: s.via) if s.output)
        return dataclasses.replace(
            shards[0], rc=0, output=output, summary=summary, seconds=sum(s.seconds for s in shards), via=f"{k} shards"
        )

    def _after_whole(self, rel: str, outcome):
        with self._lock:
            observed = self._red_shards.pop(rel, "")
        if outcome.rc != 0:
            return outcome  # red whole: an ordinary red
        line = f"{rel}  # observed: {observed} red sharded, green whole"
        with self._lock:
            self.candidates.append(line)
        return dataclasses.replace(outcome, output=f"{outcome.output}\nunsharded candidate: {line}".lstrip())

    def closing_lines(self) -> List[str]:
        if not self.candidates:
            return []
        return [
            "",
            f"=== {len(self.candidates)} file(s) red sharded, green whole — candidates for {UNSHARDED_LIST.as_posix()} ===",
            *(f"  {line}" for line in sorted(self.candidates)),
        ]
