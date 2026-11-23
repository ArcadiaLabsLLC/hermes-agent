"""A steer folded into the resident core together with the channel threads it moves.

A ``persona_instance`` patch row carries only the instance's own row, so after a
steer (``set_parents``) a fold client — Eternia, and the resident core that holds
exactly what it holds — kept every channel's ``conversation.root_thread_id`` /
``parent_thread_id`` as they were until the next full core (row
RT-FU-A-STEER-OR-SCOPE-PATCH-LEAVES-CHANNEL-THREADS-AND-PROMPT-VIEW-STALE-UNTIL-THE-NEXT-FULL-CORE).
For such a batch the hub folds the patch into the resident core, re-derives the
threads from that core's own channels and instance rows (the build's one ancestry
walk, ``operator_channels.instances.thread_relationships``) and ships the result
as the batch's ``delta``: no store read, no build. With no resident core held at
the batch's base, the patch ships as before.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..models import Event
from ..operator_channels.instances import core_thread_relationships
from ..state_patches.models import STATE_PATCHED_EVENT_TYPE
from .holder import _fold, _frame_offset, _stamped, resident_core_enabled, root_held

__layer__ = "lanes"

__all__ = ["batch_moves_thread_ancestry", "steered_core", "with_rederived_threads"]

#: The instance fields a channel's thread ancestry is derived from.
_ANCESTRY_FIELDS = frozenset({"steered_by", "spawned_by"})


def batch_moves_thread_ancestry(batch: Iterable[tuple[int, Event]]) -> bool:
    """Whether a batch carries a ``persona_instance`` patch that moves its steering parents."""

    for _offset, event in batch:
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        changed = payload.get("changed")
        if (
            getattr(event, "type", None) == STATE_PATCHED_EVENT_TYPE
            and payload.get("entity") == "persona_instance"
            and isinstance(changed, dict)
            and _ANCESTRY_FIELDS & set(changed)
        ):
            return True
    return False


def with_rederived_threads(core: dict[str, Any]) -> dict[str, Any]:
    """``core`` with every channel conversation's thread ids re-derived; copy-on-write."""

    channels = core.get("operator_channels")
    if not isinstance(channels, dict):
        return core
    moved = dict(channels)
    for channel_id, (root_thread_id, parent_thread_id) in core_thread_relationships(core).items():
        row = channels.get(channel_id)
        conversation = row.get("conversation") if isinstance(row, dict) else None
        if not isinstance(conversation, dict):
            continue
        if (conversation.get("root_thread_id"), conversation.get("parent_thread_id")) == (root_thread_id, parent_thread_id):
            continue
        moved[channel_id] = {
            **row,
            "conversation": {**conversation, "root_thread_id": root_thread_id, "parent_thread_id": parent_thread_id},
        }
    return {**core, "operator_channels": moved}


def steered_core(patch_frame: dict[str, Any]) -> dict[str, Any] | None:
    """The resident core after ``patch_frame`` with its threads re-derived, or ``None``."""

    if not resident_core_enabled():
        return None
    held = root_held()
    offset = _frame_offset(patch_frame)
    if held is None or held.stale or offset is None or patch_frame.get("base_offset") != held.offset:
        return None
    folded, hazard = _fold(held, patch_frame)
    if folded is None or hazard is not None:
        return None
    return _stamped(with_rederived_threads(folded), patch_frame, offset)
