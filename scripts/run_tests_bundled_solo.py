"""What a single-file process of the bundled runner runs with.

``scripts/run_tests_bundled.py`` owns execution; this module owns the rules that
make one file's process different from the default solo
(``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md``):

* **known reds** (§2) — a file red or timed out in the last recorded run runs
  ONCE, alone, with no flake retry, no straggler retry and a capped timeout
  (:func:`known_red_timeout`).

Generic on purpose (no fork path), like the runner's core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

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
