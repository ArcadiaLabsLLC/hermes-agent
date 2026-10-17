"""The Lens FOLD: what Mission Control paints — open Episodes, latest value per
enabled feed, the watcher's state, and the last turn receipt (stage L2; ``None``
until the exit door lands).

Plan ``eternia-lens-in-hermes.md`` §3 (``snapshot_fold.py``). Read-only and
bounded; it never creates the store (a home with no Lens answers the empty fold).
It carries numbers, typed reasons and identities only — never a source body,
header or credential.

Carriage: served on the method lane as ``runtime.lens.fold``. Riding the push
lane's snapshot is a cross-stack fixture change (``tests/fixtures/stream_frames``
are mirrored by the launcher) and moves with the launcher's fold-painter lane.
"""

from __future__ import annotations

from typing import Any

from .episode import EpisodeState
from .store import LensStore, MonitorState

__layer__ = "lanes"

MAXIMUM_OPEN_EPISODES = 32
_OPEN = (EpisodeState.ACTIVE.value, EpisodeState.RECOVERED.value)


def lens_fold(store: LensStore | None = None) -> dict[str, Any]:
    from .poller import WATCHER

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
        "watcher": WATCHER.to_json(),
    }
