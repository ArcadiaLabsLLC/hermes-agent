"""Automatic maintenance may claim idle, never turn active work into a drain."""
from __future__ import annotations

from typing import Any

__layer__ = "lanes"


def claim_idle_drain(session: Any) -> str | None:
    """Called under the serve admission lock; the native owner fences its own."""
    if any(not item.is_runtime_stream for item in session.inflight.values()):
        return "busy"
    try:
        discussion = session.discussion_owner
        if discussion is not None and discussion.pending_count():
            return "busy"
        owner = session.conversation_owner
        if owner is not None and not owner.begin_idle_drain():
            return "busy"
    except Exception:
        return "unavailable"
    return None


def native_pending_count(owner: Any) -> int:
    if owner is None:
        return 0
    try:
        return owner.pending_count()
    except Exception:
        return 1  # Unreadable ownership cannot prove idle.
