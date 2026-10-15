"""Automatic maintenance may claim idle, never turn active work into a drain.

**What holds an idle drain is a TURN, not a request.** A chat turn, a long
run, a native conversation turn and a discussion round each refuse the claim;
a read, a status call, a prewarm or the very request whose arrival made the
launcher attach do not. Those finish inside the drain — it closes admission
and waits for every in-flight request before the process exits — so refusing
them only deferred a stale-code restart by the launcher's whole recheck
interval (2026-10-08: attach at 04:25:14, drain at 04:26:05). The refusal
names WHICH hold answered, so the launcher reads the reason and never guesses
at idleness from a ``work`` count.
"""
from __future__ import annotations

from contextlib import nullcontext
from enum import Enum
from typing import Any

from agent_runtime.discussions.run_store import DiscussionError

__layer__ = "lanes"


class IdleDrainHold(str, Enum):
    """Why an idle-drain claim was refused — the ``held_by`` of the refusal."""

    CHAT_TURN = "chat_turn"
    LONG_RUN = "long_run"
    CONVERSATION_TURN = "conversation_turn"
    DISCUSSION = "discussion"
    UNREADABLE = "unreadable"

    @property
    def reason(self) -> str:
        """The refusal's ``reason`` word, unchanged for older clients."""
        return "unavailable" if self is IdleDrainHold.UNREADABLE else "busy"


class _ConversationBusy(Exception):
    """Raised inside the discussion fence so it reopens admission on the way out."""


def claim_idle_drain(session: Any) -> IdleDrainHold | None:
    """Called under the serve admission lock; the native owner fences its own."""
    items = list(session.inflight.values())
    if any(getattr(item, "is_chat_turn", False) for item in items):
        return IdleDrainHold.CHAT_TURN
    if any(getattr(item, "is_long_run", False) for item in items):
        return IdleDrainHold.LONG_RUN
    try:
        discussion = session.discussion_owner
        # Lock order: serve admission -> discussions -> conversations.
        # An exception leaves discussion admission open when another owner refuses.
        with discussion.idle_drain() if discussion is not None else nullcontext():
            owner = session.conversation_owner
            if owner is not None and not owner.begin_idle_drain():
                raise _ConversationBusy
    except _ConversationBusy:
        return IdleDrainHold.CONVERSATION_TURN
    except DiscussionError as exc:
        return IdleDrainHold.DISCUSSION if exc.reason == "busy" else IdleDrainHold.UNREADABLE
    except Exception:
        return IdleDrainHold.UNREADABLE
    return None


def native_pending_count(owner: Any) -> int:
    if owner is None:
        return 0
    try:
        return owner.pending_count()
    except Exception:
        return 1  # Unreadable ownership cannot prove idle.
