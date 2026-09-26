"""``persona_chat_trace_summary``: the bounded tail of a persona's tool trace events.

Separate because it reads its own store (the event log), not SessionDB.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..models import PersonaInstance
from ..projection_accountant import ProjectionAccountant
from ..persona_assignments import (
    persona_instance_id_for,
    safe_assignment_text,
    safe_assignment_token,
)
from .vocabulary import canonical_chat_persona_id
from .trace_rows import _bounded_message_tail, _trace_entry, _trace_fetch_limit
from .vocabulary import DEFAULT_PERSONA_CHAT_MESSAGE_TAIL, _TRACE_EVENT_TYPES

__layer__ = "stores"
__all__ = [
    "persona_chat_trace_summary",
]


def persona_chat_trace_summary(
    *,
    persona_instances: Iterable[PersonaInstance],
    event_log: Any | None = None,
    message_tail: int = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    accountant: "ProjectionAccountant | None" = None,
) -> list[dict[str, Any]]:
    """Return redaction-safe tool/progress trace rows for persona chats.

    This is an additive snapshot projection of already-persisted EventLog rows.
    The curated persona chat history intentionally keeps dropping tool/system
    noise; trace rows live in this separate channel and are merged client-side.

    Two disjoint lanes feed a persona instance's trace, merged chronologically:

    * **historical task-run trace** — persisted events from the retired task lane,
      keyed on ``task_id`` (``session_id`` is ``None``). Grouped per task so each
      task's event log is scanned once and the fetch window can be sized for
      *all* its agents at once — a flat per-persona window let a busy
      multi-agent task starve a quiet persona's trace out of the window.
    * **chat-turn trace** — tool calls an operator chat turn makes via
      ``ChatProgressSink``, keyed on ``session_id`` (``task_id`` is ``None``).
      Surfaced for *any* instance with a bound session, regardless of mode, so a
      conversational tool call shows in the operator channel's Trace lane even
      when no task is attached.

    The lanes never overlap (task events carry no ``session_id``; chat events
    carry no ``task_id``), so merging is a plain union with no double counting.
    """

    # No event log, no trace lane to project — an honest empty page. This read
    # `event_log or _default_event_log()`, naming a helper that has never
    # existed in this module: any caller that omitted the argument got a
    # NameError instead of the empty list two lines below. It never fired only
    # because both production callers (snapshot.build_snapshot,
    # status.build_status) resolve their own CachedEventLog first. Found by the
    # F821 gate.
    log = event_log
    if log is None:
        return []
    tail = _bounded_message_tail(message_tail)

    instances = list(persona_instances)
    # Preserve instance order for stable row output while accumulating each
    # instance's events from both lanes before rendering.
    accumulators: "dict[str, _TraceAccumulator]" = {}
    order: list[str] = []

    def _accumulator(instance: Any, persona_id: str) -> "_TraceAccumulator":
        instance_id = safe_assignment_text(
            getattr(instance, "id", None) or persona_instance_id_for(persona_id),
            limit=160,
        )
        acc = accumulators.get(instance_id)
        if acc is None:
            acc = _TraceAccumulator(
                instance_id=instance_id,
                persona_id=persona_id,
                task_id=safe_assignment_text(getattr(instance, "current_task_id", None), limit=160),
                session_id=safe_assignment_text(getattr(instance, "session_id", None), limit=200),
            )
            accumulators[instance_id] = acc
            order.append(instance_id)
        return acc

    # --- Lane 1: task-run trace, grouped per task. ---
    # Persona identity is canonicalized the same way the chat-history projection
    # does (``canonical_chat_persona_id``), NOT via ``safe_assignment_token``: the
    # latter mangles ids like "profile:alice" → "profile_alice", which never
    # matches the raw "profile:alice" stored on the events, silently dropping
    # every profile-instance trace row. Canonicalizing both sides also keeps the
    # row's ids identical to the history row so the Launcher matches them.
    members_by_task: dict[str, list[tuple[Any, str]]] = {}
    for instance in instances:
        mode = safe_assignment_token(getattr(instance, "mode", None))
        if mode != "task_bound":
            continue
        task_id = safe_assignment_text(getattr(instance, "current_task_id", None), limit=160)
        persona_id = canonical_chat_persona_id(getattr(instance, "persona_id", None))
        if not task_id or not persona_id:
            continue
        members_by_task.setdefault(task_id, []).append((instance, persona_id))

    for task_id, members in members_by_task.items():
        fetch_limit = _trace_fetch_limit(tail, len(members))
        trace_by_persona: dict[str, list[Any]] = {}
        for event in _fetch_trace_events(log.for_task, task_id, limit=fetch_limit):
            if getattr(event, "type", None) not in _TRACE_EVENT_TYPES:
                continue
            event_persona = canonical_chat_persona_id(getattr(event, "persona_id", None))
            if event_persona:
                trace_by_persona.setdefault(event_persona, []).append(event)
        for instance, persona_id in members:
            _accumulator(instance, persona_id).extend(trace_by_persona.get(persona_id, []))

    # --- Lane 2: conversational chat-turn trace, keyed on the bound session. ---
    for instance in instances:
        session_id = safe_assignment_text(getattr(instance, "session_id", None), limit=200)
        persona_id = canonical_chat_persona_id(getattr(instance, "persona_id", None))
        if not session_id or not persona_id:
            continue
        if not _supports_for_session(log):
            break
        fetch_limit = _trace_fetch_limit(tail, 1)
        chat_events: list[Any] = []
        for event in _fetch_trace_events(log.for_session, session_id, limit=fetch_limit):
            if getattr(event, "type", None) not in _TRACE_EVENT_TYPES:
                continue
            event_persona = canonical_chat_persona_id(getattr(event, "persona_id", None))
            if event_persona and event_persona != persona_id:
                if accountant is not None:
                    accountant.consider(1)
                    accountant.drop("persona_mismatch", entity_id=session_id, detail=event_persona)
                continue
            chat_events.append(event)
        _accumulator(instance, persona_id).extend(chat_events)

    rows: list[dict[str, Any]] = []
    for instance_id in order:
        acc = accumulators[instance_id]
        entries = acc.entries(tail=tail, accountant=accountant)
        if not entries:
            continue
        row: dict[str, Any] = {
            "persona_instance_id": acc.instance_id,
            "persona_id": acc.persona_id,
            "task_id": acc.task_id,
            "entries": entries,
        }
        if acc.session_id:
            row["session_id"] = acc.session_id
        rows.append(row)
    return rows


def _supports_for_session(log: Any) -> bool:
    return callable(getattr(log, "for_session", None))


def _fetch_trace_events(fetch: Any, key: str, *, limit: int) -> list[Any]:
    """Fetch trace-lane events with a type-aware limit when the log supports it.

    ``types=_TRACE_EVENT_TYPES`` makes ``limit`` count matched trace rows, so a
    task whose recent event tail is flooded with non-trace rows (e.g. a
    budget-incident loop) cannot starve the window. Test fakes (and any legacy
    log) without the ``types`` keyword fall back to the untyped fetch — same
    tolerance pattern as ``_list_sessions``.
    """

    try:
        return list(fetch(key, limit=limit, types=_TRACE_EVENT_TYPES))
    except TypeError:
        return list(fetch(key, limit=limit))


class _TraceAccumulator:
    """Collects a persona instance's trace events across lanes, then renders
    them chronologically into a bounded list of redaction-safe entry dicts."""

    __slots__ = ("instance_id", "persona_id", "task_id", "session_id", "_events")

    def __init__(self, *, instance_id: str, persona_id: str, task_id: str | None, session_id: str | None):
        self.instance_id = instance_id
        self.persona_id = persona_id
        self.task_id = task_id or None
        self.session_id = session_id or None
        self._events: list[Any] = []

    def extend(self, events: Iterable[Any]) -> None:
        self._events.extend(events)

    def entries(self, *, tail: int, accountant: "ProjectionAccountant | None" = None) -> list[dict[str, Any]]:
        ordered = sorted(self._events, key=_trace_event_sort_key)
        rendered: list[dict[str, Any]] = []
        unrenderable = 0
        for event in ordered:
            entry = _trace_entry(event)
            if entry is None:
                unrenderable += 1
                continue
            rendered.append(entry)
        kept = _retain_trace_tail(rendered, tail=tail)
        if accountant is not None:
            accountant.consider(len(self._events))
            accountant.include(len(kept))
            if unrenderable:
                accountant.drop("unrenderable_entry", count=unrenderable, entity_id=self.instance_id)
            truncated = len(rendered) - len(kept)
            if truncated > 0:
                # Deliberate bound: the trace lane keeps a tail window.
                accountant.drop(
                    "tail_truncated",
                    count=truncated,
                    entity_id=self.instance_id,
                    by_design=True,
                )
                accountant.mark_truncated()
        return kept


def _retain_trace_tail(rendered: list[dict[str, Any]], *, tail: int) -> list[dict[str, Any]]:
    if len(rendered) <= tail:
        return rendered
    latest_start = max(0, len(rendered) - tail)
    keep = {index for index in range(latest_start, len(rendered))}
    keep.update(
        index
        for index, entry in enumerate(rendered)
        if _priority_trace_entry(entry)
    )
    while len(keep) > tail:
        removable = [index for index in sorted(keep) if not _priority_trace_entry(rendered[index])]
        if not removable:
            break
        keep.remove(removable[0])
    if len(keep) > tail:
        keep = set(sorted(keep)[-tail:])
    return [entry for index, entry in enumerate(rendered) if index in keep]


def _priority_trace_entry(entry: dict[str, Any]) -> bool:
    return safe_assignment_token(entry.get("event")) in {
        "assignment_created",
        "assignment_closed",
    }


def _trace_event_sort_key(event: Any) -> tuple[int, float, str]:
    """Chronological sort key tolerant of missing/odd timestamps. Events with a
    real ``ts`` sort by time; anything unparseable sinks to the front in a
    stable, comparison-safe way (no naive/aware datetime mixing)."""

    ts = getattr(event, "ts", None)
    try:
        return (1, ts.timestamp(), "")
    except Exception:
        return (0, 0.0, str(ts or ""))
