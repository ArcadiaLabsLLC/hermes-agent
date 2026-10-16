"""Group Chat host-declared Discussion limits — fork-owned, beside ``gateway/hosted_room_discussion.py``.

``DiscussionLimits``, ``DEFAULT_LIMITS``, the scheduled-conclusion turn ``_conclude`` and
``task_round_index`` moved here unchanged from the upstream ``gateway/hosted_room_discussion.py``
(footprint audit 2026-10-15, lane G). That module imports them back by name with one line, so
``hosted_room_discussion.DiscussionLimits`` and every ``limits=`` default keep their identity; the
``limits=`` threading, the ``response_from_payload`` uses and the ``ready_tasks`` batch stay
upstream-side (doors J2/J3 of ``docs/agent-runtime-harness/planned/upstream-doors-2026-10-06.md``,
issue #125258).

This module is entered THROUGH ``gateway.hosted_room_discussion``: its seam line sits after the
constants and error classes this module reads at import time, and every other policy name
(``_identifier``, ``_thread_messages``, ``_build_prompt``, ...) is read through the module at
CALL time. Those private reaches are import-layers exceptions
(``tests/fixtures/import_layers_grandfathered.json``) waiting on the same door.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from gateway import hosted_room_discussion as _discussion
from gateway import hosted_room_driver as driver
from gateway import hosted_rooms
from gateway.hosted_room_message_intent import response_from_payload


@dataclass(frozen=True)
class DiscussionLimits:
    """Host-declared immutable policy, never inferred from a mutable global.

    The default preserves Bot Mode's six-profile policy. An instance-aware host
    may retain a larger historical member catalog, limit its active set separately,
    and bound prompts to the native transport's smaller input envelope.
    """
    max_members: int = _discussion.MAX_DISCUSSION_MEMBERS
    max_rounds: int = _discussion.MAX_DISCUSSION_ROUNDS
    max_messages: int = _discussion.MAX_DISCUSSION_MESSAGES
    prompt_bytes: int = driver.MAX_PROMPT_BYTES
    shared_profiles: bool = False
    guidance: str = ""
    conclusion_member_id: str | None = None

    @property
    def last_round_index(self) -> int:
        return self.max_rounds if self.conclusion_member_id is not None else self.max_rounds - 1

    def __post_init__(self) -> None:
        for name, low, high in (("max_members", 2, hosted_rooms.MAX_MEMBERS),
                                ("max_rounds", 1, _discussion.MAX_DISCUSSION_ROUNDS),
                                ("max_messages", 1, 384),
                                ("prompt_bytes", 2048, driver.MAX_PROMPT_BYTES)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise _discussion.DiscussionValidationError(f"invalid Discussion limit: {name}")
        if type(self.shared_profiles) is not bool:
            raise _discussion.DiscussionValidationError("shared_profiles must be a boolean")
        if not isinstance(self.guidance, str) or len(self.guidance.encode("utf-8")) > 1000:
            raise _discussion.DiscussionValidationError("invalid Discussion guidance")
        if self.conclusion_member_id is not None:
            _discussion._identifier(self.conclusion_member_id, label="conclusion_member_id")


DEFAULT_LIMITS = DiscussionLimits()


def _conclude(room, events, discussion, active, decision) -> _discussion.DiscussionDecision:
    """One optional ordinary driver turn; the same journal owns Stop and replay."""
    response = response_from_payload(discussion.payload)
    if response is not None and response.single_round:
        return decision
    member_id = room.limits.conclusion_member_id
    if member_id is None:
        return decision
    decide = partial(_discussion.DiscussionDecision, discussion_event_id=discussion.event_id,
        source_event_seq=discussion.seq, thread_id=discussion.payload["thread_id"])
    terminal = next((e for e in reversed(events) if e.kind in _discussion._TERMINAL_EVENT_KINDS
        and e.payload.get("discussion_event_id") == discussion.event_id
        and e.payload["round_index"] == room.limits.max_rounds), None)
    if terminal is not None:
        reason = {"turn.settled": "conclusion_completed", "turn.failed": "conclusion_failed",
                  "turn.cancelled": "conclusion_cancelled", "turn.deferred": "conclusion_deferred"}[terminal.kind]
        if terminal.kind == "turn.settled" and terminal.payload["passed"]:
            reason = "conclusion_empty"
        return decide("settled", reason)
    member = next((m for m in active if m.member_id == member_id), None)
    if member is None:
        return decide("settled", "conclusion_member_unavailable")
    _, messages, _ = _discussion._thread_messages(events, discussion)
    seen = max(e.seq for e in messages)
    prompt = _discussion._build_prompt(room=room, member=member, messages=messages, watermark=0,
        seen_through_seq=seen, active_members=active, conclusion=True)
    return decide("task", "conclusion_turn", task=_discussion._make_task_plan(room=room,
        discussion_event=discussion, member=member, member_index=0,
        round_index=room.limits.max_rounds, seen_through_seq=seen, prompt=prompt))


def task_round_index(identity: driver.TaskIdentity, *, limits: DiscussionLimits = DEFAULT_LIMITS) -> int:
    """Read a durable task coordinate, including after the room has ended."""
    match = _discussion._TURN_ID_RE.fullmatch(identity.turn_id)
    if match is None:
        raise _discussion.DiscussionReconstructionError("turn_id is not a Discussion coordinate")
    return _discussion._zero_based_int(int(match.group("round")), label="round_index", maximum=limits.last_round_index)
