"""Automatic maintenance may claim idle, never turn active work into a drain."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from agent_runtime.discussions.run_store import DiscussionError

__layer__ = "lanes"


def claim_idle_drain(session: Any) -> str | None:
    """Called under the serve admission lock; the native owner fences its own."""
    if any(not item.is_runtime_stream for item in session.inflight.values()):
        return "busy"
    try:
        discussion = session.discussion_owner
        # Lock order: serve admission -> discussions -> conversations.
        # An exception leaves discussion admission open when another owner refuses.
        with discussion.idle_drain() if discussion is not None else nullcontext():
            owner = session.conversation_owner
            if owner is not None and not owner.begin_idle_drain():
                raise DiscussionError("busy")
    except DiscussionError as exc:
        return "busy" if exc.reason == "busy" else "unavailable"
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
