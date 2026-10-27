"""The Lens FOLD: what Mission Control paints — open Episodes, latest value per
enabled feed, the watcher's state, and the exit door's newest receipt
(``last_receipt``, stage L2; ``None`` until the first Episode is admitted).

Plan ``eternia-lens-in-hermes.md`` §3 (``snapshot_fold.py``). Read-only and
bounded; it never creates the store (a home with no Lens answers the empty fold).
It carries numbers, typed reasons and identities only — never a source body,
header or credential. A ``missed`` Episode (W8) also carries ``offline``
``{from_ms, until_ms}``: the outage its deadline passed in, read back from the
recorded rows (``missed_deadlines.offline_interval``, the opening block's own
reader), or None when those rows are gone; every other Episode row is unchanged.

Carriage: served on the method lane as ``runtime.lens.fold`` AND as the push
lane snapshot's top-level ``lens`` section (``snapshot.sections``; owner ruling
2026-10-18). The watcher state is this process's memory, so a snapshot built in
the worker carries the SERVE's (:func:`recorded_watcher`), as ``running_work``
rides the request.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .missed_deadlines import offline_interval
from .rules import manifest_rule
from .store import LensStore, LensStoreError, MonitorState
from .store_decisions import open_episodes

__layer__ = "lanes"

MAXIMUM_OPEN_EPISODES = 32
_WATCHER_KEYS = frozenset({"running", "since_ms", "last_tick_ms"})
_RECORDED_WATCHER: ContextVar[dict[str, Any] | None] = ContextVar("lens_recorded_watcher", default=None)


def watcher_state() -> dict[str, Any]:
    """The watcher's state: the serve's when a worker build carries it, else this process's."""

    from .poller import WATCHER

    recorded = _RECORDED_WATCHER.get()
    return dict(recorded) if recorded is not None else WATCHER.to_json()


@contextmanager
def recorded_watcher(state: Any) -> Iterator[None]:
    """Fold with the serve's watcher state (the worker's side); a malformed one = read here."""

    valid = isinstance(state, dict) and set(state) == _WATCHER_KEYS
    token = _RECORDED_WATCHER.set(state if valid else None)
    try:
        yield
    finally:
        _RECORDED_WATCHER.reset(token)


def lens_fold(store: LensStore | None = None) -> dict[str, Any]:
    store = store or LensStore()
    enabled = store.monitors(states=(MonitorState.ENABLED,))
    latest = []
    for row in enabled:
        for feed in row["sealed"]["manifest"]["feeds"] if row["sealed"] else []:
            value = store.latest(row["monitor_id"], feed["id"])
            latest.append(value or {"monitor_id": row["monitor_id"], "feed_id": feed["id"], "sequence": None,
                                    "observed_ms": None, "value": None, "gap": True, "reason": "never_read",
                                    "http_status": None})
    return {
        "version": 1,
        "monitors_enabled": len(enabled),
        # Settled by the operator (``store_decisions``): off the fold, not crowded out by 32 newer ones.
        "open_episodes": [_with_outage(store, row) for row in open_episodes(store, limit=MAXIMUM_OPEN_EPISODES)],
        "latest": latest,
        "last_receipt": next(iter(store.receipts(limit=1)), None),
        "watcher": watcher_state(),
    }


def _with_outage(store: LensStore, row: dict[str, Any]) -> dict[str, Any]:
    """A ``missed`` row with its ``offline`` interval (see the module); any other row as stored."""

    deadline = row.get("missed_deadline_ms")
    if deadline is None:
        return row
    try:
        sealed = store.sealed(row["monitor_id"])
    except LensStoreError:  # an Episode outliving its monitor row still folds, with no outage
        sealed = None
    rule = None if sealed is None else manifest_rule(sealed.manifest(), row["rule_id"])
    interval = None if rule is None else offline_interval(store, row["monitor_id"], rule["feed_id"], deadline)
    return {**row, "offline": None if interval is None else {"from_ms": interval[0], "until_ms": interval[1]}}
