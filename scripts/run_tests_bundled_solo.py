"""What a single-file process of the bundled runner runs with.

``scripts/run_tests_bundled.py`` owns execution; this module owns the rules that
make one file's process different from the default solo
(``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md``):

* **known reds** (§2) — a file red or timed out in the last recorded run runs
  ONCE, alone, with no flake retry, no straggler retry and a capped timeout
  (:func:`known_red_timeout`); its output says so and names how its failing
  set moved since the record. A NEW red keeps the full path (bundle → re-run
  alone → leak diagnosis): that is the isolation-leak instrument.

:class:`SoloPolicy` is the one object ``run`` asks, per single-file process,
for its timeout, flake retries and extra pytest args, and which files must
not enter a bundle.

Generic on purpose (no fork path), like the runner's core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

# ── §2: known reds ──────────────────────────────────────────────────────────

#: a known red with no green duration on this box (owner ruling Q5, 2026-10-10;
#: the first load-induced false timeout lifts it to 180 s, recorded in the plan)
NO_GREEN_CAP_SECONDS = 120.0
#: the floor under twice a known red's last green duration
MIN_CAP_SECONDS = 60.0


def green_seconds(durations: Mapping[str, float], rel: str) -> Optional[float]:
    """The file's last CLEAN-pass seconds, or None. The durations file is keyed by
    ``run_tests_parallel._format_file``'s spelling (OS separators); a POSIX key
    is read too."""

    value = durations.get(str(Path(rel))) or durations.get(rel)
    return float(value) if value else None


def known_red_timeout(rel: str, durations: Mapping[str, float], flat: float) -> float:
    """``min(flat, max(60, 2 × green))`` for a known red with a green duration,
    else ``min(flat, 120)`` — never above the flat timeout, so the cap only ever
    shortens a file that is already red (fast-gate §2, owner ruling Q5)."""

    green = green_seconds(durations, rel)
    if green is None:
        return min(flat, NO_GREEN_CAP_SECONDS)
    return min(flat, max(MIN_CAP_SECONDS, 2.0 * green))


#: ``FileOutcome.via`` (and the ledger's process kind) of a known red's one run
KNOWN_RED_VIA = "known-red"
#: the default single-file process (``run``'s first-pass solos)
SOLO_VIA = "solo"
#: the per-file runner's exit code for a process killed by its timeout
TIMEOUT_RC = 124


@dataclass
class SoloPolicy:
    """What each single-file process of one run runs with.

    ``rel_of`` spells a path the way the record keys it; ``default_timeout`` is
    the per-file runner's scaler (``_effective_file_timeout``) bound to the
    run. ``known_reds`` is the record's red map and ``timed_out`` its timed-out
    set: together, the files that run once, alone, capped."""

    rel_of: Callable[[Path], str]
    default_timeout: Callable[[Path], float]
    flat_timeout: float
    retries: int
    durations: Mapping[str, float]
    known_reds: Mapping[str, frozenset] = field(default_factory=dict)
    timed_out: frozenset = frozenset()

    @property
    def known(self) -> frozenset:
        return frozenset(self.known_reds) | self.timed_out

    def alone(self) -> frozenset:
        """Files that never enter a bundle."""

        return self.known

    def jobs(self, solo_order: Sequence[Path]) -> List[Tuple[Path, str]]:
        """``(path, via)`` for each first-pass solo, in the given order."""

        return [(path, KNOWN_RED_VIA if self.rel_of(path) in self.known else SOLO_VIA) for path in solo_order]

    def budget(self, path: Path, via: str) -> Tuple[float, int, List[str]]:
        """``(timeout, flake retries, extra pytest args)`` for one process."""

        if via == KNOWN_RED_VIA:
            return known_red_timeout(self.rel_of(path), self.durations, self.flat_timeout), 0, []
        return self.default_timeout(path), self.retries, []

    def note(self, rel: str, via: str, rc: int, output: str, tally) -> str:
        """A known red's output, followed by why it ran once and how its failing set
        moved since the record (``tally`` is the recorder's, or None). A trailer,
        so the output still starts the way the per-file runner wrote it."""

        if via != KNOWN_RED_VIA:
            return output
        cap = known_red_timeout(rel, self.durations, self.flat_timeout)
        tail = [f"known red (last recorded run): ran once, alone, no retry, timeout cap {cap:g}s (fast-gate §2)"]
        if rc == TIMEOUT_RC:
            tail.append(f"known-red timeout cap {cap:g}s; run alone: scripts/run_tests.sh {rel}")
        before = self.known_reds.get(rel, frozenset())
        now = frozenset(tally.failed_nodeids) if tally is not None else frozenset()
        if rc != 0 and now != before:
            added, gone = sorted(now - before), sorted(before - now)
            tail.append(f"failing set changed: +{len(added)} −{len(gone)} (the record now carries this run's set)")
            tail += [f"  + {nodeid}" for nodeid in added] + [f"  − {nodeid}" for nodeid in gone]
        return "\n".join([output] + tail)
