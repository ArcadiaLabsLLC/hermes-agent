"""One chat root's ``persona_chat_turn`` sections, read by the core's own builders.

The read half of the stream's turn overlay (:func:`agent_runtime.stream.frames.persona_chat_turn_frames`),
kept free of the stream package so the resident snapshot worker
(:mod:`agent_runtime.snapshot_worker`) can run it off the serve's interpreter. It
takes no batch: the serve names the instance(s) the batch's events point at
(:func:`named_instance_ids`) and how many rows the history bound may have
dropped (``evict``), and the worker answers with the sections.

What it does NOT read, because only the serve holds it: ``running_work`` (its
live lanes read the serve's in-memory registries; the serve adds it after the
read) and the chat runtime registry (the serve's observations ride the worker
request, :func:`agent_runtime.persona_chat_continuity.runtime_registry.recorded_runtime_registry`).
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Sequence

from .events import EventLog
from .models import Event
from .serde import optional_text, to_jsonable

__layer__ = "lanes"

#: The events whose ``persona_instance_id`` names the instance a root belongs to:
#: the turn's publishes and a new chat's ``chat_opened``.
_INSTANCE_NAMING_EVENT_TYPES = frozenset(
    {
        "persona_chat.turn_started",
        "persona_chat.turn_ended",
        "persona_chat.projected",
        "persona_instance.chat_opened",
    }
)


def _event_root(event: Event) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if getattr(event, "type", None) == "persona_instance.chat_opened":
        return optional_text(payload.get("session_id"))
    return optional_text(payload.get("root_chat_session_id"))


def named_instance_ids(root: str, batch: Iterable[tuple[int, Event]]) -> tuple[str, ...]:
    """The instance ids ``batch``'s publishes for ``root`` name, in batch order."""

    named: list[str] = []
    for _offset, event in batch:
        if getattr(event, "type", None) not in _INSTANCE_NAMING_EVENT_TYPES or _event_root(event) != root:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        instance_id = optional_text(payload.get("persona_instance_id"))
        if instance_id and instance_id not in named:
            named.append(instance_id)
    return tuple(named)


def turn_instance(root: str, named: Sequence[str], instances: list[Any]) -> Any | None:
    """The persona instance whose chat ``root`` is: the batch names it, else the
    instance bound to the session, else the mint's owner."""

    from .persona_assignments import chat_session_owner_instance_id

    by_id = {str(getattr(item, "id", "") or ""): item for item in instances}
    for instance_id in named:
        if instance_id in by_id:
            return by_id[instance_id]
    for instance in instances:
        if root in (
            optional_text(getattr(instance, "default_chat_session_id", None)),
            optional_text(getattr(instance, "session_id", None)),
        ):
            return instance
    return by_id.get(chat_session_owner_instance_id(root) or "")


def channel_for_instance(channels: list[dict[str, Any]], instance_id: str) -> dict[str, Any] | None:
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if channel.get("persona_instance_id") == instance_id or instance_id in (
            channel.get("source_instance_ids") or ()
        ):
            return channel
    return None


def read_turn_sections(
    root: str, *, named: Sequence[str] = (), evict: int = 0
) -> tuple[dict[str, Any], dict[str, int]]:
    """One root's turn sections (no ``running_work``), read NOW, and the read's timings.

    The FULL instance list goes in everywhere attribution or ranking needs it —
    the history bound ranks every candidate exactly as the core does and only
    then narrows to the root (``only_session_ids``, plan h-turn1 §2 C0.3), and
    the channel join takes every instance so display names and relationships are
    the core's — so each row equals the row a full core built now would carry.
    The roster is ``list_all`` (a read), never ``ensure_for_personas`` (it
    writes). Raises when any read fails; the caller demotes.

    ``evicted_roots`` (present only when non-empty) is the first ``evict`` roots
    the bound omits, in its own rank order: a batch naming ``evict`` roots can
    have pushed at most that many rows out of the bound, and those are the
    top-ranked omitted ones. Every id in it is omitted by a full core built now,
    so a client removing them can only converge on that core.
    """

    from .config import ensure_persisted_personas
    from .operator_channels import operator_channel_summary
    from .persona_assignments import PersonaInstanceStore, persona_instance_summary
    from .persona_chat_history import persona_chat_history_summary, persona_chat_trace_summary
    from .persona_chat_history.vocabulary import DEFAULT_PERSONA_CHAT_MESSAGE_TAIL
    from .persona_lifecycle import is_runtime_persona
    from .resolution import runtime_resolution_scope
    from .snapshot.details import persona_session_db_scope
    from .snapshot.receipts import _persona_chat_history_frame
    from .snapshot_turn_yield import snapshot_yield_point
    from .store import AgentStore

    timings: dict[str, int] = {}
    snapshot_yield_point()
    with runtime_resolution_scope(), persona_session_db_scope() as session_db:
        event_log = EventLog()
        instances = PersonaInstanceStore(event_log=event_log).list_all()
        instance = turn_instance(root, named, instances)
        if instance is None:
            raise LookupError(f"no persona instance owns chat root {root!r}")
        started = time.perf_counter()
        omitted: set[str] = set()
        omitted_ranked: list[str] = []
        history = persona_chat_history_summary(
            persona_instances=instances,
            session_db=session_db,
            message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
            omitted_session_ids=omitted,
            omitted_ranked=omitted_ranked,
            only_session_ids=frozenset({root}),
        )
        timings["history_ms"] = int((time.perf_counter() - started) * 1000)
        snapshot_yield_point()
        started = time.perf_counter()
        trace = persona_chat_trace_summary(
            persona_instances=[instance],
            event_log=event_log,
            message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
        )
        timings["trace_ms"] = int((time.perf_counter() - started) * 1000)
        snapshot_yield_point()
        channels = operator_channel_summary(
            persona_instances=instances,
            persona_chat_history=history,
            persona_chat_trace=trace,
            intentionally_omitted_history_session_ids=omitted,
        )
    channel = channel_for_instance(channels, str(instance.id))
    if channel is None:
        raise LookupError(f"no operator channel for {instance.id!r}")
    personas = {
        str(getattr(agent, "id", "") or ""): agent
        for agent in AgentStore().list_all()
        if is_runtime_persona(agent)
    }
    history_rows = _persona_chat_history_frame(history)
    snapshot_yield_point()
    sections: dict[str, Any] = {
        "persona_instance_id": str(instance.id),
        "persona_chat_history": to_jsonable(history_rows[0]) if history_rows else None,
        "operator_channel": to_jsonable(channel),
        "persona_instance": to_jsonable(
            persona_instance_summary(
                instance,
                personas.get(str(getattr(instance, "persona_id", "") or "")),
                roster=ensure_persisted_personas,
            )
        ),
        "omitted": root in omitted,
    }
    evicted = [session_id for session_id in omitted_ranked[: max(0, int(evict))] if session_id != root]
    if evicted:
        sections["evicted_roots"] = evicted
    return sections, timings
