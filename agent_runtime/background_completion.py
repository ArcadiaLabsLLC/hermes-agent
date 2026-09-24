"""Background-process completion policy the eternia-harness plugin applies at spawn.

Owner ruling 2026-09-24: completion is decided ONCE, at spawn, and is ON by default.
Upstream's ``terminal(background=true, notify=...)`` parameter is the door; this module
only supplies the default. A spawn that says anything about notification itself —
``notify`` (bool or pattern list), the legacy ``notify_on_complete`` or
``watch_patterns`` — keeps what it said, so ``notify=false`` is the per-spawn opt-out.
Delivery (drop when the chat root has no live owner; steer into a busy turn) is the
serve drain's job, in :mod:`agent_runtime.dispatch_delivery`.
"""

from __future__ import annotations

from typing import Any

#: Arguments through which a spawn has already decided its own notification.
_EXPLICIT_NOTIFY_KEYS = ("notify", "notify_on_complete", "watch_patterns")


def default_background_notify(tool_name: str, args: Any) -> dict | None:
    """The ``terminal`` args with ``notify=True`` defaulted in, or None when unchanged."""

    if tool_name != "terminal" or not isinstance(args, dict):
        return None
    if not args.get("background"):
        return None
    if any(key in args for key in _EXPLICIT_NOTIFY_KEYS):
        return None
    return {**args, "notify": True}
