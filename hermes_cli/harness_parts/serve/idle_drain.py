"""Automatic maintenance may claim idle, never turn active work into a drain.

**What holds an idle drain is a TURN, not a request.** A chat turn, a long
run, a native conversation turn and a discussion round each refuse the claim;
a read, a status call, a prewarm or the very request whose arrival made the
launcher attach do not. Those finish inside the drain — it closes admission
and waits for every in-flight request before the process exits — so refusing
them only deferred a stale-code restart by the launcher's whole recheck
interval (2026-10-08: attach at 04:25:14, drain at 04:26:05). A cron job
running in this process holds it too: it runs on the scheduler's own pool,
outside every turn table, so only ``cron.scheduler.get_running_job_ids()``
sees it (upstream's gateway drain reads the same set); a fire of the serve's own
scheduler still on its root's send queue holds it the same way (``scheduled_turn``), and so does a
platform message the messaging bridge queued (``messaging_turn``). The refusal
names WHICH hold answered, so the launcher reads the reason and never guesses
at idleness from a ``work`` count.
"""
from __future__ import annotations

import sys
from contextlib import nullcontext
from enum import Enum
from typing import Any

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.discussions.run_store import DiscussionError

__layer__ = "lanes"


class IdleDrainHold(str, Enum):
    """Why an idle-drain claim was refused — the ``held_by`` of the refusal."""

    CHAT_TURN = "chat_turn"
    LONG_RUN = "long_run"
    CONVERSATION_TURN = "conversation_turn"
    DISCUSSION = "discussion"
    CRON_JOB = "cron_job"
    SCHEDULED_TURN = "scheduled_turn"
    MESSAGING_TURN = "messaging_turn"
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
    cron_hold = _cron_job_hold() or _queued_turn_hold()
    if cron_hold is not None:
        return cron_hold
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


def _cron_job_hold() -> IdleDrainHold | None:
    """A cron run in THIS process (a manual ``cronjob_manage run`` on its background pool, or an
    in-process ticker) holds the drain. Never imports the scheduler: unloaded, no run can exist."""
    scheduler = sys.modules.get("cron.scheduler")
    if scheduler is None:
        return None
    try:
        running = scheduler.get_running_job_ids()
    except Exception:
        return IdleDrainHold.UNREADABLE
    return IdleDrainHold.CRON_JOB if running else None


def native_pending_count(owner: Any) -> int:
    if owner is None:
        return 0
    try:
        return owner.pending_count()
    except Exception:
        return 1  # Unreadable ownership cannot prove idle.


def _queued_turn_hold() -> IdleDrainHold | None:
    """A send-queue entry (queued or running) whose origin names a row of :data:`_QUEUED_TURN_HOLDS` holds the
    drain: the queued-send runner runs it outside every turn table (``running_work`` kinds ``scheduled_turn``,
    ``messaging_turn``). Read in table order; the first origin with an entry answers."""
    for origin_key, hold in _QUEUED_TURN_HOLDS.items():
        try:
            waiting = send_queue.entries_from(origin_key)
        except OSError:
            return IdleDrainHold.UNREADABLE
        if waiting:
            return hold
    return None


#: send-queue origin key -> the hold an entry carrying it is.
_QUEUED_TURN_HOLDS: dict[str, IdleDrainHold] = {
    send_queue.SCHEDULE_ORIGIN_KEY: IdleDrainHold.SCHEDULED_TURN,
    send_queue.MESSAGING_ORIGIN_KEY: IdleDrainHold.MESSAGING_TURN,
}
