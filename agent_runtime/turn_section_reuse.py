"""One chat root's ``persona_chat_turn`` sections, reused by the next subscriber.

The serve runs two ``StreamSession``s per attached launcher (the hub lane and
the argv lane's ``harness stream``) in one process, draining the same events.
Each flushes the same turn batch and, without this memo, each reads the same
root's sections — ~0.9 s cold (plan h-turn1 §2 C0.2). The second lane's batch
closes LATER than the first's (its settle starts later), so this is
``demote_core_reuse``'s situation with a section in place of a core, and the
same POSITION rule makes the reuse safe:

* ``remember(root, sections, position=…)`` holds the sections keyed on the log
  position captured BEFORE they were read — a lower bound on what they carry.
  A post-read stat would absorb an append that landed during the read and later
  serve sections the events do not appear in (MCF-Q1's shape).
* ``consult(root, floor=…)`` hands them back only when that position is at or
  past ``floor``, the offset the reusing frame is about to be stamped with:
  every event the frame claims is then in what was read. Below it → ``None``
  and the caller reads afresh.

It is a reuse of the SECTIONS, never of a frame: each caller stamps its own
``base_offset`` / ``watermark`` on its own copy. An unknown position on either
side refuses, the expensive direction, deliberately.

**In flight (lane h-demote-census, 2026-10-06).** The read now stands aside for
a live turn's hot windows (``snapshot_turn_yield``), so it can take seconds, and
the second lane's batch used to arrive mid-read, miss the memo and read the same
root again. ``begin`` / ``finish`` bracket a read, and ``await_inflight`` lets
that lane wait for a read whose position already covers its floor — the same
position rule, applied before the read finishes instead of after.

**Claimed before it reads (lane h-overlay-worker, 2026-10-06).** Live 01:25 test:
every START section was read by BOTH lanes, each 2.4-3.6 s late, because the
first lane captured its position BEFORE standing aside and the second lane's
batch -- closing during that wait -- had a floor past it. A read is now claimed
with ``begin(root)`` (no position: "standing aside, not reading yet") and its
position recorded by :func:`started` when the read really begins. A lane that
finds a claim still standing aside waits for it (its position will be taken
after the second lane's batch closed); a claim already reading below the floor
is not waited for, as before.

**One claim per floor (lane h-section-dup, 2026-10-06).** A root held ONE claim,
so a lane whose floor the claim did not cover was refused one and read
UNCLAIMED; a third lane at that floor found only the low claim and read the same
section again (the turn-cost guard: two reads at offset 9240 with three readers).
Claims now sit side by side per root: a refused lane waits for the claim that
covers its floor, and a lane no claim covers takes its own.
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from .demote_core_reuse import _store_root  # one owner: the held core and the held sections are about the same store

__layer__ = "stores"

SOURCE_BUILT = "built"
SOURCE_REUSED = "reused"

#: A few roots at most are mid-turn at once; the bound only stops a long-lived
#: serve from holding every root it ever answered.
_MAX_ROOTS = 32

_lock = threading.Lock()
_entries: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
#: key -> every claim of that root still in flight (h-section-dup: one per floor, not one per root)
_inflight: dict[tuple[str, str], list["_Claim"]] = {}


class _Claim:
    """One claimed read: its position (``None`` while still standing aside) and its done event."""

    __slots__ = ("key", "position", "done")

    def __init__(self, key: tuple[str, str], position: int | None) -> None:
        self.key = key
        self.position = position
        self.done = threading.Event()

    def covers(self, floor: int | None) -> bool:
        """A frame stamped at ``floor`` may take this read's sections: it has no position
        yet (it will be taken after ``floor``'s batch closed) or reads at or past it."""

        return self.position is None or (floor is not None and self.position >= int(floor))


def _covering(key: tuple[str, str], floor: int | None) -> "_Claim | None":
    return next((claim for claim in _inflight.get(key, ()) if claim.covers(floor)), None)


def remember(root: str, sections: dict[str, Any], *, position: int | None) -> bool:
    """Hold ``sections`` for ``root`` at ``position``; ``False`` when nothing was held."""

    store = _store_root()
    if not root or position is None or store is None or not isinstance(sections, dict):
        return False
    held = copy.deepcopy(sections)
    with _lock:
        existing = _entries.get((store, root))
        if existing is not None and existing[0] > int(position):
            # A slower read finishing late never replaces a fresher one.
            return False
        _entries[(store, root)] = (int(position), held)
        while len(_entries) > _MAX_ROOTS:
            _entries.pop(next(iter(_entries)))
    return True


def consult(root: str, *, floor: int | None) -> dict[str, Any] | None:
    """A copy of ``root``'s held sections if they were read at or past ``floor``."""

    store = _store_root()
    if not root or floor is None or store is None:
        return None
    with _lock:
        entry = _entries.get((store, root))
    if entry is None:
        return None
    position, sections = entry
    if position < int(floor):
        return None
    return copy.deepcopy(sections)


def begin(root: str, *, position: int | None = None, floor: int | None = None) -> _Claim | None:
    """Claim a read of ``root``; the handle for :func:`started` / :func:`finish`.

    ``position=None`` claims it before the read has a position (it may still
    stand aside); :func:`started` records the position when it reads. ``None``
    back means a claim already in flight covers ``floor`` (or ``position``) --
    :func:`await_inflight` it. A claim that does NOT cover it is no bar: the
    new read is claimed BESIDE it, so a third lane at the same floor waits for
    this read instead of starting its own (h-section-dup: the refused lane used
    to read unclaimed, and the next lane at its floor read the same section again).
    """

    store = _store_root()
    if not root or store is None:
        return None
    key = (store, root)
    wanted = position if position is not None else floor
    with _lock:
        if _covering(key, wanted) is not None:
            return None
        claim = _Claim(key, None if position is None else int(position))
        _inflight.setdefault(key, []).append(claim)
    return claim


def started(claim: _Claim | None, position: int | None) -> None:
    """The claimed read begins at ``position`` (captured just before it reads)."""

    if claim is None or position is None:
        return
    with _lock:
        claim.position = int(position)


def finish(claim: _Claim | None) -> None:
    """End the read ``begin`` marked (remembered or not); wakes its waiters."""

    if claim is None:
        return
    with _lock:
        claims = _inflight.get(claim.key)
        if claims is not None and claim in claims:
            claims.remove(claim)
            if not claims:
                _inflight.pop(claim.key, None)
    claim.done.set()


def await_inflight(root: str, *, floor: int | None, timeout_s: float) -> dict[str, Any] | None:
    """Wait for an in-flight read of ``root`` that covers ``floor`` -- or that has
    not taken its position yet -- then consult. With none in flight, consult now:
    a covering read may have finished between the caller's miss and this look."""

    store = _store_root()
    if not root or floor is None or store is None:
        return None
    with _lock:
        claim = _covering((store, root), floor)
    if claim is not None:
        claim.done.wait(max(0.0, float(timeout_s)))
    return consult(root, floor=floor)


def clear() -> None:
    """Drop every held root (tests, and a store switch)."""

    with _lock:
        _entries.clear()
        waiting = [claim for claims in _inflight.values() for claim in claims]
        _inflight.clear()
    for claim in waiting:
        claim.done.set()
