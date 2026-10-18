"""The Lens FOLD: what Mission Control paints — open Episodes, latest value per
enabled feed, the watcher's state, and the last turn receipt (stage L2; ``None``
until the exit door lands).

Plan ``eternia-lens-in-hermes.md`` §3 (``snapshot_fold.py``). Read-only and
bounded; it never creates the store (a home with no Lens answers the empty fold).
It carries numbers, typed reasons and identities only — never a source body,
header or credential.

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

from .episode import EpisodeState
from .store import LensStore, MonitorState

__layer__ = "lanes"

MAXIMUM_OPEN_EPISODES = 32
_OPEN = (EpisodeState.ACTIVE.value, EpisodeState.RECOVERED.value)
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
        "open_episodes": store.episodes(states=_OPEN, limit=MAXIMUM_OPEN_EPISODES),
        "latest": latest,
        "last_receipt": None,
        "watcher": watcher_state(),
    }
