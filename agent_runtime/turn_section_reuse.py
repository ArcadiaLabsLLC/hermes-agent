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
_inflight: dict[tuple[str, str], tuple[int, threading.Event]] = {}


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


def begin(root: str, *, position: int | None) -> tuple[str, str] | None:
    """Mark a read of ``root`` at ``position`` in flight; the key for :func:`finish`."""

    store = _store_root()
    if not root or position is None or store is None:
        return None
    key = (store, root)
    with _lock:
        held = _inflight.get(key)
        if held is not None and held[0] >= int(position):
            return None
        _inflight[key] = (int(position), threading.Event())
    return key


def finish(key: tuple[str, str] | None) -> None:
    """End the read ``begin`` marked (remembered or not); wakes its waiters."""

    if key is None:
        return
    with _lock:
        held = _inflight.pop(key, None)
    if held is not None:
        held[1].set()


def await_inflight(root: str, *, floor: int | None, timeout_s: float) -> dict[str, Any] | None:
    """Wait for an in-flight read of ``root`` that covers ``floor``, then consult."""

    store = _store_root()
    if not root or floor is None or store is None:
        return None
    with _lock:
        held = _inflight.get((store, root))
    if held is None or held[0] < int(floor):
        return None
    held[1].wait(max(0.0, float(timeout_s)))
    return consult(root, floor=floor)


def clear() -> None:
    """Drop every held root (tests, and a store switch)."""

    with _lock:
        _entries.clear()
        waiting = list(_inflight.values())
        _inflight.clear()
    for _position, event in waiting:
        event.set()
